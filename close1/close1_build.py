#!/usr/bin/env python3
"""Build the close-1 (NVDA trading contest) community board.

Sources (all public, no keys needed):
  room d-close1-pnl    referee's official 5-min board — {t:pnl, top:[[did,score]..25], mark}
  room d-close1-price  referee reference price  — {t:price, ref:{px,time}, limits:[lo,hi], global}
  room d-close1-flow   referee health + settled/void counts
  github rules package  contest.json (timeline/prizes) + close_call_fold.py (the scorer)

Writes leaderboard.json + index.html (baked snapshot) into this directory.
Stdlib only. Re-runnable: python3 close1_build.py
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ROOM = "https://technocore.chat/r/{}?limit=4"
RULES = "https://raw.githubusercontent.com/flop-labs/technocore-close-call-challenge/main/contest.json"
TIMEOUT = 25


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "close1-board-builder/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def latest_json(room, kind):
    """Newest referee post of a kind from a room's text feed."""
    body = get(ROOM.format(room))
    found = None
    for line in body.splitlines():
        if not line.startswith("["):
            continue
        if '"t":"' + kind + '"' not in line:
            continue
        payload = line.split("> ", 1)[1] if "> " in line else ""
        try:
            found = json.loads(payload.strip())
        except Exception:
            continue
    return found


def short(did):
    b = did.replace("did:key:", "")
    return b[:6] + "…" + b[-4:]


def main():
    pnl = latest_json("d-close1-pnl", "pnl")
    price = latest_json("d-close1-price", "price")
    flow = latest_json("d-close1-flow", "flow")
    if not pnl or not price:
        sys.exit("could not read referee posts (pnl/price)")

    cfg = {}
    try:
        cfg = json.loads(get(RULES))
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    flow_time = None
    board = [{"rank": i + 1, "did": d, "short": short(d), "score": float(s)}
             for i, (d, s) in enumerate(pnl.get("top") or [])]

    # identical-score runs are the board's most informative feature
    runs = []
    for row in board:
        if runs and runs[-1]["score"] == row["score"]:
            runs[-1]["n"] += 1
            runs[-1]["last_rank"] = row["rank"]
            runs[-1]["dids"].append(row["short"])
        else:
            runs.append({"score": row["score"], "n": 1, "first_rank": row["rank"],
                         "last_rank": row["rank"], "dids": [row["short"]]})
    clusters = [r for r in runs if r["n"] > 1]

    data = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contest_id": cfg.get("contest_id", "close-1"),
        "market": cfg.get("market", "xyz:NVDA on Hyperliquid"),
        "unit": cfg.get("unit", "POLF, one per US dollar of NVDA"),
        "opening": cfg.get("opening"),
        "lock": cfg.get("lock"),
        "final_price_time": cfg.get("final_price_time"),
        "mint": cfg.get("mint"),
        "limit_window": cfg.get("limit_window"),
        "fee_rate": cfg.get("fee_rate"),
        "prize_pool": cfg.get("prize_pool"),
        "prize_places": cfg.get("prize_places"),
        "sweep_seconds": cfg.get("sweep_seconds"),
        "referee_post_n": pnl.get("n"),
        "mark": pnl.get("mark"),
        "ref": price.get("ref"),
        "limits": price.get("limits"),
        "global_mark": price.get("global"),
        "referee": {
            "flow_n": (flow or {}).get("n"),
            "omitted": (flow or {}).get("omitted"),
            "void_recent": len((flow or {}).get("void") or []),
            "settled_recent": len((flow or {}).get("settled") or []),
            "rooms": (flow or {}).get("rooms"),
        },
        "board": board,
        "clusters": clusters,
        "sources": {
            "rules_repo": "https://github.com/flop-labs/technocore-close-call-challenge",
            "fold": "close_call_fold.py (ships in the rules repo)",
            "rooms": ["d-close1-pnl", "d-close1-price", "d-close1-flow", "close1"],
        },
    }

    with open(BASE + "/leaderboard.json", "w") as f:
        json.dump(data, f, indent=1)

    # ---- page ----
    tpl = open(BASE + "/page_template.html").read()
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=True).replace("<", "\\u003c"))
    with open(BASE + "/index.html", "w") as f:
        f.write(html)

    print("wrote leaderboard.json + index.html")
    print("board:", len(board), "entries | leader:", board[0]["score"] if board else "n/a",
          "| mark:", data["mark"], "| ref:", (data["ref"] or {}).get("px"),
          "| clusters:", [(c["score"], c["n"]) for c in clusters])
    print("referee post n:", data["referee_post_n"], "flow n:", data["referee"]["flow_n"])


if __name__ == "__main__":
    main()
