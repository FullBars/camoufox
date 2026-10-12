"""SOCKS proxy selection for Juggler.

Firefox 156 authenticates SOCKS from nsIProxyInfo (newProxyInfoWithAuth).
These checks run that decision in node. They do not open a socket.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "additions" / "juggler" / "NetworkObserver.js"
PROTOCOL = ROOT / "additions" / "juggler" / "protocol" / "Protocol.js"


def _body_after(source: str, signature: str) -> str:
    start = source.find(signature)
    assert start != -1, signature
    brace = source.find("{", start + len(signature))
    depth = 0
    for index, char in enumerate(source[brace:], brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unclosed {signature}")


def _endpoints(calls: list) -> list:
    source = OBSERVER.read_text(encoding="utf-8")
    function = _body_after(source, "export function proxyEndpoint(proxy)")
    function = function.replace("export function", "function", 1)
    script = function + "\nconst calls = " + json.dumps(calls) + """;
const out = [];
for (const call of calls) {
  try {
    out.push({value: proxyEndpoint(call)});
  } catch (error) {
    out.push({error: error.message});
  }
}
console.log(JSON.stringify(out));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout)


def test_http_and_https_do_not_use_socks_auth():
    http, https = _endpoints([
        {"type": "http", "username": "u", "password": "p"},
        {"type": "https", "username": "u", "password": "p"},
    ])
    assert http["value"] == {"type": "http", "username": "", "password": "", "isolationKey": "", "auth": False}
    assert https["value"]["type"] == "https" and https["value"]["auth"] is False


def test_socks5_no_auth_and_user_pass():
    plain, alias, authed = _endpoints([
        {"type": "socks"},
        {"type": "socks5"},
        {"type": "socks5", "username": "router", "password": "secret"},
    ])
    assert plain["value"]["auth"] is False and plain["value"]["type"] == "socks"
    assert alias["value"] == plain["value"]
    value = authed["value"]
    assert value["auth"] is True
    assert value["type"] == "socks"
    assert value["username"] == "router" and value["password"] == "secret"
    other = _endpoints([{"type": "socks", "username": "router", "password": "other"}])[0]["value"]
    assert other["isolationKey"] != value["isolationKey"]
    assert "router" in value["isolationKey"] and "secret" in value["isolationKey"]


def test_socks_credentials_that_firefox_cannot_send_fail():
    results = _endpoints([
        {"type": "socks5", "password": "only"},
        {"type": "socks5", "username": "only"},
        {"type": "socks4", "username": "user", "password": "nope"},
        {"type": "socks5", "username": "u" * 256, "password": "p"},
        {"type": "socks5", "username": "u", "password": "p" * 256},
    ])
    assert all("error" in item for item in results)
    assert "password requires a username" in results[0]["error"]
    assert "requires a password" in results[1]["error"]
    assert "SOCKS4" in results[2]["error"]
    assert "255" in results[3]["error"] and "255" in results[4]["error"]


def test_socks4_userid_is_a_username_without_a_password():
    value = _endpoints([{"type": "socks4", "username": "ident"}])[0]["value"]
    assert value == {
        "type": "socks4",
        "username": "ident",
        "password": "",
        "isolationKey": "ident\0",
        "auth": True,
    }


def test_filter_wires_auth_without_dropping_http():
    source = OBSERVER.read_text(encoding="utf-8")
    apply_filter = _body_after(source, "applyFilter: (channel, defaultProxyInfo, proxyFilter) =>")
    assert "proxyEndpoint(proxy)" in apply_filter
    assert "newProxyInfoWithAuth" in apply_filter
    assert "newProxyInfo(" in apply_filter
    assert "TRANSPARENT_PROXY_RESOLVES_HOST" in apply_filter
    assert "endpoint.auth ?" in apply_filter
    # HTTP proxy credentials still come from the auth prompt, not the SOCKS constructor.
    prompt = _body_after(source, "\n  promptAuth(aChannel, level, authInfo)")
    assert "AUTH_PROXY" in prompt
    assert "proxy.username" in prompt
    assert "newProxyInfoWithAuth" not in prompt


def test_protocol_accepts_socks5_and_keeps_http():
    source = PROTOCOL.read_text(encoding="utf-8")
    for method in ("'setBrowserProxy':", "'setContextProxy':"):
        body = _body_after(source, method)
        for name in ("http", "https", "socks", "socks5", "socks4"):
            assert f"'{name}'" in body
        assert "username: t.Optional(t.String)" in body
        assert "password: t.Optional(t.String)" in body
    note = (ROOT / "additions" / "juggler" / "protocol" / "PROTOCOL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (note, readme):
        assert "socks5" in text
        assert "newProxyInfoWithAuth" in text or "RFC 1929" in text
