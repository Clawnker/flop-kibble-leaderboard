#!/usr/bin/env python3
"""Point kibble.clawnker.work at the GitHub Pages leaderboard.

Steps: verify CF token -> create DNS-only CNAME -> wait for propagation ->
set Pages custom domain -> commit CNAME file -> enforce HTTPS -> verify.

Usage: CF_API_TOKEN=xxx python3 setup_domain.py [subdomain] [github-page-host]
Stdlib only. Never prints the token.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ZONE_NAME = "clawnker.work"
SUBDOMAIN = sys.argv[1] if len(sys.argv) > 1 else "kibble"
PAGE_HOST = sys.argv[2] if len(sys.argv) > 2 else "clawnker.github.io"
REPO = "Clawnker/flop-kibble-leaderboard"
REPO_DIR = "/home/clawdbot/.openclaw/workspace/flop-leaderboard"
FQDN = SUBDOMAIN + "." + ZONE_NAME
CF = "https://api.cloudflare.com/client/v4"


def cf(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CF + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:400]
        raise SystemExit("CF API " + str(e.code) + " on " + path + ": " + body_text)


def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def dig(resolve, rtype, target):
    out = run("dig +short " + rtype + " " + target + " @" + resolve).stdout.strip()
    return out


def resolve_doh(name, rtype="A"):
    """Resolve via DNS-over-HTTPS. ALWAYS use this to verify DNS here: the local
    resolver negative-caches NXDOMAIN for the zone's SOA minimum (1800s), so a
    name queried a second or two after creation keeps returning NXDOMAIN for
    ~30 min even though the zone serves it correctly (cost us a false 'CNAME is
    broken in this zone' diagnosis on 2026-09-27)."""
    url = "https://cloudflare-dns.com/dns-query?name=" + name + "&type=" + rtype
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    answers = [(a.get("type"), a.get("data")) for a in (d.get("Answer") or [])]
    return d.get("Status"), answers


def main():
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("CF_API_TOKEN not set")

    v = cf("GET", "/user/tokens/verify", token)
    print("1. token verify:", v["result"]["status"])

    zones = cf("GET", "/zones?name=" + ZONE_NAME, token)
    if not zones["result"]:
        raise SystemExit("zone " + ZONE_NAME + " not visible to this token")
    zone_id = zones["result"][0]["id"]
    print("2. zone ok:", ZONE_NAME, zone_id[:8] + "...")

    recs = cf("GET", "/zones/" + zone_id + "/dns_records?type=CNAME&name=" + FQDN, token)
    body = {"type": "CNAME", "name": FQDN, "content": PAGE_HOST,
            "ttl": 1, "proxied": True, "comment": "GitHub Pages: FLOP kibble leaderboard"}
    if recs["result"]:
        rid = recs["result"][0]["id"]
        cf("PUT", "/zones/" + zone_id + "/dns_records/" + rid, token, body)
        print("3. CNAME updated ->", PAGE_HOST, "(proxied, mirroring this zone's apex config)")
    else:
        cf("POST", "/zones/" + zone_id + "/dns_records", token, body)
        print("3. CNAME created ->", PAGE_HOST, "(proxied, mirroring this zone's apex config)")

    # propagation: verify via DoH (NOT local dig — see resolve_doh docstring)
    print("4. waiting for DNS propagation (up to 90s, via DoH)...")
    seen = False
    for i in range(18):
        try:
            status, answers = resolve_doh(FQDN, "A")
        except Exception as e:
            status, answers = None, []
        if status == 0 and answers:
            print("   resolving after ~" + str(i * 5) + "s:", answers[:2])
            seen = True
            break
        time.sleep(5)
    if not seen:
        print("   WARNING: not resolving via DoH yet — continuing anyway")

    # GitHub Pages custom domain
    print("5. setting GitHub Pages custom domain...")
    gh = run("gh api -X PUT repos/" + REPO + "/pages -f 'source[branch]=main' -f 'source[path]=/' -f cname=" + FQDN)
    if gh.returncode != 0:
        print("   gh said:", (gh.stderr or gh.stdout).strip()[:300])
    else:
        print("   pages cname set:", FQDN)

    # commit the CNAME file (Pages requires it for custom domains)
    print("6. committing CNAME file...")
    with open(REPO_DIR + "/CNAME", "w") as f:
        f.write(FQDN + chr(10))
    run("git add CNAME", cwd=REPO_DIR)
    run("git -c user.email=claw@local -c user.name='Clawnker Bot' commit -m 'custom domain: " + FQDN + "'", cwd=REPO_DIR)
    push = run("git push origin main", cwd=REPO_DIR)
    print("   push:", "ok" if push.returncode == 0 else (push.stderr or push.stdout).strip()[:200])

    # wait for the Pages build + cert, then enforce HTTPS. Use --resolve with the
    # DoH-resolved edge IP: the local resolver may still negative-cache this name.
    print("7. waiting for the site to serve (up to 5 min)...")
    try:
        _, doh_answers = resolve_doh(FQDN, "A")
        edge_ip = doh_answers[0][1] if doh_answers else ""
    except Exception:
        edge_ip = ""
    resolve_flag = ("--resolve " + FQDN + ":443:" + edge_ip) if edge_ip else ""
    code = ""
    for i in range(20):
        time.sleep(15)
        code = run("curl -s -o /dev/null -w '%{http_code}' --max-time 15 " + resolve_flag + " https://" + FQDN + "/").stdout.strip()
        print("   [" + str(i * 15) + "s] https://" + FQDN + " -> " + code + (" (edge " + edge_ip + ")" if edge_ip else ""))
        if code == "200":
            break

    if code == "200":
        gh2 = run("gh api -X PUT repos/" + REPO + "/pages -f cname=" + FQDN + " -F https_enforced=true")
        print("8. enforce https:", "ok" if gh2.returncode == 0 else (gh2.stderr or gh2.stdout).strip()[:200])
        pages = run("gh api repos/" + REPO + "/pages")
        try:
            pj = json.loads(pages.stdout)
            print("   pages state:", json.dumps({"html_url": pj.get("html_url"),
                                                 "cname": pj.get("cname"),
                                                 "https_enforced": pj.get("https_enforced"),
                                                 "status": pj.get("status")}))
        except Exception:
            pass
    else:
        print("8. custom domain not serving yet — Pages cert may still be provisioning; re-check the URL shortly")

    # final content check
    final = run("curl -s --max-time 20 https://" + FQDN + "/")
    ok = "kibble community leaderboard" in final.stdout
    print("9. content check on https://" + FQDN + "/:", "PASS (page served)" if ok else "FAIL (unexpected body)")
    print("DONE" if (ok and code == "200") else "PARTIAL — see steps above")


if __name__ == "__main__":
    main()
