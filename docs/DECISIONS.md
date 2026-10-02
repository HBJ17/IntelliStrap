# Decisions

Defaults taken from the spec (Section 2), plus every assumption made while building.

## Defaults from the spec

| Question | Decision |
|---|---|
| Demo vs real deployment | Built for the demo first (simulator + Twilio sandbox). Production sits behind `MESSAGING_MODE=twilio_production`. |
| HTTPS POST vs MQTT | Straps use HTTPS POST (v1). Commands go back in the `events` response and through `GET /api/device/commands`. An MQTT ingest adapter exists behind `MQTT_ENABLED` and calls the same `ingest_event()`. |
| Who enters prices | The owner, in Settings → Catalog. |
| Shops per owner | One (`owners.shop_id`). |
| Shopkeeper Confirm button | Not in v1. The shop message has no buttons. `messaging/base.shop_template_variables` and `send_shop_order` are the extension point. |
| Database | SQLite through SQLAlchemy 2.x with Alembic migrations. Enums are stored as VARCHAR (non-native) and the partial unique index has both `sqlite_where` and `postgresql_where`, so the schema also works on Postgres. |
| Dashboard | Plain HTML and vanilla JS served by FastAPI. It polls every 3 s and only uses the JSON API. |
| Auth | One dashboard password (`DASHBOARD_PASSWORD`) and a signed, HttpOnly session cookie (itsdangerous, 7 days). Each device has its own token. |

## Assumptions made while building

### Layout and tooling
- **Repo layout:** the spec's `smartband/` folder is the repository root (`backend/`, `firmware/`, `tools/`, `docs/`).
- **Relative SQLite paths:** `sqlite:///./smartband.db` resolves against `backend/`, whatever the working directory. `.env` is read from the repo root or from `backend/`.
- **Schema setup:** the schema is created by `alembic upgrade head`, which runs on app startup and in `python -m app.seed`. A test checks that the migration matches the models.
- **Money:** stored as integer rupees in fields ending `_inr`.

### Device protocol and ingest
- **Device auth:** the strap sends `X-Device-Id` next to `Authorization: Bearer <token>`, so the backend can find the row and compare token hashes in constant time. A token is 32 random bytes; the backend stores its SHA-256 (no slow KDF needed for random secrets).
- **Device ID format:** `^sb-[0-9A-Z]{12}$`. Real MACs are hex, but the spec's own examples (`sb-TEST00000001`) use letters, so any uppercase letter is allowed.
- **Re-registration:** when a device ID registers again (after a factory reset, or after `tools/provision.py`), the backend rotates the token and keeps the name, label, owner and any unused claim code. This makes pre-printed stickers work: provision at the bench, then let the strap register itself.
- **Throttled drift events:** a drift event that arrives inside the throttle window is not logged. It still updates `last_seen` and the strap's latest baseline.
- **Repeat LOW reports:** a repeat LOW does not reset `state_since`, so the hold timer keeps counting from the first LOW.

### Shopping list and orders
- **`price_at_time_inr` is nullable.** NULL means "needs price" (R9). When the owner later enters a price, pending unpriced rows for that item are filled in and the threshold is checked again.
- **Threshold reached while an item is unpriced (R9):** the automatic order contains only the priced rows. Unpriced rows stay pending, so an order never contains an unpriced item. **Send now** refuses outright until every price is entered.
- **`list_items.strap_id` is nullable**, so items can be added by hand from the catalog. Each manual add creates a new row (no quantity merging).
- **Removing a row:** removing a row or refilling a jar marks the row `cancelled` instead of deleting it, so history stays intact.
- **Refill while an order is open:** a refill marks an `ordered` row `fulfilled`, even if the owner has not answered yet. The order total does not change.
- **Not now and expiry:** both return rows to `pending` and unlink them from the order. The order keeps its total, but its item list becomes empty.
- **Opt-in check:** the shop opt-in check runs in every messaging mode, not only production. This means the simulator also shows the "shop not opted in" failure.
- **Owner reply matching:** the sender's number must match the order owner's WhatsApp number. Replies from unknown numbers are ignored. A keyword reply (`ORDER`, `YES`, `Y`, `CONFIRM` / `NO`, `NOT NOW`, `SKIP`, `CANCEL`) applies to that owner's most recent `awaiting_owner` order. A bare "OK" is not treated as a keyword because it is ambiguous.
- **Idempotency (R14):** order status changes use a conditional `UPDATE … WHERE status IN (…)` and check the row count, so a double tap is handled once even when two requests race.
- **Extra order columns:** `orders.last_error` holds the reason an order is unsent. The dashboard can retry an unsent order (resent to the owner, or to the shop if the owner already tapped Order) or cancel it.
- **Retries:** transient Twilio errors (HTTP 429, 5xx, network) are retried 3 times with 1 s and 2 s backoff. After that the order becomes `send_failed`.

