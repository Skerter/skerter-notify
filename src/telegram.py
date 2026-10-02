"""Minimal Telegram Bot API adapter."""

import httpx

from src.config import Destination


class DeliveryError(Exception):
    def __init__(self, code: str, exception_type: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.exception_type = exception_type


async def send_message(
    client: httpx.AsyncClient, destination: Destination, message: str
) -> None:
    url = f"https://api.telegram.org/bot{destination.bot_token}/sendMessage"
    for attempt in range(2):
        try:
            response = await client.post(
                url,
                json={
                    "chat_id": destination.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
        except httpx.TimeoutException as exc:
            error = DeliveryError("telegram_timeout", type(exc).__name__)
        except httpx.TransportError as exc:
            error = DeliveryError("telegram_transport", type(exc).__name__)
        else:
            if 500 <= response.status_code <= 599:
                error = DeliveryError("telegram_server")
            elif response.status_code != 200:
                raise DeliveryError("telegram_rejected")
            else:
                try:
                    body = response.json()
                except ValueError:
                    raise DeliveryError("telegram_invalid_response") from None
                if isinstance(body, dict) and body.get("ok") is True:
                    return
                raise DeliveryError("telegram_rejected")

        if attempt == 1:
            raise error
