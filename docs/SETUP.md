# SETUP — Hermes_Zalo

## Requirements

- Windows 10+ (also works on Linux/macOS with path tweaks)
- Node.js ≥ 18
- Hermes Agent installed (`%LOCALAPPDATA%\hermes`)
- Secondary Zalo account

## Install (Windows PowerShell)

```powershell
git clone https://github.com/quangminh1212/Hermes_Zalo.git C:\Dev\Hermes_Zalo
cd C:\Dev\Hermes_Zalo
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

What `install.ps1` does:

1. `npm install` in `bridge/`
2. Junctions:
   - `%LOCALAPPDATA%\hermes\scripts\zalo-bridge` → `...\Hermes_Zalo\bridge`
   - `%LOCALAPPDATA%\hermes\plugins\zalo-platform` → `...\Hermes_Zalo\plugin`
3. Appends Zalo keys to Hermes `.env` if missing
4. Runs `hermes plugins enable zalo-platform` when `hermes` is on PATH

## Manual install

```bat
cd C:\Dev\Hermes_Zalo\bridge
npm install

mklink /J "%LOCALAPPDATA%\hermes\scripts\zalo-bridge" "C:\Dev\Hermes_Zalo\bridge"
mklink /J "%LOCALAPPDATA%\hermes\plugins\zalo-platform" "C:\Dev\Hermes_Zalo\plugin"
```

Edit `%LOCALAPPDATA%\hermes\.env` — see root `.env.example`.

```bat
hermes plugins enable zalo-platform
```

## Pair QR

```bat
cd C:\Dev\Hermes_Zalo\bridge
set HERMES_HOME=%LOCALAPPDATA%\hermes
set ZALO_SESSION_DIR=%LOCALAPPDATA%\hermes\zalo\session
node bridge.js --port 3001
```

Or:

```powershell
.\scripts\pair.ps1
```

Open:

- `%LOCALAPPDATA%\hermes\zalo\session\qr.png`
- http://127.0.0.1:3001/qr.png

Scan with secondary Zalo. QR expires quickly → `POST /pair` for a fresh one.

Credentials: `%LOCALAPPDATA%\hermes\zalo\session\credentials.json`

## Start with Hermes gateway

Prefer your usual headless stack so WA + Zalo bridges start **before** `pythonw gateway`:

- `%LOCALAPPDATA%\hermes\logs\headless_full.ps1`

Or start bridge alone, then gateway.

## First message → lock allowlist

1. DM the paired nick from your phone  
2. Read UID from gateway log / bridge log (`senderId`)  
3. Hot-reload:

```bat
curl -s -X POST http://127.0.0.1:3001/allowlist -H "Content-Type: application/json" -d "{\"users\":\"UID\",\"allowAll\":false}"
```

4. Set `ZALO_ALLOWED_USERS=UID` and `ZALO_ALLOW_ALL_USERS=false` in `.env`

## Linux / macOS notes

```bash
git clone https://github.com/quangminh1212/Hermes_Zalo.git ~/Hermes_Zalo
cd ~/Hermes_Zalo && bash scripts/install.sh
```

Hermes home is often `~/.hermes` instead of `%LOCALAPPDATA%\hermes`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `bridge not found` | Check junction / copy `bridge` under `scripts/zalo-bridge` |
| `get_chat_info` abstract error | Old plugin — update `plugin/adapter.py`, restart gateway |
| QR “Cannot get scan result” | `POST /pair`, new QR |
| Hang on allowlist change | Use `POST /allowlist`, do **not** restart from Zalo chat |
| WinError 5 spawn node | Start bridge **before** pythonw gateway |
| Acc checkpoint | Secondary only; reduce spam rate |

## Uninstall

```bat
rmdir "%LOCALAPPDATA%\hermes\scripts\zalo-bridge"
rmdir "%LOCALAPPDATA%\hermes\plugins\zalo-platform"
hermes plugins disable zalo-platform
```

Set `ZALO_ENABLED=false` in `.env`. Session folder can stay or be deleted to unpair.
