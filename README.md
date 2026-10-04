# skerter-notify

Made for my own projects to send Telegram notifications through a simple webhook when direct access to Telegram API is inconvenient or unreliable.

Supports multiple named destinations, Bearer auth and Docker deployment.

```http
POST /v1/notify
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

```json
{
  "destination": "monitoring",
  "title": "Something happened",
  "text": "Notification text"
}
```

Built with FastAPI + httpx.