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

## CI и автодеплой

- `CI` (`.github/workflows/ci.yaml`): push в `dev`, pull request в `main`/`dev` и вызов из CD. Проверяет Ruff, mypy, pytest и конфигурацию Compose на Python 3.12.
- `CD` (`.github/workflows/cd.yaml`): push в `main` или ручной запуск для `main`. Сначала вызывает CI, затем по SSH обновляет код на VDS и запускает `docker compose up -d --build --wait --wait-timeout 120`.

Единственная production-конфигурация — `compose.yaml` в корне. Образ собирается на VDS, запуск проверяется через `/health`. На push в `main` проверки выполняются один раз, внутри CD.

В GitHub → Settings → Secrets and variables → Actions задайте repository secrets:

| Secret | Значение |
| --- | --- |
| `VPS_HOST` | Адрес сервера |
| `VPS_USER` | SSH-пользователь с доступом к Docker и каталогу проекта |
| `VPS_SSH_KEY` | Приватный SSH-ключ; публичный ключ добавьте в `authorized_keys` на VPS |
| `VPS_SSH_FINGERPRINT` | SHA256 fingerprint SSH host key из доверенной консоли сервера |

Fingerprint можно получить в консоли VDS: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`. В secret сохраните только значение `SHA256:…`.

Необязательные repository variables: `VPS_DEPLOY_PATH` (по умолчанию `/opt/skerter-notify`) и `VPS_SSH_PORT` (по умолчанию `22`).

Перед первым деплоем установите на VDS Git, Docker и Compose v2 с поддержкой `up --wait`. От имени SSH-пользователя подготовьте checkout и `.env`:

```bash
git clone --branch main https://github.com/Skerter/skerter-notify.git /opt/skerter-notify
cd /opt/skerter-notify
cp .env.example .env
chmod 600 .env
# Заполните .env реальными API_KEY, Telegram bot tokens и chat IDs.
```

Для приватного репозитория отдельно настройте доступ VDS к `git fetch origin main`. Изменения `config/destinations.yaml` нужно коммитить в репозиторий. Секреты хранятся в `.env` на сервере.

CD пропускает устаревший коммит и обновляет checkout только через fast-forward до проверенного CI коммита. Локальные изменения отслеживаемых файлов останавливают деплой. Порт остаётся `127.0.0.1:18080`. Ошибка сборки или проверки здоровья завершает workflow с ошибкой; автоматического отката нет.

Ручное управление выполняйте из корня checkout:

```bash
docker compose ps
docker compose logs --tail 100 notify
docker compose up -d --build --wait
```
