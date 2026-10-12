# Juggler browser protocol

Camoufox speaks Playwright's Juggler protocol. The schema is `Protocol.js`.
This note covers the page-creation methods a client needs in order to put more
than one cookie partition on a single tab strip.

## `Browser.newPage`

Unchanged.

```json
{ "id": 1, "method": "Browser.newPage", "params": { "browserContextId": "optional" } }
```

Response: `{ "targetId": "<new page>" }`.

Opens a new browser window with one tab. Omit `browserContextId` for the
default context. Existing clients keep this behavior.

## `Browser.newPageInWindow`

```json
{
  "id": 2,
  "method": "Browser.newPageInWindow",
  "params": {
    "targetId": "<page already open in the window>",
    "browserContextId": "optional"
  }
}
```

Response: `{ "targetId": "<new page>" }`, the same shape as `Browser.newPage`.

The new tab is added to the window that contains `targetId` and becomes the
selected tab. `browserContextId` is the Firefox container (`userContextId`)
for that tab. Omit it for the default context, as with `Browser.newPage`.

There is no separate window id. The anchor is an existing page.

Cookie and storage isolation follow the context. `TargetRegistry` maps
`tab.userContextId` to the browser context, and that context's cookie jar is
keyed by the same id. The new tab does not inherit the anchor tab's container.

The operating-system window is shared. A context viewport still resizes that
window, which is what opening any tab in it already does.

Unknown `targetId`, unknown `browserContextId`, or a tab that does not land in
the requested window and context fails the call. The method does not fall back
to opening a window.

## `Browser.setBrowserProxy` and `Browser.setContextProxy`

Both methods take the same proxy object. `setContextProxy` also takes an
optional `browserContextId`; omit it for the default context. A context proxy
wins over the browser proxy.

```json
{
  "id": 3,
  "method": "Browser.setBrowserProxy",
  "params": {
    "type": "socks5",
    "host": "10.0.0.1",
    "port": 1080,
    "bypass": [],
    "username": "optional",
    "password": "optional"
  }
}
```

`type` is `http`, `https`, `socks`, `socks5`, or `socks4`.

`socks` and `socks5` are SOCKS5. Firefox's own name for that proxy is `socks`;
`socks5` is accepted and mapped to it. Omit `username` and `password` for a
no-auth proxy. With both set, the handshake is RFC 1929 username/password,
carried on `nsIProxyInfo` via `newProxyInfoWithAuth`. Each is at most 255
bytes. A password without a username, or a SOCKS5 username without a
password, fails the call.

`socks4` may carry a username, which is the SOCKS4 userid. Firefox does not
send a SOCKS4 password, so a password is rejected.

`http` and `https` are unchanged. Their username and password still go through
the HTTP proxy auth prompt, not through `newProxyInfoWithAuth` (Firefox
implements that method for SOCKS only).

The proxy resolves hostnames (`TRANSPARENT_PROXY_RESOLVES_HOST`), including
SOCKS5, so DNS for proxied connections is remote. This is TCP CONNECT.
Firefox's SOCKS layer does not implement SOCKS5 UDP ASSOCIATE.
