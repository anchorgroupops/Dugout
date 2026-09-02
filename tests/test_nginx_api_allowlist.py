"""Every mutating Flask /api route must be reachable through nginx.

client/nginx.conf allow-lists API routes with `limit_except`; the catch-all
`location /api/` only permits GET. A route added to sync_daemon.py without a
matching nginx location 403s in production before Flask ever sees it (this
bit /api/evals, /api/practice, /api/announcer/repair, the player DELETE and
/api/auth/verify). This test models nginx's location selection closely
enough to catch that.
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF = ROOT / "client" / "nginx.conf"
DAEMON = ROOT / "tools" / "sync_daemon.py"

_LOC_RE = re.compile(r"^\s*location\s+(?:(=|~\*|~|\^~)\s+)?(\S+)\s*\{", re.M)
_ROUTE_RE = re.compile(
    r"@app\.route\(\s*['\"](/api/[^'\"]*)['\"]\s*,\s*methods=\[([^\]]*)\]", re.S
)


def _locations():
    """Yield (modifier, pattern, allowed_methods_or_None) in file order."""
    text = NGINX_CONF.read_text()
    out = []
    for m in _LOC_RE.finditer(text):
        # body = up to the matching close brace (locations here are flat
        # except the /data/ block, which is not an API location)
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]
        le = re.search(r"limit_except\s+([A-Z\s]+)\{", body)
        methods = set(le.group(1).split()) if le else None
        out.append((m.group(1) or "", m.group(2), methods))
    return out


def _match(path: str):
    """nginx order: exact, then ^~ / longest prefix, then first regex."""
    locs = _locations()
    for mod, pat, methods in locs:
        if mod == "=" and pat == path:
            return pat, methods
    best = None
    for mod, pat, methods in locs:
        if mod in ("", "^~") and path.startswith(pat):
            if best is None or len(pat) > len(best[0]):
                best = (pat, methods, mod)
    if best and best[2] == "^~":
        return best[0], best[1]
    for mod, pat, methods in locs:
        if mod in ("~", "~*"):
            flags = re.I if mod == "~*" else 0
            if re.search(pat, path, flags):
                return pat, methods
    return (best[0], best[1]) if best else (None, None)


def _mutating_routes():
    src = DAEMON.read_text()
    for rule, methods in _ROUTE_RE.findall(src):
        ms = {m.strip(" '\"") for m in methods.split(",")}
        ms -= {"GET", "HEAD", "OPTIONS"}
        if not ms:
            continue
        sample = re.sub(r"<int:[^>]+>", "1", rule)
        sample = re.sub(r"<[^>]+>", "abc123", sample)
        yield rule, sample, ms


@pytest.mark.parametrize("rule,sample,methods", list(_mutating_routes()))
def test_mutating_route_is_allowed_by_nginx(rule, sample, methods):
    pat, allowed = _match(sample)
    assert pat is not None, f"{rule}: no nginx location matches {sample}"
    if allowed is None:  # no limit_except => everything allowed
        return
    missing = methods - allowed
    assert not missing, (
        f"{rule}: nginx location `{pat}` allows {sorted(allowed)}, "
        f"Flask needs {sorted(methods)} — add/extend a location in client/nginx.conf"
    )
