# Bridge HTTP API — Hermes_Zalo

Base URL: `http://127.0.0.1:3001` (default).  
**Host filter:** only `localhost` / `127.0.0.1` / `::1`.

## GET `/health`

```json
{
  "status": "connected",
  "queueLength": 0,
  "uptime": 120.5,
  "scriptHash": "e13b…",
  "ownId": "8458…",
  "displayName": "Nick",
  "error": null,
  "allowAll": false,
  "allowedUsers": ["2745…"],
  "features": [
    "text",
    "media",
    "typing",
    "chat_info",
    "allowlist_hot_reload",
    "seen",
    "inbound_media_meta"
  ]
}
```

`status`: `disconnected` | `pairing` | `connected`

## GET `/messages`

Drains the inbound queue (array). Each item:

```json
{
  "messageId": "…",
  "chatId": "…",
  "senderId": "…",
  "senderName": "…",
  "isGroup": false,
  "body": "hello",
  "fromMe": false,
  "timestamp": 1784700000000,
  "mediaType": "image",
  "mediaUrl": "https://…",
  "quote": { "msgId": "…", "body": "…", "ownerId": "…" }
}
```

## POST `/send`

```json
{ "chatId": "2745…", "message": "hi", "isGroup": false }
```

Long text is chunked at 2000 chars.

**200**

```json
{ "success": true, "messageId": "…", "messageIds": ["…"] }
```

## POST `/send-media`

```json
{
  "chatId": "2745…",
  "filePath": "C:/path/to/file.png",
  "mediaType": "image",
  "caption": "optional",
  "isGroup": false,
  "fileName": "optional.png"
}
```

Or `"fileUrl": "https://…"`.

`mediaType`: `image` | `video` | `voice` | `audio` | `document`

## POST `/typing`

```json
{ "chatId": "2745…", "isGroup": false }
```

Best-effort; failures are soft.

## GET `/chat/:id?isGroup=0`

Returns name, type, avatar / participants when available.

## GET `/allowlist` · POST `/allowlist`

```json
{ "users": "uid1,uid2", "allowAll": false }
```

`users` may be a string CSV or string array.  
**Hot-reload** — no process restart.

## GET `/me`

```json
{ "ownId": "…", "displayName": "…", "status": "connected" }
```

## Pairing

| | |
|--|--|
| `GET /qr` | JSON QR payload |
| `GET /qr.png` | PNG bytes |
| `POST /pair` | start / refresh QR login |

## CLI

```bat
node bridge.js --port 3001 --session "%LOCALAPPDATA%\hermes\zalo\session"
node bridge.js --pair-only
```

Env: `ZALO_BRIDGE_PORT`, `ZALO_SESSION_DIR`, `ZALO_ALLOWED_USERS`, `ZALO_ALLOW_ALL_USERS`, `ZALO_FORWARD_SELF_MESSAGES`, `ZALO_SEND_SEEN`, `HERMES_HOME`.
