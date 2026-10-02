"""HTTP API for the notification relay."""

import hmac
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from html import escape
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from src.config import Config, load_config
from src.telegram import DeliveryError, send_message


class NotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3500)
    ]


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("skerter_notify")
    for old_handler in logger.handlers[:]:
        logger.removeHandler(old_handler)
        old_handler.close()
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # httpx's standard request log includes the bot token in the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logger


def create_app(
    config: Config | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        app.state.config = config if config is not None else load_config()
        app.state.logger = configure_logging()
        async with httpx.AsyncClient(timeout=5.0, transport=transport) as client:
            app.state.telegram_client = client
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/notify")
    async def notify(
        payload: NotifyRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        parts = authorization.split() if authorization else []
        if (
            len(parts) != 2
            or parts[0].lower() != "bearer"
            or not hmac.compare_digest(
                parts[1].encode(), app.state.config.api_key.encode()
            )
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")

        destination = app.state.config.destinations.get(payload.destination)
        if destination is None:
            raise HTTPException(status_code=404, detail="Destination not found")

        started = time.perf_counter()
        fields = {
            "destination": payload.destination,
            "title": payload.title,
            "text": payload.text,
        }
        message = f"<b>{escape(payload.title)}</b>\n\n{escape(payload.text)}"
        try:
            await send_message(app.state.telegram_client, destination, message)
        except DeliveryError as exc:
            app.state.logger.error(
                json.dumps(
                    {
                        "event": "notification_failed",
                        **fields,
                        "error": str(exc),
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    },
                    ensure_ascii=False,
                )
            )
            raise HTTPException(
                status_code=502, detail="Telegram delivery failed"
            ) from None

        app.state.logger.info(
            json.dumps(
                {
                    "event": "notification_sent",
                    **fields,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
                ensure_ascii=False,
            )
        )
        return {"status": "sent"}

    return app


app = create_app()
