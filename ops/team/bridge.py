#!/usr/bin/env python3
"""JBHNTR Team Boardroom client (R3-35). Stdlib only.

  bridge.py peek                      -> prints the number of unhandled Founder messages
  bridge.py pull                      -> writes them to $CHAT_FILE (JSON, mode 600), prints the count
  bridge.py reply [BODY]              -> posts a CEO chat reply (BODY or stdin)
  bridge.py log ROLE TASK STATUS SUMMARY CYCLE [--detail-file F]   -> one Live team row

Token + URL come ONLY from the runtime env file ($JBHNTR_TEAM/env, default ~/.jbhntr-team/env, the one run_cycle.sh
sources), never from argv or the process environment. Everything sent is passed through redact() first.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TEAM = Path(os.environ.get("JBHNTR_TEAM") or Path.home() / ".jbhntr-team")
DEFAULT_URL = "https://jbhntr.app"

# key=value / key: value where the key names a secret; vendor token shapes; Basic/Bearer creds; URL userinfo;
# long mixed-case+digit blobs (token_urlsafe-like). Lower-case hex (git shas) is left alone.
_PATTERNS = [
    re.compile(r"(?i)\b([\w-]*(?:token|passw(?:or)?d|pwd|secret|api[_-]?key|private[_-]?key|access[_-]?key)[\w-]*"
               r"[\"']?\s*[:=]\s*)[\"']?[^\s\"',;]+"),
    re.compile(r"\b([Bb]earer|Basic)\s+(?=\S*[\d=])[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
               r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"(?<![\w-])(?=[\w-]*[A-Z])(?=[\w-]*[a-z])(?=[\w-]*\d)[A-Za-z0-9_-]{32,}(?![\w-])"),
]


def load_env(path=None):
    """Parse `[export ]KEY=VALUE` lines (optionally quoted). No shell evaluation."""
    out = {}
    p = Path(path) if path else TEAM / "env"
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)=(.*)$", line)
        if m and not line.lstrip().startswith("#"):
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def redact(text, extra=()):
    if not text:
        return text
    for s in extra:  # the admin token itself (and anything else known-secret), wherever it appears
        if s and len(s) >= 6:
            text = text.replace(s, "[REDACTED]")
    for i, rx in enumerate(_PATTERNS):
        text = rx.sub((lambda m: m.group(1) + "[REDACTED]") if i == 0 else
                      (lambda m: m.group(1) + " [REDACTED]") if i == 1 else "[REDACTED]", text)
    return text


class Client:
    def __init__(self, env):
        self.url = (env.get("JBHNTR_APP_URL") or DEFAULT_URL).rstrip("/")
        self.token = env.get("JBHNTR_ADMIN_TOKEN", "")
        if not self.token:
            sys.exit("bridge: JBHNTR_ADMIN_TOKEN missing from the env file")

    def call(self, method, path, payload=None):
        req = urllib.request.Request(self.url + path, method=method)
        req.add_header("User-Agent", "jbhntr-team-bridge/1")  # the jbhntr.app edge 403s the default Python-urllib UA
        req.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{self.token}".encode()).decode())
        if payload is not None:
            req.data = json.dumps(payload).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            sys.exit(f"bridge: {method} {path} -> HTTP {e.code}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            sys.exit(f"bridge: {method} {path} failed: {type(e).__name__}")

    def clean(self, s):
        return redact(s, (self.token,))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bridge.py", description="JBHNTR Boardroom client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("peek")
    sub.add_parser("pull")
    r = sub.add_parser("reply")
    r.add_argument("body", nargs="?", help="reply text (default: stdin)")
    lg = sub.add_parser("log")
    for a in ("role", "task", "status", "summary", "cycle"):
        lg.add_argument(a)
    lg.add_argument("--detail-file")
    a = ap.parse_args(argv)

    c = Client(load_env())
    if a.cmd == "peek":
        print(int((c.call("GET", "/boardroom/peek") or {}).get("count", 0)))
    elif a.cmd == "pull":
        msgs = c.call("GET", "/boardroom/pull") or []
        dest = Path(os.environ.get("CHAT_FILE") or TEAM / "chat.json")
        tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=1)
        os.replace(tmp, dest)
        print(len(msgs))
    elif a.cmd == "reply":
        body = c.clean((a.body if a.body is not None else sys.stdin.read()).strip())
        if not body:
            sys.exit("bridge: empty reply")
        c.call("POST", "/boardroom/reply", {"body": body})
    else:
        row = {"agent": a.role, "task": c.clean(a.task), "status": a.status,
               "summary": c.clean(a.summary), "cycle": a.cycle}
        if a.detail_file:  # rendered as safe Markdown in Live team (R3-38)
            row["detail"] = c.clean(Path(a.detail_file).read_text(encoding="utf-8"))
        c.call("POST", "/boardroom/log", row)


if __name__ == "__main__":
    main()
