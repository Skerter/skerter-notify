import json
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config import Config, Destination, load_config
from src.main import create_app

TOKEN = "test-bot-token"
KEY = "test-api-key"
CHAT_ID = "test-chat-id"
PAYLOAD = {"destination": "website-a", "title": "Title", "text": "Message"}
AUTH = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def config() -> Config:
    return Config(
        api_key=KEY,
        destinations={"website-a": Destination(bot_token=TOKEN, chat_id=CHAT_ID)},
    )


def client_for(
    config: Config, handler: Callable[[httpx.Request], httpx.Response]
) -> TestClient:
    return TestClient(create_app(config, httpx.MockTransport(handler)))


def forbidden(_request: httpx.Request) -> httpx.Response:
    pytest.fail("Request contacted Telegram")


def test_health_does_not_contact_telegram(config: Config) -> None:
    with client_for(config, forbidden) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_success_and_html_escaping(config: Config) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    payload = {
        "destination": "website-a",
        "title": "<New & request>",
        "text": 'Alice <script> & "Bob"',
    }
    with client_for(config, handler) as client:
        response = client.post("/v1/notify", headers=AUTH, json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    assert len(seen) == 1
    assert str(seen[0].url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert json.loads(seen[0].content) == {
        "chat_id": CHAT_ID,
        "text": (
            "<b>&lt;New &amp; request&gt;</b>\n\n"
            "Alice &lt;script&gt; &amp; &quot;Bob&quot;"
        ),
        "parse_mode": "HTML",
    }


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer wrong"}],
)
def test_auth_failure_never_sends(config: Config, headers: dict[str, str]) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Unauthorized request contacted Telegram")

    with client_for(config, forbidden) as client:
        response = client.post("/v1/notify", headers=headers, json=PAYLOAD)
    assert response.status_code == 401


def test_unknown_destination_never_sends(config: Config) -> None:
    with client_for(config, forbidden) as client:
        response = client.post(
            "/v1/notify", headers=AUTH, json={**PAYLOAD, "destination": "missing"}
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("destination", "  "),
        ("title", ""),
        ("title", "  "),
        ("title", "x" * 201),
        ("text", ""),
        ("text", "  "),
        ("text", "x" * 3501),
        ("parse_mode", "HTML"),
    ],
)
def test_invalid_payload_never_sends(config: Config, field: str, value: str) -> None:
    payload = {**PAYLOAD, field: value}
    with client_for(config, forbidden) as client:
        response = client.post("/v1/notify", headers=AUTH, json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("timeout", "telegram_timeout"),
        ("transport", "telegram_transport"),
        ("server", "telegram_server"),
    ],
)
def test_transient_failure_retries_once(
    config: Config, failure: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("hidden URL", request=request)
            if failure == "transport":
                raise httpx.ConnectError("hidden URL", request=request)
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    with client_for(config, handler) as client:
        logger = logging.getLogger("skerter_notify")
        logger.addHandler(caplog.handler)
        try:
            response = client.post("/v1/notify", headers=AUTH, json=PAYLOAD)
        finally:
            logger.removeHandler(caplog.handler)
    logs = "\n".join(record.getMessage() for record in caplog.records)

    assert response.status_code == 200
    assert calls == 2
    assert "notification_sent" in logs
    assert expected not in logs


def test_telegram_4xx_is_not_retried(config: Config) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"ok": False})

    with client_for(config, handler) as client:
        response = client.post("/v1/notify", headers=AUTH, json=PAYLOAD)
    assert response.status_code == 502
    assert response.json() == {"detail": "Telegram delivery failed"}
    assert calls == 1


@pytest.mark.parametrize("status", [503, 200])
def test_telegram_failure_after_retry_or_false_ok(config: Config, status: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"ok": False})

    with client_for(config, handler) as client:
        response = client.post("/v1/notify", headers=AUTH, json=PAYLOAD)
    assert response.status_code == 502
    assert calls == (2 if status == 503 else 1)


def test_failure_logs_have_no_secrets(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"secret URL {request.url} key {KEY} chat {CHAT_ID}", request=request
        )

    with client_for(config, handler) as client:
        logger = logging.getLogger("skerter_notify")
        logger.addHandler(caplog.handler)
        try:
            response = client.post("/v1/notify", headers=AUTH, json=PAYLOAD)
        finally:
            logger.removeHandler(caplog.handler)
    logs = "\n".join(record.getMessage() for record in caplog.records)

    assert response.status_code == 502
    entry = json.loads(logs.strip())
    assert entry["event"] == "notification_failed"
    assert entry["title"] == PAYLOAD["title"]
    assert entry["text"] == PAYLOAD["text"]
    assert entry["error"] == "telegram_transport"
    for secret in (TOKEN, KEY, CHAT_ID, "api.telegram.org"):
        assert secret not in logs
        assert secret not in response.text


def test_missing_destination_secret_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "destinations.yaml"
    path.write_text(
        "destinations:\n  website-a:\n"
        "    bot_token_env: TG_TOKEN\n    chat_id_env: TG_CHAT\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="TG_CHAT"):
        load_config(path, {"API_KEY": KEY, "TG_TOKEN": TOKEN})
