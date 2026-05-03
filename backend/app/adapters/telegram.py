"""Telegram Bot API adapter — alerting service.

Verified against https://core.telegram.org/bots/api (Bot API 9.6, 2026-04).
Base URL: https://api.telegram.org/bot{TOKEN}/{METHOD}
Methods used: sendMessage, sendDocument, sendPhoto, getMe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger

logger = get_logger(__name__)


class TelegramAdapter(BaseHTTPAdapter):
    provider_name = "telegram"
    requires_api_key = True

    def __init__(self) -> None:
        if not settings.telegram_bot_token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN missing")
        token = settings.telegram_bot_token.get_secret_value()
        super().__init__(
            base_url=f"https://api.telegram.org/bot{token}",
            api_key=token,
            timeout=15.0,
            max_retries=3,
        )
        self._default_chat = settings.telegram_default_chat_id

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self.post_json(f"/{method}", json=payload)
        if not data.get("ok"):
            raise ExternalAPIError(
                f"telegram.{method}: {data.get('description')}",
                provider=self.provider_name,
                upstream_status=data.get("error_code"),
                details={"method": method},
            )
        return data.get("result") or {}

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe", {})

    async def send_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        cid = chat_id or self._default_chat
        if not cid:
            raise ConfigurationError("Telegram: no chat_id provided / configured")
        return await self._call("sendMessage", {
            "chat_id": cid,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        })

    async def send_document(
        self,
        file_path: str | Path,
        *,
        caption: str | None = None,
        chat_id: int | str | None = None,
    ) -> dict[str, Any]:
        cid = chat_id or self._default_chat
        if not cid:
            raise ConfigurationError("Telegram: no chat_id provided / configured")
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        # multipart upload via httpx — we cannot use post_json (which JSON-encodes).
        with path.open("rb") as f:
            files = {"document": (path.name, f.read(),
                                  "application/pdf"
                                  if path.suffix.lower() == ".pdf"
                                  else "application/octet-stream")}
        form: dict[str, str] = {"chat_id": str(cid)}
        if caption:
            form["caption"] = caption
            form["parse_mode"] = "HTML"
        response = await self._client.post("/sendDocument", data=form, files=files)
        if response.status_code != 200:
            raise ExternalAPIError("telegram.sendDocument failed",
                                   provider=self.provider_name,
                                   upstream_status=response.status_code)
        data = response.json()
        if not data.get("ok"):
            raise ExternalAPIError(f"telegram.sendDocument: {data.get('description')}",
                                   provider=self.provider_name)
        return data["result"]
