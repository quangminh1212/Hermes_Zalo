# Zalo ↔ Hermes: giao việc bằng giọng nói

## Có / không có

| Cách | Hỗ trợ | Ghi chú |
|------|--------|---------|
| **Chat text Zalo** → Hermes làm việc | ✅ | Owner full tools; guest = safe + Hakinet |
| **Tin nhắn thoại (voice note)** → STT → Hermes | ✅ | Gateway auto-transcribe (`stt.enabled`) |
| Hermes **trả lời thoại** (TTS voice note) | ✅ | Bật `/voice on` (voice_only) hoặc `/voice tts` |
| **Pseudo-call `/call`** (voice note liên tục, gần realtime) | ✅ v1.3 | STT→agent→TTS ngắn; TTL 30 phút |
| **Cuộc gọi Zalo native** (VoIP/gọi điện trong app) | ❌ | `zca-js` Listener **không** có event call; không API answer/reject |

Native call (nút gọi trong Zalo) **không** đi qua bridge. Không thể “nhấc máy” cuộc gọi Zalo cá nhân bằng stack hiện tại (zca-js 2.1.2 chỉ có `message`, `typing`, `reaction`, … — không VoIP).

## Pseudo-call gần realtime (`/call`) — khuyến nghị khi muốn “gọi”

```
/call  →  bật session + voice_only TTS
Bạn giữ micro gửi voice note liên tục
  → bridge → STT vi → agent (prompt ngắn) → TTS voice note
/call off  hoặc nói "cúp máy"
```

1. DM Hermes trên Zalo (owner).
2. Gõ **`/call`** (hoặc `/goi`, “gọi hermes”).
3. Bot xác nhận: native VoIP không được; dùng voice note.
4. Gửi tin nhắn thoại ngắn rõ → chờ reply thoại/text ngắn → lặp.
5. **`/call off`** hoặc nói “cúp máy” / “tạm biệt”.

TTL session: 30 phút không hoạt động thì tự hết.

## Luồng text / voice note đơn (không cần /call)

```
Bạn (Zalo)  --voice note hoặc text-->  bridge :3001  -->  Hermes gateway
                                              STT (vi) -->  Agent + tools
                                              TTS (tuỳ mode) -->  voice note / text reply
```

1. Gateway + bridge `connected`.
2. Owner DM bot.
3. Tuỳ chọn: `/voice on` (nếu chưa bật).
4. Gửi text hoặc voice note giao việc.

## Cấu hình Hermes (live home)

```yaml
stt:
  enabled: true
  local:
    model: small          # base yếu tiếng Việt
    language: vi
platform_toolsets:
  zalo:                   # parity tool owner (file/terminal/skills/…)
    - browser
    - terminal
    - file
    - skills
    # … full list like whatsapp/cli
platforms:
  zalo:
    extra:
      machine_admin_from: ["<owner_uid>"]
      guest_toolsets: ["safe"]
      user_allowed_commands: [help, whoami, status, pairzalo, pair, voice]
```

Voice mode file: `%LOCALAPPDATA%\hermes\gateway_voice_mode.json`

```json
{
  "zalo:<owner_uid>": "voice_only"
}
```

Restart gateway sau khi sửa file này (hoặc dùng `/voice on` trong chat để ghi live).

## JarvisLab (gọi “ngoài đời” trên máy)

MCP mic/loa **trên PC** — không phải cuộc gọi Zalo:

```
mcp__jarvislab__voice_speak / voice_listen / voice_wait_for_speech
python C:\Dev\JarvisLab\jarvis_call.py
```

Dùng khi bạn **ngồi tại máy** Hermes. Remote phone → dùng voice note Zalo ở trên.

## Kiểm tra nhanh

```powershell
# bridge
Invoke-RestMethod http://127.0.0.1:3001/health

# STT local (Hermes venv)
$py = "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe"
$env:HERMES_HOME = "$env:LOCALAPPDATA\hermes"
$env:PYTHONPATH = "$env:LOCALAPPDATA\hermes\hermes-agent"
& $py -c "from tools.transcription_tools import transcribe_audio; print(transcribe_audio(file_path=r'C:\path\to\voice.m4a'))"
```

## Rủi ro

- Unofficial personal client — dùng acc phụ.
- Voice note lớn / mạng chậm → STT timeout; nói ngắn rõ.
- Guest không được full tools — chỉ CSKH / safe.
