#!/usr/bin/env python3
"""Assemble index.html: inject snapshot + score receipt into page_template.html.
Re-runnable, stdlib only. Output: index.html in this dir."""
import json
import re
import sys

BASE = "/home/clawdbot/.openclaw/workspace/flop-leaderboard"

def payload(path):
    with open(path) as f:
        obj = json.load(f)
    # </script>-safe and HTML-safe JSON literal
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c")

def main():
    tpl = open(BASE + "/page_template.html").read()
    snap = payload(BASE + "/leaderboard.json")
    score = payload(BASE + "/sample_score.json")
    for token in ("__SNAPSHOT_JSON__", "__OUR_SCORE_JSON__"):
        if not re.search(re.escape(token), tpl):
            sys.exit("template missing " + token)
    html = tpl.replace("__SNAPSHOT_JSON__", snap).replace("__OUR_SCORE_JSON__", score)
    for token in ("__SNAPSHOT_JSON__", "__OUR_SCORE_JSON__"):
        if token in html:
            sys.exit("replacement failed for " + token)
    out = BASE + "/index.html"
    with open(out, "w") as f:
        f.write(html)
    print("wrote", out, len(html), "bytes")

if __name__ == "__main__":
    main()
