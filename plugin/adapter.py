"""
Hermes_Zalo — Zalo personal-account platform adapter for Hermes Agent.
https://github.com/quangminh1212/Hermes_Zalo

OpenClaw zalouser pattern: Node bridge (zca-js) + HTTP poll/send.
Unofficial — risk of ban. Prefer a secondary Zalo account.

Features (parity with WA/Telegram where Zalo allows):
  - text send (chunked)
  - media out: image / video / voice / document (MEDIA: tags)
  - typing indicator
  - get_chat_info
  - inbound media meta + download when URL present
  - allowlist hot-reload via bridge POST /allowlist (NO gateway restart)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform as py_platform
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _plain_zalo_text(text: str) -> str:
    """Zalo CSKH: plain chat only — no bold/italic/font/markdown."""
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    # zero-width / fancy spaces that look like "font tricks"
    for ch in (
        "\u200b", "\u200c", "\u200d", "\ufeff", "\u2060",
        "\u00a0",  # nbsp → normal space later
    ):
        s = s.replace(ch, " " if ch == "\u00a0" else "")
    # HTML-ish
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    # code fences / inline
    s = re.sub(r"```[\w-]*\n?", "", s)
    s = s.replace("```", "")
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # markdown links
    s = re.sub(r"\[([^\]\n]+)\]\(([^)]+)\)", r"\1 \2", s)
    # bold/italic/strike (common markdown)
    s = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    s = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"\1", s)
    s = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"\1", s)
    # headings / quotes
    s = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}>[ \t]?", "", s)
    # bullets → plain dash line (no special bullet font)
    s = re.sub(r"(?m)^[ \t]*[\*\+\-·•▪◦●○][ \t]+", "- ", s)
    # park URLs then strip leftover markdown markers
    urls: list[str] = []

    def _park(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"§URL{len(urls) - 1}§"

    s = re.sub(r"https?://[^\s<>\]]+", _park, s)
    for ch in ("*", "#", "`", "•", "▪", "◦", "●", "○"):
        s = s.replace(ch, "")
    # mathematical / fullwidth / bold-unicode letters → best-effort strip to ASCII letters if mapped
    # (Zalo sometimes gets fancy unicode "bold" from models)
    try:
        import unicodedata

        def _demath(c: str) -> str:
            # unwrap enclosed/math alphanumerics via NFKC when possible
            return unicodedata.normalize("NFKC", c)

        s = "".join(_demath(c) for c in s)
    except Exception:
        pass
    for i, u in enumerate(urls):
        s = s.replace(f"§URL{i}§", u)
    # collapse whitespace
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()



# CSKH Zalo: short bubbles (normal chat feel)
_ZALO_SOFT_CHARS = 260
_ZALO_SOFT_LINES = 5
_ZALO_HARD_CHARS = 900
_ZALO_CHUNK_DELAY_S = 0.55


def _split_zalo_cskh(text: str, soft_chars: int = _ZALO_SOFT_CHARS, soft_lines: int = _ZALO_SOFT_LINES) -> list[str]:
    """Split long CSKH replies into short plain bubbles."""
    s = (text or "").strip()
    if not s:
        return []
    if len(s) <= soft_chars and s.count("\n") + 1 <= soft_lines:
        return [s]

    # Prefer blank-line paragraphs first
    paras = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    if len(paras) == 1:
        # single block: split by lines then sentences
        lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
        if len(lines) > 1:
            paras = lines
        else:
            paras = re.split(r"(?<=[.!?…。！？])\s+", s)
            paras = [x.strip() for x in paras if x.strip()] or [s]

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    buf_lines = 0

    def flush():
        nonlocal buf, buf_len, buf_lines
        if buf:
            chunks.append("\n".join(buf).strip())
            buf, buf_len, buf_lines = [], 0, 0

    for para in paras:
        # hard-wrap oversized paragraph
        pieces = [para]
        if len(para) > soft_chars:
            pieces = []
            # sentence-ish then width
            sents = re.split(r"(?<=[.!?…。！？;；])\s+", para)
            sents = [x.strip() for x in sents if x.strip()] or [para]
            for sent in sents:
                if len(sent) <= soft_chars:
                    pieces.append(sent)
                else:
                    # wrap by words/chars
                    start_i = 0
                    while start_i < len(sent):
                        pieces.append(sent[start_i : start_i + soft_chars].strip())
                        start_i += soft_chars
        for piece in pieces:
            add_lines = piece.count("\n") + 1
            add_len = len(piece) + (1 if buf else 0)
            if buf and (buf_len + add_len > soft_chars or buf_lines + add_lines > soft_lines):
                flush()
            buf.append(piece)
            buf_len += add_len
            buf_lines += add_lines
            # if still oversized alone, flush immediately
            if buf_len >= soft_chars or buf_lines >= soft_lines:
                flush()
    flush()

    # safety hard cap
    final: list[str] = []
    for c in chunks:
        if len(c) <= _ZALO_HARD_CHARS:
            final.append(c)
        else:
            for i in range(0, len(c), _ZALO_HARD_CHARS):
                part = c[i : i + _ZALO_HARD_CHARS].strip()
                if part:
                    final.append(part)
    return final or [s[:_ZALO_HARD_CHARS]]



_IS_WINDOWS = py_platform.system() == "Windows"

from gateway.config import Platform
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    cache_audio_from_url,
    cache_document_from_bytes,
    cache_image_from_url,
    get_document_cache_dir,
    get_image_cache_dir,
)

try:
    from gateway.platforms.base import cache_video_from_url  # type: ignore
except Exception:  # pragma: no cover
    cache_video_from_url = None  # type: ignore


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _bridge_dir() -> Path:
    return _hermes_home() / "scripts" / "zalo-bridge"


def _session_dir() -> Path:
    return _hermes_home() / "zalo" / "session"


def _find_node() -> str:
    try:
        from hermes_constants import find_node_executable

        return find_node_executable("node") or "node"
    except Exception:
        return "node"


def _popen_kwargs() -> dict:
    try:
        from hermes_cli._subprocess_compat import windows_detach_popen_kwargs

        return windows_detach_popen_kwargs()
    except Exception:
        if _IS_WINDOWS:
            return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        return {}


def _strip_group_prefix(chat_id: str) -> tuple[str, bool]:
    cid = str(chat_id or "")
    if cid.startswith("group:"):
        return cid[6:], True
    return cid, False


class ZaloAdapter(BasePlatformAdapter):
    """Polls local zca-js bridge and relays DMs/groups to Hermes."""

    def __init__(self, config, **kwargs):
        super().__init__(config=config, platform=Platform("zalo"))
        extra = getattr(config, "extra", {}) or {}
        try:
            self._bridge_port = int(
                os.getenv("ZALO_BRIDGE_PORT") or extra.get("bridge_port") or 3001
            )
        except (TypeError, ValueError):
            self._bridge_port = 3001
        self._bridge_process: Optional[subprocess.Popen] = None
        self._http_session = None
        self._poll_task: Optional[asyncio.Task] = None
        self._bridge_log = _session_dir().parent / "bridge.log"
        # Faster poll = snappier replies; still light on CPU
        try:
            self._poll_interval = float(os.getenv("ZALO_POLL_INTERVAL") or "0.4")
        except (TypeError, ValueError):
            self._poll_interval = 0.4

    @property
    def name(self) -> str:
        return "Zalo"

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        import aiohttp

        _session_dir().mkdir(parents=True, exist_ok=True)

        if await self._health_ok():
            print(f"[{self.name}] Bridge already up on :{self._bridge_port}")
        else:
            if not await self._start_bridge():
                return False

        ok = False
        data: dict = {}
        for _ in range(40):
            await asyncio.sleep(1)
            try:
                if self._http_session is None:
                    self._http_session = aiohttp.ClientSession()
                async with self._http_session.get(
                    f"http://127.0.0.1:{self._bridge_port}/health",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        st = data.get("status")
                        if st == "connected":
                            ok = True
                            break
                        if st == "pairing":
                            qr_path = _session_dir() / "qr.png"
                            print(
                                f"[{self.name}] Waiting for QR scan… "
                                f"open {qr_path} or http://127.0.0.1:{self._bridge_port}/qr.png"
                            )
            except Exception:
                pass

        if not ok:
            err = data.get("error") or "bridge not connected (scan QR?)"
            print(f"[{self.name}] ✗ {err}")
            self._set_fatal_error("zalo_not_connected", str(err), retryable=True)
            return False

        self._running = True
        self._mark_connected()
        self._poll_task = asyncio.create_task(self._poll_messages())
        print(
            f"[{self.name}] ✓ connected as "
            f"{data.get('displayName') or data.get('ownId') or '?'}"
        )
        return True

    async def disconnect(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        print(f"[{self.name}] Disconnected (bridge left running)")
        self._mark_disconnected()

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        import aiohttp

        if not self._http_session:
            self._http_session = aiohttp.ClientSession()
        meta = metadata or {}
        target, is_group_pref = _strip_group_prefix(chat_id)
        is_group = bool(meta.get("is_group") or is_group_pref)
        try:
            # Always send Unicode text as str — aiohttp json= uses ensure_ascii
            # escape which Zalo accepts; never re-encode via Windows console.
            if not isinstance(content, str):
                content = str(content or "")
            content = _plain_zalo_text(content)
            # CSKH: long replies → several short Zalo bubbles
            no_split = bool(meta.get("no_split") or meta.get("zalo_no_split"))
            parts = [content] if no_split else _split_zalo_cskh(content)
            if not parts:
                return SendResult(success=True, message_id=None)

            last_id = None
            quote = meta.get("zalo_quote") or meta.get("quote")
            for idx, part in enumerate(parts):
                payload: Dict[str, Any] = {
                    "chatId": target,
                    "message": part,
                    "isGroup": is_group,
                }
                # Only first bubble may carry a full quote object.
                if (
                    idx == 0
                    and isinstance(quote, dict)
                    and quote.get("msgId")
                    and quote.get("uidFrom")
                ):
                    payload["replyTo"] = quote
                async with self._http_session.post(
                    f"http://127.0.0.1:{self._bridge_port}/send",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if not (resp.status == 200 and data.get("success")):
                        err = data.get("error") or f"HTTP {resp.status}"
                        if last_id:
                            return SendResult(
                                success=False,
                                error=f"partial send after {idx}/{len(parts)}: {err}",
                                message_id=last_id,
                            )
                        return SendResult(success=False, error=err)
                    last_id = data.get("messageId") or last_id
                if idx < len(parts) - 1 and _ZALO_CHUNK_DELAY_S > 0:
                    await asyncio.sleep(_ZALO_CHUNK_DELAY_S)
            return SendResult(success=True, message_id=last_id)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def _send_media_to_bridge(
        self,
        chat_id: str,
        *,
        file_path: Optional[str] = None,
        file_url: Optional[str] = None,
        media_type: str = "document",
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        import aiohttp

        if not self._http_session:
            self._http_session = aiohttp.ClientSession()
        meta = metadata or {}
        target, is_group_pref = _strip_group_prefix(chat_id)
        is_group = bool(meta.get("is_group") or is_group_pref)
        if file_path and not os.path.exists(file_path):
            return SendResult(success=False, error=f"File not found: {file_path}")
        payload: Dict[str, Any] = {
            "chatId": target,
            "mediaType": media_type,
            "isGroup": is_group,
        }
        if file_path:
            payload["filePath"] = os.path.abspath(file_path)
        if file_url:
            payload["fileUrl"] = file_url
        if caption:
            payload["caption"] = _plain_zalo_text(str(caption))
        if file_name:
            payload["fileName"] = file_name
        try:
            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/send-media",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and data.get("success"):
                    return SendResult(success=True, message_id=data.get("messageId"))
                return SendResult(
                    success=False, error=data.get("error") or f"HTTP {resp.status}"
                )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        try:
            # Prefer local cache then native attach
            if image_url.startswith(("http://", "https://")):
                local = await cache_image_from_url(image_url)
                return await self._send_media_to_bridge(
                    chat_id, file_path=local, media_type="image", caption=caption, metadata=metadata
                )
            if os.path.isabs(image_url) and os.path.exists(image_url):
                return await self._send_media_to_bridge(
                    chat_id, file_path=image_url, media_type="image", caption=caption, metadata=metadata
                )
            return await self._send_media_to_bridge(
                chat_id, file_url=image_url, media_type="image", caption=caption, metadata=metadata
            )
        except Exception as e:
            logger.warning("[%s] send_image native failed: %s", self.name, e)
            return await super().send_image(chat_id, image_url, caption, reply_to, metadata)

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return await self._send_media_to_bridge(
            chat_id,
            file_path=image_path,
            media_type="image",
            caption=caption,
            metadata=kwargs.get("metadata"),
        )

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return await self._send_media_to_bridge(
            chat_id,
            file_path=video_path,
            media_type="video",
            caption=caption,
            metadata=kwargs.get("metadata"),
        )

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return await self._send_media_to_bridge(
            chat_id,
            file_path=audio_path,
            media_type="voice",
            caption=caption,
            metadata=kwargs.get("metadata"),
        )

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return await self._send_media_to_bridge(
            chat_id,
            file_path=file_path,
            media_type="document",
            caption=caption,
            file_name=file_name or os.path.basename(file_path),
            metadata=kwargs.get("metadata"),
        )

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        if not self._http_session:
            return
        meta = metadata or {}
        target, is_group_pref = _strip_group_prefix(chat_id)
        is_group = bool(meta.get("is_group") or is_group_pref)
        try:
            import aiohttp

            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/typing",
                json={"chatId": target, "isGroup": is_group},
                timeout=aiohttp.ClientTimeout(total=5),
            ):
                pass
        except Exception:
            pass

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        cid = str(chat_id or "")
        target, is_group = _strip_group_prefix(cid)
        if not self._http_session:
            return {"name": target or cid or "Unknown", "type": "group" if is_group else "dm"}
        try:
            import aiohttp

            q = "1" if is_group else "0"
            async with self._http_session.get(
                f"http://127.0.0.1:{self._bridge_port}/chat/{target}?isGroup={q}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return {
                        "name": data.get("name") or target,
                        "type": data.get("type") or ("group" if is_group else "dm"),
                        "participants": data.get("participants") or [],
                        "avatar": data.get("avatar"),
                    }
        except Exception as e:
            logger.debug("[%s] get_chat_info failed: %s", self.name, e)
        return {"name": target or cid or "Unknown", "type": "group" if is_group else "dm"}

    # ── internal ──────────────────────────────────────────────────────

    async def _health_ok(self) -> bool:
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=2)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(f"http://127.0.0.1:{self._bridge_port}/health") as r:
                    if r.status != 200:
                        return False
                    j = await r.json()
                    return j.get("status") in {"connected", "pairing", "disconnected"}
        except Exception:
            return False

    async def _start_bridge(self) -> bool:
        bridge_js = _bridge_dir() / "bridge.js"
        if not bridge_js.is_file():
            self._set_fatal_error(
                "bridge_missing",
                f"Zalo bridge not found at {bridge_js}",
                retryable=False,
            )
            return False

        env = os.environ.copy()
        env["HERMES_HOME"] = str(_hermes_home())
        env["ZALO_SESSION_DIR"] = str(_session_dir())
        env.setdefault("ZALO_ALLOWED_USERS", os.getenv("ZALO_ALLOWED_USERS", "*"))
        env.setdefault("ZALO_ALLOW_ALL_USERS", os.getenv("ZALO_ALLOW_ALL_USERS", "true"))
        env.setdefault(
            "ZALO_FORWARD_SELF_MESSAGES",
            os.getenv("ZALO_FORWARD_SELF_MESSAGES", "true"),
        )
        env.setdefault("ZALO_SEND_SEEN", os.getenv("ZALO_SEND_SEEN", "true"))

        self._bridge_log.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(self._bridge_log, "a", encoding="utf-8")
        try:
            self._bridge_process = subprocess.Popen(
                [
                    _find_node(),
                    str(bridge_js),
                    "--port",
                    str(self._bridge_port),
                    "--session",
                    str(_session_dir()),
                ],
                cwd=str(_bridge_dir()),
                stdout=log_fh,
                stderr=log_fh,
                env=env,
                **_popen_kwargs(),
            )
        except Exception as e:
            log_fh.close()
            self._set_fatal_error("bridge_spawn_failed", str(e), retryable=True)
            print(f"[{self.name}] Failed to start bridge: {e}")
            return False

        for _ in range(20):
            await asyncio.sleep(0.5)
            if await self._health_ok():
                return True
            if self._bridge_process.poll() is not None:
                self._set_fatal_error(
                    "bridge_died",
                    f"bridge exit {self._bridge_process.returncode}; see {self._bridge_log}",
                    retryable=True,
                )
                return False
        return await self._health_ok()

    async def _poll_messages(self) -> None:
        import aiohttp

        while self._running:
            if not self._http_session:
                break
            try:
                async with self._http_session.get(
                    f"http://127.0.0.1:{self._bridge_port}/messages",
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        messages = await resp.json()
                        for msg in messages or []:
                            event = await self._build_event(msg)
                            if event:
                                await self.handle_message(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{self.name}] Poll error: {e}")
                await asyncio.sleep(5)
            await asyncio.sleep(self._poll_interval)

    async def _build_event(self, data: Dict[str, Any]) -> Optional[MessageEvent]:
        try:
            body = (data.get("body") or "").strip()
            media_url = data.get("mediaUrl") or data.get("media_url")
            media_type = (data.get("mediaType") or data.get("media_type") or "").lower()
            media_name = data.get("mediaFileName") or data.get("media_file_name") or ""

            if not body and not media_url:
                return None

            chat_id = str(data.get("chatId") or "")
            sender_id = str(data.get("senderId") or chat_id)
            is_group = bool(data.get("isGroup"))
            source = self.build_source(
                chat_id=chat_id,
                chat_name=str(data.get("chatName") or chat_id),
                chat_type="group" if is_group else "dm",
                user_id=sender_id,
                user_name=str(data.get("senderName") or sender_id),
            )
            ts = data.get("timestamp")
            try:
                if isinstance(ts, (int, float)):
                    if ts < 10_000_000_000:
                        ts = ts * 1000
                    timestamp = datetime.fromtimestamp(ts / 1000.0)
                else:
                    timestamp = datetime.now()
            except Exception:
                timestamp = datetime.now()

            msg_type = MessageType.TEXT
            media_urls: List[str] = []
            media_types: List[str] = []

            if media_url:
                url = str(media_url)
                try:
                    if media_type in {"image", "photo"} or any(
                        url.lower().split("?")[0].endswith(ext)
                        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")
                    ):
                        msg_type = MessageType.PHOTO
                        if url.startswith(("http://", "https://")):
                            local = await cache_image_from_url(url)
                            media_urls.append(local)
                            media_types.append("image/jpeg")
                        else:
                            media_urls.append(url)
                            media_types.append("image/jpeg")
                        if not body or body.startswith("["):
                            body = body if body and not body.startswith("[") else ""
                    elif media_type in {"video"}:
                        msg_type = MessageType.VIDEO
                        media_urls.append(url)
                        media_types.append("video/mp4")
                    elif media_type in {"audio", "voice"}:
                        msg_type = MessageType.VOICE if media_type == "voice" else MessageType.AUDIO
                        if url.startswith(("http://", "https://")):
                            try:
                                local = await cache_audio_from_url(url)
                                media_urls.append(local)
                            except Exception:
                                media_urls.append(url)
                        else:
                            media_urls.append(url)
                        media_types.append("audio/mpeg")
                    else:
                        msg_type = MessageType.DOCUMENT
                        if url.startswith(("http://", "https://")):
                            try:
                                import aiohttp

                                async with aiohttp.ClientSession() as s:
                                    async with s.get(
                                        url, timeout=aiohttp.ClientTimeout(total=60)
                                    ) as r:
                                        raw = await r.read()
                                fname = media_name or Path(url.split("?")[0]).name or "file.bin"
                                local = cache_document_from_bytes(raw, fname)
                                media_urls.append(local)
                            except Exception:
                                media_urls.append(url)
                        else:
                            media_urls.append(url)
                        media_types.append("application/octet-stream")
                except Exception as e:
                    logger.warning("[%s] inbound media cache failed: %s", self.name, e)
                    if not body:
                        body = f"[media: {media_type or 'file'}] {url}"

            quote = data.get("quote") or {}
            reply_to_id = None
            reply_to_text = None
            if isinstance(quote, dict):
                reply_to_id = str(quote.get("msgId") or "") or None
                reply_to_text = str(quote.get("body") or "") or None

            return MessageEvent(
                text=body or "",
                message_type=msg_type,
                source=source,
                raw_message=data,
                message_id=str(data.get("messageId") or ""),
                timestamp=timestamp,
                media_urls=list(media_urls or []),
                media_types=list(media_types or []),
                reply_to_message_id=reply_to_id,
                reply_to_text=reply_to_text,
                metadata={
                    "zalo_from_me": bool(data.get("fromMe")),
                    "is_group": is_group,
                    "zalo_msg_type": data.get("msgType"),
                },
            )
        except Exception as e:
            print(f"[{self.name}] build event error: {e}")
            return None


# ── plugin hooks ─────────────────────────────────────────────────────


def check_requirements() -> bool:
    return os.getenv("ZALO_ENABLED", "").lower() in {"1", "true", "yes"}


def validate_config(config) -> bool:
    return check_requirements() or bool((getattr(config, "extra", {}) or {}).get("enabled"))


def _is_connected() -> bool:
    return True


def _env_enablement():
    if os.getenv("ZALO_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return None
    home = os.getenv("ZALO_HOME_CHANNEL") or ""
    extra = {
        "bridge_port": os.getenv("ZALO_BRIDGE_PORT", "3001"),
        "allowed_users": os.getenv("ZALO_ALLOWED_USERS", "*"),
    }
    result = {"extra": extra}
    if home:
        result["home_channel"] = {
            "id": home,
            "name": os.getenv("ZALO_HOME_CHANNEL_NAME") or "Zalo",
            "type": "dm",
        }
    return result


def interactive_setup() -> None:
    from hermes_cli.setup import (
        get_env_value,
        print_header,
        print_info,
        print_success,
        print_warning,
        prompt,
        prompt_yes_no,
        save_env_value,
    )

    print_header("Zalo (personal / unofficial)")
    print_warning("Unofficial zca-js — may ban account. Use a SECONDARY Zalo.")
    if not prompt_yes_no("Enable Zalo personal bridge?", True):
        save_env_value("ZALO_ENABLED", "false")
        return
    save_env_value("ZALO_ENABLED", "true")
    port = prompt("Bridge port", get_env_value("ZALO_BRIDGE_PORT") or "3001")
    save_env_value("ZALO_BRIDGE_PORT", port or "3001")
    allow = prompt("Allowed users (* = all)", get_env_value("ZALO_ALLOWED_USERS") or "*")
    save_env_value("ZALO_ALLOWED_USERS", allow or "*")
    save_env_value("ZALO_ALLOW_ALL_USERS", "true" if (allow or "*").strip() == "*" else "false")
    save_env_value("ZALO_FORWARD_SELF_MESSAGES", "true")
    print_info(
        "Allowlist changes: curl -X POST http://127.0.0.1:3001/allowlist "
        '-H "Content-Type: application/json" -d "{\\"users\\":\\"UID\\"}"  (NO restart)'
    )
    print_info("After gateway start: scan QR at %LOCALAPPDATA%\\hermes\\zalo\\session\\qr.png")
    print_success("Zalo enabled — restart gateway, then scan QR.")


async def _standalone_send(chat_id: str, message: str, **kwargs) -> dict:
    import aiohttp

    port = int(os.getenv("ZALO_BRIDGE_PORT") or 3001)
    media = kwargs.get("media") or []
    try:
        async with aiohttp.ClientSession() as s:
            caption_left = message or ""
            for idx, item in enumerate(media):
                fpath = item[0] if isinstance(item, (list, tuple)) else item
                is_voice = bool(
                    isinstance(item, (list, tuple)) and len(item) > 1 and item[1]
                )
                mtype = "voice" if is_voice else "document"
                ext = Path(str(fpath)).suffix.lower()
                if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    mtype = "image"
                elif ext in {".mp4", ".mov", ".webm"}:
                    mtype = "video"
                elif ext in {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"}:
                    mtype = "voice" if is_voice else "audio"
                # put caption on last media item only
                cap = caption_left if idx == len(media) - 1 else ""
                async with s.post(
                    f"http://127.0.0.1:{port}/send-media",
                    json={
                        "chatId": chat_id,
                        "filePath": str(fpath),
                        "mediaType": mtype,
                        "caption": cap,
                        "isGroup": False,
                    },
                    timeout=aiohttp.ClientTimeout(total=180),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status != 200 or not data.get("success"):
                        return {"error": data.get("error") or f"HTTP {resp.status}"}
                if idx == len(media) - 1:
                    caption_left = ""
            if caption_left:
                async with s.post(
                    f"http://127.0.0.1:{port}/send",
                    json={"chatId": chat_id, "message": caption_left, "isGroup": False},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200 and data.get("success"):
                        return {"success": True, "message_id": data.get("messageId")}
                    return {"error": data.get("error") or f"HTTP {resp.status}"}
            return {"success": True}
    except Exception as e:
        return {"error": str(e)}


_PAIR_CMDS = frozenset({"pairzalo", "pair", "pair_zalo"})

# Commands that historically hung Zalo sessions for 5–30 min (approval + idle).
# Instant-block — never wait for approve/timeout.
_HANG_CMD_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        # gateway / bridge lifecycle (any rename of known scripts)
        r"headless_full",
        r"force_restart_gw",
        r"gw_relaunch",
        r"restart_zalo_(only|bridge)",
        r"Hermes_Gateway\.(vbs|cmd|bat|ps1)",
        r"hermes(\.exe)?\s+gateway\s+(run|stop|restart|install|start)",
        r"pythonw(\.exe)?\s+-m\s+hermes_cli\.main\s+gateway",
        r"python(\.exe)?\s+-m\s+hermes_cli\.main\s+gateway",
        r"(taskkill|Stop-Process|kill).{0,120}(bridge\.js|hermes_cli|pythonw|gateway)",
        r"(rm|del|Remove-Item).{0,60}bridge\.js",
        r"schtasks.{0,80}(Hermes|HkGwRel|Gateway)",
        r"Register-ScheduledTask.{0,80}(Hermes|HkGwRel|Gateway)",
        r"Start-ScheduledTask.{0,40}(Hermes|HkGwRel)",
        r"Get-CimInstance\s+Win32_Process.{0,160}(bridge|hermes_cli|gateway)",
        r"Start-Process.{0,120}(headless|force_restart|gw_relaunch|Hermes_Gateway|restart_zalo)",
        r"wscript.{0,80}Hermes_Gateway",
        # long blind waits (Unix + Windows) — idle watchdog cannot see progress
        # threshold: >= 60 seconds
        r"\bsleep\s+(?:[6-9]\d|\d{3,})\b",
        r"Start-Sleep\s+(?:-Seconds\s+)?(?:[6-9]\d|\d{3,})",
        r"\btimeout\s+/t\s+(?:[6-9]\d|\d{3,})\b",
        r"\bping\s+-n\s+(?:[6-9]\d|\d{3,})\b",
        r"for\s+\w+\s+in\s+.*;\s*do\s+sleep\s+",
        r"while\s+true\s*;\s*do",
        r"while\s*\(\s*\$true\s*\)",
        r"for\s*\(\s*;\s*;\s*\)",  # C-style infinite
        r"time\.sleep\s*\(\s*(?:[6-9]\d|\d{3,})\s*\)",
        r"Thread\.Sleep\s*\(\s*(?:[6-9]\d{3,}|\d{5,})\s*\)",  # ms >= 60000
    )
)

# Tools that can embed hang cmds in non-command fields
_HANG_TOOL_NAMES = frozenset(
    {
        "terminal",
        "execute_code",
        "run_terminal_command",
        "shell",
        "process",
        "run_command",
    }
)


def _extract_terminal_command(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, str):
        try:
            import json as _json

            args = _json.loads(args)
        except Exception:
            return args
    if isinstance(args, dict):
        parts = []
        for k in (
            "command",
            "cmd",
            "code",
            "script",
            "data",
            "input",
            "args",
            "argv",
        ):
            v = args.get(k)
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                parts.append(" ".join(str(x) for x in v))
            else:
                parts.append(str(v))
        return "\n".join(parts)
    return str(args)


def _anti_hang_pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    session_id: str = "",
    **_: Any,
) -> Optional[Dict[str, str]]:
    """Hard-block hang-class ops (gateway restart / long sleep / infinite loops).

    Returns immediately with action=block so the model never sits in
    approval-wait or idle-timeout. Covers terminal + execute_code + process.
    """
    name = (tool_name or "").lower()
    if name not in _HANG_TOOL_NAMES:
        return None
    # Normalize dict args (may arrive as JSON string)
    parsed = args
    if isinstance(parsed, str):
        try:
            import json as _json

            parsed = _json.loads(parsed)
        except Exception:
            parsed = args
    # process(wait/poll) with large/missing timeout is itself a hang vector
    if name == "process" and isinstance(parsed, dict):
        action = str(parsed.get("action") or "").lower()
        if action in {"wait", "poll"}:
            raw_to = parsed.get("timeout")
            try:
                to = float(raw_to) if raw_to is not None else 9999.0
            except Exception:
                to = 9999.0
            if to >= 60 or raw_to is None:
                return {
                    "action": "block",
                    "message": (
                        "ANTI-HANG BLOCK: process wait/poll with timeout>=60s "
                        "(or no timeout) from chat. Finish turn or use timeout<=30."
                    ),
                }
    cmd = _extract_terminal_command(args)
    if not cmd:
        return None
    for pat in _HANG_CMD_PATTERNS:
        if pat.search(cmd):
            logger.warning(
                "anti-hang blocked tool=%s session=%s pattern=%s cmd=%.160s",
                name,
                session_id,
                pat.pattern,
                cmd.replace("\n", " "),
            )
            return {
                "action": "block",
                "message": (
                    "ANTI-HANG BLOCK: hang-class pattern "
                    f"({pat.pattern}). "
                    "Do NOT restart gateway/bridge, long-sleep, or infinite-loop from chat. "
                    "Allowlist: POST http://127.0.0.1:3001/allowlist "
                    '{"users":"UID","allowAll":false}. '
                    "Full restart: user runs desktop gw_relaunch.ps1 only — never this turn. "
                    "Pivot to a short non-restart approach now."
                ),
            }
    return None


def _pairzalo_pre_dispatch(event=None, gateway=None, **_kwargs):
    """Opt-in pairing only: /pairzalo or /pair on Zalo.

    Gateway default auto-sends pairing codes to unknown DMs; operators here
    prefer public guest chat + explicit command. unauthorized_dm_behavior is
    also set to ignore in config.yaml so non-command DMs never get a code.
    """
    if event is None or gateway is None:
        return None
    text = (getattr(event, "text", None) or "").strip()
    if not text:
        return None
    first = text.split(None, 1)[0].lower()
    # Accept /pairzalo, !pairzalo, pairzalo
    cmd = first.lstrip("/!").replace("-", "_")
    if cmd not in _PAIR_CMDS:
        return None

    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = source.platform.value if getattr(source, "platform", None) else ""
    if platform != "zalo":
        return None
    user_id = getattr(source, "user_id", None)
    if not user_id:
        return None

    store = getattr(gateway, "pairing_store", None)
    if store is None:
        return None

    user_name = getattr(source, "user_name", None) or ""
    chat_id = getattr(source, "chat_id", None) or user_id

    if store._is_rate_limited(platform, str(user_id)):
        msg = (
            "Bạn vừa xin mã pair rồi. Đợi ~10 phút rồi gửi /pairzalo lại."
        )
    else:
            code = store.generate_code(platform, str(user_id), user_name)
            if code:
                msg = (
                    f"Mã pair Zalo của bạn: {code}\n\n"
                    f"Gửi mã này cho chủ bot để duyệt:\n"
                    f"hermes pairing approve zalo {code}"
                )
                logger.info(
                    "pairzalo issued user=%s name=%s chat=%s",
                    user_id,
                    user_name,
                    chat_id,
                )
            else:
                msg = (
                    "Không tạo được mã pair lúc này (quá tải / rate-limit / lockout). "
                    "Thử lại sau."
                )

    async def _send() -> None:
        try:
            adapter = gateway._adapter_for_source(source)
            if adapter is None:
                logger.warning("pairzalo: no adapter for source")
                return
            await adapter.send(str(chat_id), msg)
        except Exception as exc:
            logger.warning("pairzalo send failed: %s", exc)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        # Not on an event loop — best-effort sync via bridge HTTP.
        try:
            import json
            import urllib.request

            port = int(os.getenv("ZALO_BRIDGE_PORT") or "3001")
            body = json.dumps(
                {"chatId": str(chat_id), "message": msg, "isGroup": False}
            ).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/send",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as exc:
            logger.warning("pairzalo sync send failed: %s", exc)

    return {"action": "skip", "reason": "pairzalo_cmd"}


def register(ctx) -> None:
    ctx.register_platform(
        name="zalo",
        label="Zalo (personal)",
        adapter_factory=lambda cfg: ZaloAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=_is_connected,
        required_env=["ZALO_ENABLED"],
        install_hint="npm install in %LOCALAPPDATA%\\hermes\\scripts\\zalo-bridge && enable ZALO_ENABLED=true",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        allowed_users_env="ZALO_ALLOWED_USERS",
        allow_all_env="ZALO_ALLOW_ALL_USERS",
        cron_deliver_env_var="ZALO_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        max_message_length=2000,
        emoji="💜",
        allow_update_command=True,
        platform_hint=(
            "You are chatting via Zalo (personal account bridge). "
            "Keep replies concise. Zalo messages MUST be normal plain chat text only: no bold, no italic, no markdown, no * # ` ** ###, no fancy unicode fonts. Write like a normal Zalo CSKH message. ALWAYS Vietnamese with full diacritics (tiếng Việt có dấu), never khong dau. "
            "GUEST / stranger DMs (not owner admin UID): you are ONLY a Hakinet parental-control consultant. "
            "Load skill hakinet-zalo-consult and read C:/Dev/AgentLab/knowledge/hakinet/ "
            "(PRODUCT, FEATURES, INSTALL, FAQ, PRICING_PAYMENT, CONTACT, CONSULTING_PLAYBOOK). "
            "Answer ONLY Hakinet / kids screen-time / block game-web / install Android-iOS-Windows / pricing. "
            "Refuse other topics politely; no code, no PC control, no non-Hakinet work. "
            "Owner/admin chats: full Hermes agent (still obey anti-hang). "
            "CRITICAL anti-hang (plugin pre_tool_call blocks instantly): "
            "(1) NEVER restart gateway / headless_full / force_restart_gw / gw_relaunch / kill bridge.js / "
            "long sleep/timeout loops from this session. "
            "(2) Allowlist: POST http://127.0.0.1:3001/allowlist JSON only — hot-reload. "
            "(3) Prefer short terminals; on block/deny pivot immediately. "
            "(4) No auto-continue after idle timeout — finish with clear status. "
            "Media: MEDIA: paths when possible. "
            "Pairing: only /pairzalo|/pair; owner hermes pairing approve zalo <code>."
        ),
    )
    # Hard block hang-class terminal before approval wait.
    ctx.register_hook("pre_tool_call", _anti_hang_pre_tool_call)
    # Explicit pairing only — no auto-code on first stranger DM.
    ctx.register_hook("pre_gateway_dispatch", _pairzalo_pre_dispatch)
    try:
        ctx.register_command(
            "pairzalo",
            lambda _args: (
                "Trên Zalo: gõ /pairzalo (hoặc /pair) để nhận mã pair. "
                "Chủ bot duyệt: hermes pairing approve zalo <code>"
            ),
            description="Xin ma pair Zalo (chi khi go lenh)",
        )
        ctx.register_command(
            "pair",
            lambda _args: (
                "Trên Zalo: gõ /pairzalo (hoặc /pair) để nhận mã pair. "
                "Chủ bot duyệt: hermes pairing approve zalo <code>"
            ),
            description="Alias /pairzalo",
        )
    except Exception as exc:
        logger.debug("pairzalo command register skipped: %s", exc)
