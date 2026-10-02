# skerter-notify

Небольшой HTTP → Telegram relay для сервисов, которым нужен единый webhook. Принимает уведомление, отправляет его через Telegram Bot API и отвечает успешно только после `ok: true` от Telegram.

## Запуск

Нужен Python 3.12. Для локального запуска вне Docker переменные из `.env.example` задайте в окружении, затем:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"  # Windows
.venv/Scripts/uvicorn src.main:app --host 127.0.0.1 --port 18080
```

В Linux/macOS используйте `.venv/bin/` вместо `.venv/Scripts/`. Для Docker Compose скопируйте `.env.example` в `.env`, замените все placeholders реальными значениями и выполните `docker compose up --build`. Compose читает `.env` и передаёт переменные контейнеру. Порт опубликован только на `127.0.0.1:18080`; HTTPS и reverse proxy настраиваются отдельно.

Имена направлений и имена переменных окружения задаются в `config/destinations.yaml`. У каждого направления должны быть `bot_token_env` и `chat_id_env`. При старте сервис проверяет `API_KEY` и все эти переменные; при отсутствии значения запуск завершается ошибкой. Токены и chat ID в YAML не пишутся.

## Запрос

```bash
curl -X POST http://127.0.0.1:18080/v1/notify \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"destination":"website-a","title":"Test notification","text":"Hello from skerter-notify"}'
```

`GET /health` возвращает `{"status":"ok"}` без обращения к Telegram.

`POST /v1/notify` возвращает `{"status":"sent"}` и HTTP 200 только когда Telegram принял сообщение. Ошибки: 401 — неверная авторизация, 404 — неизвестное направление, 422 — неверный запрос, 502 — Telegram не принял сообщение. При сетевой ошибке, таймауте (5 секунд на попытку) или HTTP 5xx выполняется один повтор. После таймаута возможна повторная доставка: Telegram мог принять первый запрос, хотя ответ не дошёл до сервиса.

## Проверки

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check .
.venv/Scripts/mypy
docker compose config
```

Сервис намеренно пишет полные `title` и `text` в JSON-логи. Вызывающие сервисы должны очищать содержимое перед отправкой.
