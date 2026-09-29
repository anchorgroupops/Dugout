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


@pytest.mark.parametrize("path,method", [
    ("/api/announcer/voice-profiles", "POST"),                  # add a fish.audio voice
    ("/api/announcer/voice-profiles/fish_01234567", "DELETE"),  # remove a custom voice
    ("/api/announcer/voice-profiles/default", "POST"),          # keeps the write block
    ("/api/announcer/voice-library/search", "GET"),             # catalogue proxy
])
def test_voice_library_paths_reach_flask(path, method):
    pat, allowed = _match(path)
    assert pat is not None and (allowed is None or method in allowed), (path, pat, allowed)


def test_voice_default_keeps_the_long_render_timeout_location():
    pat, _ = _match("/api/announcer/voice-profiles/default")
    assert "render-all" in pat

# ---------------------------------------------------------------------------
# Team-password gate (SIGN-021): nginx asks Flask before serving data/audio
# ---------------------------------------------------------------------------

def _location_body(header_regex: str) -> str:
    """Body of the first location whose header matches `header_regex`
    (brace-matched, so nested locations are included)."""
    text = NGINX_CONF.read_text()
    m = re.search(r"^\s*location\s+" + header_regex + r"\s*\{", text, re.M)
    assert m, f"no nginx location matching {header_regex!r}"
    depth, i = 0, m.end() - 1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return text[m.end():i]


def _own_directives(body: str) -> str:
    """Drop nested location blocks so only this block's own lines remain."""
    return re.sub(r"location[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", body)


_GATED_LOCATIONS = {
    "data tree": r"\^~\s+/data/",
    "data snapshot json": r"~\s+\^/data/sharks/\S+",
    "bundled data fallback": r"@data_bundled",
    "announcer clips": r"/announcer-clips/",
    "walk-up music": r"~\s+\^/audio/music/\S+",
    "soundboard": r"~\s+\^/audio/soundboard/\S+",
}


@pytest.mark.parametrize("name,header", list(_GATED_LOCATIONS.items()))
def test_gated_location_requires_session(name, header):
    body = _own_directives(_location_body(header))
    assert re.search(r"^\s*auth_request\s+/_auth;", body, re.M), f"{name}: missing auth_request /_auth"
    assert re.search(r"^\s*error_page\s+401\s+=\s+@unauth;", body, re.M), f"{name}: missing error_page 401 = @unauth"


@pytest.mark.parametrize("name,header", list(_GATED_LOCATIONS.items()))
def test_gated_location_is_never_publicly_cacheable(name, header):
    # Cloudflare's edge caches .mp3/.ogg by default; `public` would let it
    # hand a gated file to someone with no session.
    for value in re.findall(r'Cache-Control\s+"([^"]*)"', _location_body(header)):
        assert "public" not in value, f"{name}: Cache-Control {value!r}"


def test_auth_subrequest_location_is_internal():
    body = _location_body(r"=\s+/_auth")
    assert re.search(r"^\s*internal;", body, re.M)
    assert re.search(r"^\s*proxy_pass\s+\$api_upstream/api/auth/check;", body, re.M)
    assert re.search(r"^\s*proxy_pass_request_body\s+off;", body, re.M)
    assert re.search(r'^\s*proxy_set_header\s+Content-Length\s+"";', body, re.M)
    assert re.search(r"^\s*proxy_set_header\s+X-Original-URI\s+\$request_uri;", body, re.M)
    assert re.search(r"^\s*proxy_set_header\s+Host\s+\$host;", body, re.M)


def test_unauth_location_returns_json_401_uncached():
    body = _location_body(r"@unauth")
    assert re.search(r"""^\s*return\s+401\s+'\{"error":"auth_required"\}';""", body, re.M)
    assert re.search(r"^\s*default_type\s+application/json;", body, re.M)
    assert re.search(r'Cache-Control\s+"no-store"', body)


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/logout"])
def test_login_logout_allow_post(path):
    _pat, allowed = _match(path)
    assert allowed is not None and "POST" in allowed


def test_auth_check_goes_through_read_catch_all():
    pat, allowed = _match("/api/auth/check")
    assert pat == "/api/" and "GET" in allowed


def test_only_data_and_audio_are_gated():
    # No server-level auth_request, and exactly the gated locations carry
    # one: the SPA shell, /assets/, sw.js and the manifest stay public.
    text = NGINX_CONF.read_text()
    assert "auth_request" not in _own_directives(text.split("server {", 1)[1])
    assert len(re.findall(r"^\s*auth_request\s", text, re.M)) == len(_GATED_LOCATIONS)


# ---------------------------------------------------------------------------
# Coach uploads: the method check above passes even when the songs regex
# catches the upload, which then 413s at the server's 128k body limit.
# ---------------------------------------------------------------------------

def _body_size_bytes(body: str) -> int:
    m = re.search(r"^\s*client_max_body_size\s+(\d+)([kKmM]?);", _own_directives(body), re.M)
    if not m:
        return 128 * 1024  # server-level default in nginx.conf
    return int(m.group(1)) * {"": 1, "k": 1024, "m": 1024 * 1024}[m.group(2).lower()]


@pytest.mark.parametrize("path", [
    "/api/announcer/songs/07-jane/upload",
    "/api/announcer/calls/07-jane/upload",
    "/api/announcer/soundboard/upload",
])
def test_upload_paths_accept_25_mb(path):
    pat, allowed = _match(path)
    assert pat and "upload" in pat, f"{path} matched {pat}"
    assert "POST" in allowed
    body = _location_body(r"~\s+" + re.escape(pat))
    assert _body_size_bytes(body) >= 25 * 1024 * 1024


@pytest.mark.parametrize("path,method", [
    ("/api/announcer/batting-order", "PUT"),
    ("/api/announcer/batting-order", "DELETE"),
    ("/api/announcer/soundboard/crowd", "DELETE"),
    ("/api/announcer/soundboard", "GET"),
])
def test_order_and_soundboard_paths_reach_flask(path, method):
    pat, allowed = _match(path)
    assert pat is not None and (allowed is None or method in allowed), (path, pat, allowed)
