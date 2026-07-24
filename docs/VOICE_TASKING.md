# Zalo ↔ Hermes: giao việc bằng giọng nói

## Có / không có

| Cách | Hỗ trợ | Ghi chú |
|------|--------|---------|
| **Chat text Zalo** → Hermes làm việc | ✅ | Owner full tools; guest = safe + Hakinet |
| **Tin nhắn thoại (voice note)** → STT → Hermes | ✅ | Gateway auto-transcribe (`stt.enabled`) |
| Hermes **trả lời thoại** (TTS voice note) | ✅ | Bật `/voice on` (voice_only) hoặc `/voice tts` |
| **Cuộc gọi Zalo native** (VoIP/gọi điện trong app) | ❌ | `zca-js` **không** có API nghe/trả lời call |

Native call (nút gọi trong Zalo) **không** đi qua bridge. Không có path hợp pháp/ổn định để Hermes “nhấc máy” cuộc gọi Zalo cá nhân.

## Luồng khuyến nghị (giao việc từ điện thoại)

```
Bạn (Zalo)  --voice note hoặc text-->  bridge :3001  -->  Hermes gateway
                                              STT (vi) -->  Agent + tools
                                              TTS (tuỳ mode) -->  voice note / text reply
```

1. Đảm bảo gateway + bridge đang `connected` (`GET http://127.0.0.1:3001/health`).
2. **Owner** (UID máy admin): chat DM bot Hermes trên Zalo.
3. Lần đầu bật trả lời thoại (nếu chưa pre-seed):
   - gõ `/voice on` → chỉ reply voice khi bạn gửi thoại  
   - hoặc `/voice tts` → mọi reply đều có voice  
   - `/voice off` → chỉ text  
   - `/voice status`
4. Gửi **tin nhắn thoại** hoặc text: “Tóm tắt file X”, “Chạy test …”, “Nhắc tôi …”.
5. Hermes STT (local faster-whisper, `stt.local.language: vi`) → làm việc → reply text (+ voice nếu mode bật).

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
