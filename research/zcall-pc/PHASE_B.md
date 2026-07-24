# Phase B — Reverse Zalo personal VoIP (auto-answer R&D)

**Status:** active research (2026-07-24)  
**Goal:** personal account auto-answer + Hermes realtime voice  
**Risk:** high ban / ToS / binary reverse — **acc phụ only**

---

## Architecture discovered (Zalo PC 26.7.10)

```
                    ┌─────────────────────────────┐
  Peer calls ──────►│  Zalo PC main (Electron)    │
                    │  zcall-v2 call-helper        │
                    │  handleControl(act=request)  │
                    │  handleRecvSignal(...)       │
                    └──────────┬──────────────────┘
                               │ $zcall.sendDataToNative
                               │ type: recvSignal | update | init
                               ▼
                    ┌─────────────────────────────┐
                    │  ZaloCall.exe + zcall_*.node │
                    │  RTP / RTCP / ZRTP media     │
                    │  vcmac: incomingCall/makeCall│
                    └─────────────────────────────┘
```

### Key code facts (from `app.asar`)

| Piece | Finding |
|-------|---------|
| Module | **`[zcall-v2] call-helper`** |
| Incoming detect | `isIncomingCallEvent(e)` → `e.act === "request" \|\| "group_request"` |
| Signal → native | `handleRecvSignal` → `{type:"recvSignal", command, data}` → `_sendToNative` |
| Native IPC | `$zcall.sendDataToNative`, `$zcall.initCall` |
| Flags | `enableCall`, `enable_ipc_call`, `enableVideoCall`, `call.launch_native_in_startup` |
| HTTP domains | `https://voicecall-wpa.<zalo domain>`, `qos.talk.zing.vn/api/qos/uploadcalllog` |
| Chat leftovers | `MSG_CALL` / `recommened.receivecall` / MissCall / Calling (message history, not full media) |
| Native lib | `nativelibs/zcall/zcall_ia32.node` + `vcmac.js` (`incomingCall`, `makeCall`, `setConfigData`) |
| Live artifacts | `%APPDATA%\ZaloData\call.log`, `cal\voip.log` (obfuscated), `cal\*.calf` (locked DB) |

### What zca-js does **not** see

Hermes_Zalo bridge uses zca-js Listener → only chat-class events.  
Call **control** (`act=request`) and **recvSignal** stay inside Zalo PC → native.  
Hence personal auto-answer **cannot** be done only in current bridge.

---

## Research milestones

### B0 — Map (DONE this session)

- [x] Locate zcall native + vcmac API surface  
- [x] Extract asar snippets → `asar_call_snippets.json`, `asar_signal_deep.json`  
- [x] Identify domains + incoming control shape  
- [x] Locate live logs under ZaloData  

### B1 — Capture live incoming call (NEXT)

1. Run `.\monitor-call.ps1` while **acc phụ** receives a call from another phone.  
2. Capture:  
   - process list (ZaloCall start/stop)  
   - `voip.log` / `call.log` deltas  
   - optional: Wireshark filter `host voicecall-wpa.zalo.me or host talk.zing.vn`  
3. Save under `captures/<timestamp>/`.

### B2 — Intercept control path

Options (pick after B1 data):

| Option | Idea | Difficulty |
|--------|------|------------|
| **B2a Electron inject** | DevTools / `--inspect` / asar patch hook `handleControl` + log full payload | Medium |
| **B2b Frida on ZaloCall** | Hook `$zcall.sendDataToNative` / native exports | Hard |
| **B2c Mitm HTTPS** | Intercept `voicecall-wpa` (cert pin may block) | Hard |

Need full JSON of `handleControl` when `act=request` (caller id, callId, sdp/servers, tokens).

### B3 — Answer path

1. Find UI/native command for **accept** (mirror reject counter already seen: `countContinuouslyPressRejectCall`).  
2. Or send native message type for accept via `$zcall.sendDataToNative`.  
3. Confirm media path active (`callRunning=true`).

### B4 — Audio bridge → Hermes

1. Virtual cable / WASAPI loopback from ZaloCall audio device.  
2. Streaming STT → Hermes agent (short turns) → TTS → inject into Zalo call mic device.  
3. Later: native PCM hooks if found in `zcall_*.node`.

### B5 — Stabilize / productize

- Acc phụ only, rate limits, fail-safe hangup.  
- Fallback: if reverse fails → document switch to **OA ZCC SIP** (path A).

---

## Tools in this folder

| File | Role |
|------|------|
| `PHASE_B.md` | This plan |
| `monitor-call.ps1` | Watch ZaloCall + copy log deltas |
| `export-map.mjs` | Re-scan asar for call keywords |
| `asar_*.json` | Static reverse dumps |
| `call_related_urls.txt` | Domains/URLs from asar |
| `captures/` | Live capture sessions (gitignored) |

---

## Hard constraints

1. **Do not** reverse on main banking Zalo.  
2. Expect Zalo PC update to break hooks.  
3. No public open-source complete answer stack (zca-js issues still open).  
4. Hermes bridge alone is **insufficient** for VoIP; Phase B is Zalo-PC-centric.

---

## Immediate operator steps

```powershell
cd C:\Dev\Hermes_Zalo\research\zcall-pc
powershell -NoProfile -ExecutionPolicy Bypass -File .\monitor-call.ps1
# From another phone: call this Zalo (PC logged in, sound on)
# Ctrl+C when call ends → check captures\<id>\
```

After first capture, open an issue/note with redacted `handleControl` payload shape for B2.
