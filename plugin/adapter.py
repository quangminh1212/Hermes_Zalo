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
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
            payload: Dict[str, Any] = {
                "chatId": target,
                "message": content,
                "isGroup": is_group,
            }
            if reply_to:
                payload["replyTo"] = {"msgId": reply_to}
            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/send",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and data.get("success"):
                    return SendResult(success=True, message_id=data.get("messageId"))
                return SendResult(
                    success=False, error=data.get("error") or f"HTTP {resp.status}"
                )
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
            payload["caption"] = caption
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
            "Keep replies concise. Markdown is limited — prefer plain text. "
            "CRITICAL anti-hang rules: "
            "(1) NEVER restart Hermes gateway / headless_full / kill bridge.js from a Zalo session — "
            "that blocks for minutes waiting for approval and leaves the chat hung. "
            "(2) To change allowlist: POST http://127.0.0.1:3001/allowlist "
            'with JSON {\"users\":\"uid1,uid2\"} OR edit .env then POST the same — '
            "hot-reload, no process restart. "
            "(3) Prefer short tool loops; if a terminal needs elevated/approval, stop and tell the user instead of waiting. "
            "Media: MEDIA: paths and images/files are delivered natively when possible."
        ),
    )
