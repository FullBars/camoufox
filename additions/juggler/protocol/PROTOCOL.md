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
