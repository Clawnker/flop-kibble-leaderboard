"""Offline regression tests: every HTTP call is replaced with a fixture."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from close1 import close1_build as builder


def feed(*payloads):
    return "\n".join(f"[fixture timestamp] referee> {payload}" for payload in payloads)


class ResponseDiagnosticsTests(unittest.TestCase):
    def request(self, raw, content_type="text/plain; charset=utf-8", url=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {} if content_type is None else {"Content-Type": content_type}
        response.read.return_value = raw
        err = io.StringIO()
        url = url or builder.ROOM.format("d-close1-pnl")
        with patch.object(builder.urllib.request, "urlopen", return_value=response) as opener, contextlib.redirect_stderr(err):
            body = builder.get(url)
        opener.assert_called_once()
        args, kwargs = opener.call_args
        self.assertEqual(args[0].full_url, url)
        self.assertEqual(kwargs, {"timeout": builder.TIMEOUT})
        response.read.assert_called_once_with()
        self.assertEqual(body, raw.decode("utf-8", "replace"))
        return err.getvalue()

    def test_metadata_and_envelope_counts_without_content(self):
        raw = b'private header\n[private] sender> {"t":"pnl"}\n[no delimiter]\nother> private\n\n'
        log = self.request(raw, "text/plain; private=secret")
        data = json.loads(log.removeprefix("feed response: "))
        self.assertEqual(data, {
            "room": "d-close1-pnl", "status": 200, "content_type": "text/plain",
            "bytes": len(raw), "shape": "text_or_other", "lines": 5,
            "nonempty_lines": 4, "bracket_lines": 2, "separator_lines": 2,
            "text_post_lines": 1,
        })
        for secret in ("private", "secret", "sender", '{"t":"pnl"}'):
            self.assertNotIn(secret, log)

    def test_empty_markup_json_and_unrecognized_envelopes(self):
        for raw, shape, posts in (
            (b"", "empty", 0), (b" \n", "empty", 0),
            (b"<html>private</html>", "markup_like", 0),
            (b'{"t":"pnl"}', "object_like", 0),
            (b'[{"t":"pnl"}]', "array_or_text_feed", 0),
            (b' [time] sender> {"t":"pnl"}', "array_or_text_feed", 0),
            (b'[time] sender> {"t":"pnl"}', "array_or_text_feed", 1),
            (b'\xffprivate', "text_or_other", 0),
        ):
            with self.subTest(raw=raw):
                data = json.loads(self.request(raw).removeprefix("feed response: "))
                self.assertEqual(data["shape"], shape)
                self.assertEqual(data["text_post_lines"], posts)
                self.assertEqual(data["bytes"], len(raw))

    def test_content_type_is_allowlisted_not_echoed(self):
        for header, expected in ((None, "missing"), ("TEXT/HTML; secret=x", "text/html"),
                                 ("application/json", "application/json"),
                                 ("private-secret\n::warning::private", "other")):
            with self.subTest(header=header):
                log = self.request(b"private", header)
                self.assertEqual(json.loads(log.removeprefix("feed response: "))["content_type"], expected)
                self.assertNotIn("private", log)
                self.assertNotIn("secret", log)
                self.assertNotIn("::warning::", log)

    def test_http_error_metadata_preserves_exception_without_reading_body(self):
        raw = MagicMock()
        error = urllib.error.HTTPError(builder.ROOM.format("d-close1-price"), 403,
                                       "private reason", {"Content-Type": "text/html; private=secret"}, raw)
        err = io.StringIO()
        with patch.object(builder.urllib.request, "urlopen", side_effect=error) as opener, contextlib.redirect_stderr(err):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                builder.get(builder.ROOM.format("d-close1-price"))
        self.assertIs(raised.exception, error)
        opener.assert_called_once()
        raw.read.assert_not_called()
        self.assertEqual(json.loads(err.getvalue().removeprefix("feed response: ")), {
            "room": "d-close1-price", "status": 403, "content_type": "text/html", "bytes": None,
        })

    def test_rules_response_has_no_feed_diagnostics(self):
        self.assertEqual(self.request(b'{"contest_id":"private"}', url=builder.RULES), "")


class RefereeTests(unittest.TestCase):
    def parse(self, body, kind="pnl"):
        with patch.object(builder, "get", return_value=body), contextlib.redirect_stderr(io.StringIO()):
            return builder.latest_json("d-close1-" + kind, kind)

    def test_compact_and_spaced_json(self):
        for payload in ('{"t":"pnl","n":1}', '{"n": 1, "t" : "pnl"}'):
            with self.subTest(payload=payload):
                self.assertEqual(self.parse(feed(payload)), {"t": "pnl", "n": 1})

    def test_last_matching_post_survives_invalid_and_other_posts(self):
        body = feed('{"t":"pnl","n":1}', '{"t": "pnl", "n": 2}',
                    '{"t":"pnl",broken}', '{"t":"price","n":3}')
        self.assertEqual(self.parse(body), {"t": "pnl", "n": 2})

    def test_non_objects_and_embedded_type_strings_do_not_match(self):
        for payload in ('null', '[]', '42', '"pnl"',
                        '{"t":"price","nested":{"t":"pnl"}}'):
            with self.subTest(payload=payload):
                self.assertIsNone(self.parse(feed(payload)))

    def test_requires_text_post_envelope(self):
        self.assertIsNone(self.parse('{"t":"pnl"}\n[header without separator]'))

    def test_diagnostic_identifies_room_and_counts_without_payload(self):
        err = io.StringIO()
        with patch.object(builder, "get", return_value=feed('private text', 'null')), contextlib.redirect_stderr(err):
            self.assertIsNone(builder.latest_json("d-close1-pnl", "pnl"))
        self.assertIn("room d-close1-pnl: no 'pnl' JSON object in 2 text posts", err.getvalue())
        self.assertIn("1 invalid JSON payloads; requested limit=4", err.getvalue())
        self.assertNotIn("private text", err.getvalue())

    def test_transport_error_is_not_reported_as_missing_post(self):
        with patch.object(builder, "get", side_effect=OSError("fixture transport failure")):
            with self.assertRaisesRegex(OSError, "fixture transport failure"):
                builder.latest_json("d-close1-pnl", "pnl")

    def test_missing_required_posts_preserves_snapshots_and_stops_requests(self):
        for missing in (("pnl",), ("price",), ("pnl", "price")):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                paths = [Path(directory) / name for name in ("leaderboard.json", "index.html")]
                for path in paths:
                    path.write_text("existing snapshot")

                def fake_get(url):
                    for kind in ("pnl", "price"):
                        if url == builder.ROOM.format("d-close1-" + kind):
                            return "" if kind in missing else feed(json.dumps({"t": kind}))
                    self.fail("Unexpected request after required input failure: " + url)

                with patch.object(builder, "BASE", directory), patch.object(builder, "get", side_effect=fake_get), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        builder.main()
                self.assertEqual(str(error.exception), "could not read referee posts: " + ", ".join(missing))
                self.assertEqual([path.read_text() for path in paths], ["existing snapshot"] * 2)

    def test_build_from_spaced_fixture_posts_and_optional_missing_flow(self):
        fixtures = {
            builder.ROOM.format("d-close1-pnl"): feed(json.dumps({"t": "pnl", "n": 7, "top": [["did:key:fixture", "2.5"]], "mark": "123"})),
            builder.ROOM.format("d-close1-price"): feed(json.dumps({"t": "price", "ref": {"px": "124", "time": "fixture-time"}})),
            builder.ROOM.format("d-close1-flow"): "",
            builder.RULES: '{"contest_id":"fixture-contest"}',
        }
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "page_template.html").write_text("<script>const data = __DATA__;</script>")
            with patch.object(builder, "BASE", directory), patch.object(builder, "get", side_effect=fixtures.__getitem__), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                builder.main()
            data = json.loads(Path(directory, "leaderboard.json").read_text())
            self.assertEqual(data["board"][0]["score"], 2.5)
            self.assertEqual(data["referee_post_n"], 7)
            self.assertEqual(data["ref"]["time"], "fixture-time")
            self.assertIsNone(data["referee"]["flow_n"])
            self.assertNotIn("__DATA__", Path(directory, "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