### Reminders and alerts
- **R11 reminder:** the reminder re-sends the owner-list message itself, so in production it is still an approved template. Expiry is measured from `owner_sent_at` (or `created_at` if the list was never sent).
- **R12 (refill reminder):** applies only to rows whose order reached `sent_to_shop`, counted from `sent_to_shop_at`. The delay is a new global setting, `refill_reminder_days` (default 4). `list_items.refill_reminder_sent_at` makes sure it is sent once.
- **Offline alerts:** the owner gets one WhatsApp text when a claimed strap goes silent for `offline_minutes`. `straps.offline_alerted_at` records it, and the next event clears it.

### Dashboard and simulator
- **Fill bar:** shows `gap / fill_gap_full` (new setting, default 40). The firmware's gap scale is not in the spec, so tune this per strap type. It is display only.
- **Simulator panel:** a floating, collapsible panel shown only when `MESSAGING_MODE=simulator`. "Skip hold time" runs the hold check with a zero hold. `DEV_HOLD_SECONDS` also shortens the scheduler interval.
- **`parse_webhook()`:** takes the already-parsed form dict instead of the raw request, so messengers stay synchronous and easy to test.

### Twilio
- **Sandbox buttons:** the sandbox sends a Content Template (buttons) only when `TWILIO_CONTENT_SID_OWNER` is set. Otherwise it sends plain text ending with the ORDER/NO prompt. Keyword replies are always accepted.
- **Template quick-reply IDs:** owner template buttons are assumed to use the IDs `order:{{3}}:yes` and `order:{{3}}:no`. Variables: `{{1}}` items, `{{2}}` total, `{{3}}` order ID.
- **Free-form texts in production:** confirmations ("Sent to …") are free-form. They go out right after the owner replies, inside WhatsApp's 24-hour service window. Refill reminders and offline alerts are also free-form, so in production they only arrive while a session is open. A dedicated template would be needed to guarantee delivery.

### Hardening
- **Rate limits:** in memory, per client IP: `/api/device/*` 120/min and `/api/login` 10/min (configurable via `RATE_LIMIT_*`). Because the limits are in memory, run a single backend process, or move the limits to the reverse proxy.
- **Body size:** request bodies are capped at 16 KB (`MAX_BODY_BYTES`). Chunked uploads without a length are refused.
- **Placeholder secrets:** outside `APP_ENV=dev`, the app refuses to start while `DASHBOARD_PASSWORD`, `SESSION_SECRET` or `DEVICE_PROVISION_SECRET` is still `change-me`. In that case the session cookie is also marked `Secure`.
- **MQTT:** requires `mqtts://`. The broker ACL must ensure a strap can only publish to `smartband/<its id>/events`, because the adapter trusts the device ID in the topic.

### Firmware
- **Detection source missing:** the original firmware (detection block) was not in the repository. `firmware/smartband_v5/detection.cpp` defines the interface the wrapper needs and contains an `#error` until the original code is pasted in unchanged. Nothing about detection was rewritten.
- **Not compiled:** the firmware wrapper has not been compiled here (no Arduino or PlatformIO toolchain was available). It targets arduino-esp32 2.x/3.x APIs (`Preferences`, `WebServer`, `DNSServer`, `HTTPClient`, `WiFiClientSecure`).
- **TLS:** the firmware refuses HTTPS when `BACKEND_CA_CERT` is not set, instead of falling back to unverified TLS. Plain `http://` URLs are allowed for LAN development only.
