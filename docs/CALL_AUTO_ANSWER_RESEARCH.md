# Research: tự bắt máy + trả lời cuộc gọi Zalo

**Ngày:** 2026-07-24  
**Kết luận ngắn:**  
- **Tài khoản cá nhân (Hermes_Zalo / zca-js):** **chưa có** API public để bắt máy VoIP.  
- **Đường chính thức khả thi:** **Zalo OA + Gọi thoại ZCC (SIP trunk)** → FreeSWITCH/Asterisk → STT/TTS → Hermes.  
- **Đường reverse (PC):** Zalo Desktop có stack `zcall` native riêng — reverse được về lý thuyết, **chưa ship được** trong sprint hiện tại (binary + signaling riêng, rủi ro ban cao).

---

## 1. Đã rà soát kỹ

### 1.1 zca-js 2.1.2 (bridge Hermes hiện tại)

| Hạng mục | Kết quả |
|----------|---------|
| Listener events | `message`, `typing`, `reaction`, `friend_event`, `group_event`, … — **không** `call` |
| API surface | `sendVoice` (voice **note**), không `answerCall` / `rejectCall` |
| Friend settings | `BLOCK_CALL` / `UNBLOCK_CALL`, `accept_stranger_call` = preference, **không** media |
| GitHub issues | [#184](https://github.com/RFS-ADRENO/zca-js/issues/184), [#366](https://github.com/RFS-ADRENO/zca-js/issues/366) vẫn **Open** — community cũng xin “gọi điện”, chưa merge |
| Issue #366 | Nhắc “sản phẩm rework có gọi điện” (đóng, không open-source protocol) |

### 1.2 Bridge Hermes_Zalo

- Chỉ HTTP poll tin nhắn / send media.  
- Đã log `inbound_empty_no_media` để soi gói lạ (call signaling **không** đi kênh message chuẩn).

### 1.3 Zalo PC (máy user) — manh mối reverse

Máy có cài Zalo Desktop + process `ZaloCall.exe`.  
Native stack (không phải zca-js):

```
%LOCALAPPDATA%\Programs\Zalo\Zalo-*\resources\app.asar.unpacked\native\nativelibs\zcall\
  binding.js → zcall_*.node
  vcmac.js   → incomingCall(), setConfigData(), mute, RTP/RTCP, ZRTP
```

`vcmac.js` lộ endpoint / khái niệm:

- `https://vlogin.zaloapp.com/login`
- `http://api.conf.talk.zing.vn/genuid`
- `http://api.conf.talk.zing.vn/zls?action=call_config`
- Config: `fromId`, `toId`, `callId`, `sessId`, `protocol`, `servers` (rtp/rtcp), `zrtc_config`, `changeZRTP`

→ Cuộc gọi personal dùng **stack “talk.zing.vn / zcall” riêng**, auth session Zalo PC, native codec.  
**Không** tái sử dụng session zca-js Web một cách documented.

Muốn auto-answer personal theo hướng reverse cần:

1. Bắt **signaling** cuộc gọi tới (WS/HTTP từ client Zalo PC hoặc reverse protocol).  
2. Lấy `call_config` + token hợp lệ.  
3. Gọi native `incomingCall` / answer path trong `zcall_*.node` **hoặc** reimplement media (RTP/ZRTP).  
4. Pipe audio ↔ Hermes STT/TTS realtime.

**Ước lượng:** nhiều tuần–tháng reverse + dễ ban + vỡ mỗi bản Zalo PC. **Không phải fix config.**

### 1.4 Official Zalo OA — **đường production**

[Gọi thoại OA](https://oa.zalo.me/home/function/interaction?type=goi-thoai):

| Chế độ | Ý nghĩa |
|--------|---------|
| **MCC** | Mini call center trên OA Manager (UI) |
| **ZCC (Zalo Cloud Connect)** | **SIP trunk** nối tổng đài doanh nghiệp; **inbound miễn phí** (theo docs OA) |

Docs dev: [developers.zalo.me — Gọi thoại](https://developers.zalo.me/docs/official-account/goi-thoai/tong-quan)

Yêu cầu: OA **đã xác thực** + gói dịch vụ OA phù hợp.

**Luồng auto-answer AI (khả thi end-to-end):**

```
User Zalo  --gọi OA-->  Zalo ZCC SIP
                              |
                         FreeSWITCH / Asterisk / LiveKit SIP
                              |
                    STT realtime → Hermes agent → TTS realtime
                              |
                         audio stream back to user
```

Đây là **cách duy nhất documented** để “tự bắt máy + trả lời bằng giọng” trong hệ sinh thái Zalo.

---

## 2. Ma trận quyết định

| Mục tiêu user | Cách | Tự bắt máy? | Reply giọng realtime? | Effort | Rủi ro |
|---------------|------|-------------|------------------------|--------|--------|
| Gọi **nick cá nhân** Hermes (app) | zca-js / bridge | ❌ | ❌ | — | — |
| Gọi nick cá nhân, voice note `/call` | Đã ship 1.3 | N/A | Turn-based TTS | Done | Thấp (unofficial chat) |
| Gọi **OA** Hermes, bot nhấc máy | **ZCC + SIP + Hermes** | ✅ | ✅ | 1–3 tuần | Thấp (official) |
| Gọi nick cá nhân, reverse zcall | Reverse PC stack | ? | ? | Tháng+ | **Rất cao (ban)** |
| Gọi số điện thoại thường | Twilio/SIP → Hermes | ✅ | ✅ | 1–2 tuần | Thấp |

---

## 3. Roadmap đề xuất (nếu làm tiếp)

### Phase A — Official (khuyến nghị)

1. Tạo / xác thực **Zalo OA** + gói có Gọi thoại.  
2. Bật **ZCC**, lấy SIP credentials.  
3. Cài FreeSWITCH (hoặc LiveKit SIP) nhận inbound.  
4. Module `hermes-zalo-sip` (repo mới hoặc `Hermes_Zalo/sip/`):  
   - answer → stream PCM  
   - STT streaming (faster-whisper / cloud)  
   - Hermes turn (short system prompt voice)  
   - TTS streaming → playback  
5. Test: user Zalo gọi OA → bot nhấc → hội thoại.

### Phase B — Personal reverse (R&D, không hứa ship)

1. Instrument Zalo PC: log call signaling khi có cuộc gọi tới.  
2. Map payload `call_config` / `incomingCall`.  
3. Prototype answer bằng inject vào process hoặc drive `zcall` (legal/ToS risk).  
4. Chỉ khi protocol ổn định mới nối Hermes.

### Phase C — Hybrid UX (đã có một phần)

- User gọi personal → **không nhấc** → auto text/voice note:  
  *“Mình không bắt máy Zalo call. Gửi /call hoặc tin nhắn thoại.”*  
- (Cần detect cuộc gọi — personal **chưa detect được** qua bridge; chỉ làm được nếu reverse/UI automation.)

---

## 4. Việc **không** nên hứa

- “Bật flag là Hermes bắt máy nick cá nhân” — **sai**.  
- Patch zca-js thêm 50 dòng là xong call — **sai**.  
- Dùng voice note thay VoIP full-duplex zero-latency — **không tương đương**.

---

## 5. Tài liệu liên quan

- `docs/VOICE_TASKING.md` — voice note + `/call` pseudo  
- zca-js issues #184, #366  
- OA Gọi thoại / ZCC docs (developers.zalo.me)

---

## 6. Next action (chờ chọn)

1. **A — Làm ZCC SIP + Hermes voice agent** (official, bắt máy thật trên OA).  
2. **B — R&D reverse Zalo PC zcall** (personal, rủi ro, dài).  
3. **C — Giữ personal chat + `/call`**, không làm VoIP.

Không chọn = giữ hiện trạng: chat + voice note + pseudo `/call`.
