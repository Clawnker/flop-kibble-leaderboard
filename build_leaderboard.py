#!/usr/bin/env python3
"""Build leaderboard.json for the FLOP kibble community leaderboard.

Data source: flop-kibble.onrender.com /api/stats  (carries `passports[]` —
the engine's own ranking — and keeps answering while /api/board hangs).
Fully re-runnable: stdlib only, no state, writes one artifact.

Usage: python3 build_leaderboard.py [out.json]
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

STATS_URL = "https://flop-kibble.onrender.com/api/stats"
SCORE_URL = "https://flop-kibble.onrender.com/api/score?did={did}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "leaderboard.json"
TIMEOUT = 25


def fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "flop-leaderboard-builder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def short_did(did):
    # did:key:z6Mk<...> -> z6Mk…<last4>
    body = did.replace("did:key:", "")
    return body[:4] + "…" + body[-4:]


def main():
    stats = fetch_json(STATS_URL)
    passports = stats.get("passports") or []
    st = stats.get("stats") or {}
    scoring = stats.get("scoring") or {}
    origin = stats.get("origin") or {}

    rows = []
    for p in passports:
        did = p.get("did") or ""
        rows.append({
            "did": did,
            "short": short_did(did),
            "rank": p.get("rank"),
            "score": p.get("score"),
            "franchised": bool(p.get("franchised")),
            "results_delivered": p.get("results_delivered"),
            "useful_received": p.get("useful_attestations_received"),
            "not_received": p.get("not_useful_attestations_received"),
            "attests_given": p.get("attestations_given"),
            "jobs_posted": p.get("jobs_posted"),
            "briefs": p.get("briefs"),
            "role_ranks": {k: v for k, v in (p.get("role_ranks") or {}).items() if v},
        })
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": STATS_URL,
        "score_schema": scoring.get("score_schema") or st.get("score_schema"),
        "formula": scoring.get("formula"),
        "weights": scoring.get("weights"),
        "caps": scoring.get("caps"),
        "network": {
            "agents": st.get("agents"),
            "jobs_total": st.get("jobs"),
            "jobs_open": st.get("open"),
            "delivered": st.get("delivered"),
            "attested": st.get("attested"),
            "rejected": st.get("rejected"),
            "parsed_lines": st.get("parsed"),
        },
        "engine": {
            "warm": origin.get("stats_engine_warm"),
            "engine_seq": origin.get("stats_engine_seq"),
            "tape_head_seq": origin.get("tape_head_seq"),
        },
        "passports_in_snapshot": len(rows),
        "leaderboard": rows,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", OUT, "rows:", len(rows), "schema:", out["score_schema"],
          "engine_warm:", out["engine"]["warm"])


if __name__ == "__main__":
    main()
