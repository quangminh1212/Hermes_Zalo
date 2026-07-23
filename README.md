# Hermes_Zalo

**Unofficial Zalo personal messaging for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**  
Chat with your AI agent on Zalo the same way you do on Telegram / WhatsApp.

[![Node](https://img.shields.io/badge/node-%3E%3D18-brightgreen)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![zca-js](https://img.shields.io/badge/zca--js-2.1.2-purple)](https://github.com/RFS-ADRENO/zca-js)
[![Hermes](https://img.shields.io/badge/Hermes-platform%20plugin-orange)](https://hermes-agent.nousresearch.com/)

> ⚠️ **Ban risk.** This uses unofficial `zca-js` (not Zalo OA API).  
> Use a **secondary Zalo account** only. Never your main / banking nick.

---

## Why Hermes_Zalo?

| | Telegram bot | **Hermes_Zalo** |
|--|--------------|-----------------|
| Official API | ✅ BotFather | ❌ personal client |
| Setup | token only | QR once + bridge |
| Cost | free | free |
| Media / typing | ✅ | ✅ |
| Vietnam daily chat | so-so | **native Zalo** |

OpenClaw-style **zalouser** pattern: small **Node bridge** + **Hermes platform plugin**.

---

## Features

| Feature | Status |
|---------|--------|
| Text DM / group in & out (chunk 2000) | ✅ |
| Typing indicator | ✅ |
| Outbound image / video / voice / file (`MEDIA:`) | ✅ |
| Inbound media (when Zalo sends URL) | ✅ |
| `get_chat_info` | ✅ |
| Seen receipts | ✅ |
| Quote / reply context (inbound) | ✅ |
| **Allowlist hot-reload** (no restart) | ✅ `POST /allowlist` |
| Anti-hang platform hints | ✅ |
| Native buttons / poll clarify | ❌ personal API limits |
| Edit message | ❌ personal API limits |

---

## Architecture

```
Zalo app  ←→  zca-js  ←→  bridge.js :3001  ←→  Hermes plugin  ←→  Agent
                              │
                         localhost only
```

```
Hermes_Zalo/
├── bridge/          # Node HTTP bridge (zca-js)
│   ├── bridge.js
│   └── package.json
├── plugin/          # Hermes platform adapter
│   ├── adapter.py
│   ├── plugin.yaml
│   └── __init__.py
├── scripts/         # install / pair (Windows + bash)
├── docs/            # SETUP · API
├── .env.example
└── README.md
```

---

## External module

This repo is **not** part of Hermes core. Attach / detach when needed:

```powershell
# attach
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Dev\Hermes_Zalo\scripts\install.ps1

# detach (removes junctions; does not delete this repo)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Dev\Hermes_Zalo\scripts\uninstall.ps1
```

## Quick start (Windows)

### 1) Clone & install bridge

```bat
git clone https://github.com/quangminh1212/Hermes_Zalo.git C:\Dev\Hermes_Zalo
cd C:\Dev\Hermes_Zalo\bridge
npm install
```

Or one-shot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Dev\Hermes_Zalo\scripts\install.ps1
```

### 2) Link into Hermes home

```powershell
# junctions (admin not required for junctions on same volume usually)
$h = "$env:LOCALAPPDATA\hermes"
cmd /c mklink /J "%LOCALAPPDATA%\hermes\scripts\zalo-bridge" "C:\Dev\Hermes_Zalo\bridge"
cmd /c mklink /J "%LOCALAPPDATA%\hermes\plugins\zalo-platform" "C:\Dev\Hermes_Zalo\plugin"
```

`scripts\install.ps1` does this for you.

### 3) Env (`%LOCALAPPDATA%\hermes\.env`)

```env
ZALO_ENABLED=true
ZALO_BRIDGE_PORT=3001
ZALO_ALLOWED_USERS=*
ZALO_ALLOW_ALL_USERS=true
ZALO_FORWARD_SELF_MESSAGES=true
```

After first DM, tighten allowlist to your UID (see below).

### 4) Enable plugin + pair QR

```bat
hermes plugins enable zalo-platform
```

Start bridge (or full headless stack):

```bat
cd C:\Dev\Hermes_Zalo\bridge
set HERMES_HOME=%LOCALAPPDATA%\hermes
set ZALO_SESSION_DIR=%LOCALAPPDATA%\hermes\zalo\session
node bridge.js --port 3001
```

- QR file: `%LOCALAPPDATA%\hermes\zalo\session\qr.png`  
- or http://127.0.0.1:3001/qr.png  
- Scan with **secondary** Zalo app.

Restart Hermes gateway so the platform attaches. Then DM the paired account.

### 5) Verify

```bat
curl http://127.0.0.1:3001/health
```

Expect `"status":"connected"` and `features` including `media`, `allowlist_hot_reload`.

---

## Allowlist (no hang / no restart)

```bat
curl -s -X POST http://127.0.0.1:3001/allowlist ^
  -H "Content-Type: application/json" ^
  -d "{\"users\":\"YOUR_UID\",\"allowAll\":false}"
```

Also set `ZALO_ALLOWED_USERS=YOUR_UID` in `.env` for next boot.

> **Anti-hang:** never restart gateway / kill bridge **from a Zalo chat session** — approval prompts freeze the turn for minutes. Change allowlist via HTTP; restart only from desktop/schtasks.

---

## Bridge API (localhost)

| Method | Path | |
|--------|------|--|
| GET | `/health` | status, ownId, features, allowlist |
| GET | `/messages` | drain inbound queue |
| POST | `/send` | `{chatId, message, isGroup?}` |
| POST | `/send-media` | `{chatId, filePath\|fileUrl, mediaType, caption?}` |
| POST | `/typing` | `{chatId, isGroup?}` |
| GET | `/chat/:id` | user / group info |
| GET/POST | `/allowlist` | hot-reload |
| GET | `/qr` `/qr.png` | pairing |
| POST | `/pair` | new QR |

Full detail: [docs/API.md](docs/API.md) · install notes: [docs/SETUP.md](docs/SETUP.md)

---

## Env reference

| Variable | Default | |
|----------|---------|--|
| `ZALO_ENABLED` | — | `true` to load plugin |
| `ZALO_BRIDGE_PORT` | `3001` | HTTP port |
| `ZALO_ALLOWED_USERS` | `*` | UIDs CSV or `*` |
| `ZALO_ALLOW_ALL_USERS` | — | `true` / `false` |
| `ZALO_FORWARD_SELF_MESSAGES` | `true` | phone → agent |
| `ZALO_SEND_SEEN` | `true` | seen receipts |
| `ZALO_POLL_INTERVAL` | `0.4` | adapter poll (s) |
| `ZALO_HOME_CHANNEL` | — | cron / notify chat id |
| `ZALO_SESSION_DIR` | `%HERMES_HOME%\zalo\session` | credentials |

---

## Security

1. Secondary account only  
2. Bridge binds **127.0.0.1** only  
3. Protect `credentials.json` (session = full account)  
4. Prefer strict allowlist (not `*`) in production  
5. Unofficial → violates Zalo ToS; you accept the risk  

---

## Related

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)  
- [zca-js](https://github.com/RFS-ADRENO/zca-js)  
- OpenClaw **zalouser** pattern (inspiration)

---

## License

MIT — see [LICENSE](LICENSE).

**Not affiliated with Zalo / VNG or Nous Research.** Community integration.
