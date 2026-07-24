# Changelog

## Unreleased

- **1.3.0** Pseudo-call `/call` | `/goi`: voice-note session + auto voice_only TTS (native VoIP still N/A)
- Bridge: log inbound_empty_no_media for research
- Docs: VOICE_TASKING pseudo-call guide
- Docs: `docs/VOICE_TASKING.md` — Zalo voice-note → Hermes STT tasking; native VoIP call not supported (zca-js).


## 1.2.0

- CSKH plain-text outbound (`_plain_zalo_text`: strip markdown/HTML/fancy unicode)
- Plugin version bump; Hermes home junctions are SoT (not AgentLab copies)
- Sync runtime adapter from AgentLab into this repo; AgentLab only keeps docs/pointers

## 1.1.0


- Media out: image / video / voice / document via `/send-media`
- Typing, `get_chat_info`, seen receipts
- Allowlist **hot-reload** (`POST /allowlist`) ΓÇö no gateway restart
- Faster poll (0.4s), inbound media meta, anti-hang platform hints
- Install scripts (Windows + bash), full docs
- Public repo packaging as **Hermes_Zalo**

## 1.0.0

- Initial bridge + Hermes plugin (text DM/group, QR pair)

