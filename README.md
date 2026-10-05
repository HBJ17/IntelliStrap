# IntelliStrap: SmartBand software

SmartBand is a capacitive food-level strap for opaque kitchen jars (ESP32-C3 + LM358). This repository turns it into a service:

- **Name and label each strap** on a dashboard (for example "Rice jar", containing Rice).
- **Background logging.** Every state change, recalibration and baseline drift is recorded. A labelled jar that stays LOW for the hold time (20 seconds) is added to a **shopping list**.
- **Ordering over WhatsApp (Twilio).** When the list reaches ₹400, the owner gets it on WhatsApp with **Order / Not now** buttons. Tapping Order sends the same list to the shopkeeper, exactly once.

```
[ESP32-C3 strap] --HTTPS (or MQTT)--> [FastAPI backend + DB] <--> [Dashboard]
                                               |
                                               +--> [Twilio WhatsApp] <--> owner / shopkeeper
```

| Path | What |
|---|---|
| `backend/` | FastAPI app, SQLAlchemy models, Alembic migration, rules, scheduler, messaging, dashboard (`static/`), tests |
| `tools/fake_strap.py` | CLI that behaves like a strap |
| `tools/provision.py` | Pre-registers straps and prints claim-code stickers |
| `firmware/smartband_v5/` | Networking, persistence and provisioning around the existing detection block |
| `docs/DECISIONS.md` | Every default and assumption taken while building |

## Quick start (simulator, no Twilio, no hardware)

These commands are for Windows (PowerShell). On macOS/Linux, use `source .venv/bin/activate` and `cp`.

```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate
```
```bash
pip install -e "backend[dev]"
```
```bash
copy .env.example .env
```

Edit `.env` and set `DASHBOARD_PASSWORD`. For the demo, also set `DEV_HOLD_SECONDS=10`.

Load the demo data. **Do this once only.** Running it again just reports that the data is already loaded:

```bash
python -m app.seed
```

Start the server. Do this every time; it works from the project root with the venv active:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Press Ctrl+C to stop it.

Open http://localhost:8000 and sign in. `app.seed` creates one owner, an opted-in shop, a priced catalog (Rice ₹60, Toor dal ₹150, Poha ₹90, Sago ₹110, Sugar ₹55, Tea ₹120) and **one** strap, `sb-DEMO00000001` ("Rice jar", labelled Rice). Its token is saved in `.fake_straps.json`, so `fake_strap.py` can drive it straight away. Add more straps with **Add strap** and remove them with **Delete** on a strap card.

### Demo script: jar LOW → list → Order → shop receives it once

1. Open the **Shopping list** tab and the **WhatsApp simulator** panel (bottom right).
2. Make the jar report LOW (from the repo root):
   ```bash
   python tools/fake_strap.py low --id sb-DEMO00000001
   ```
   You can also use **Goes LOW** in the simulator panel.
3. Wait out the hold time (`DEV_HOLD_SECONDS`), or click **Skip hold time**. Rice (₹60) appears on the list.
4. The list is sent automatically once it reaches the ₹400 threshold. With one jar, either press **Send now**, or lower the threshold in **Settings** (for example to ₹50) before step 2. The owner's message, with **Order** and **Not now** buttons, appears in the simulator.
5. Click **Order**. The shop message appears once, followed by "Sent to Sharma General Store.". Clicking Order again only produces "already handled".
6. Try **Refilled (OK)** to see a pending row cleared, or **Not now** to see the row return to the list.

### fake_strap.py

```
python tools/fake_strap.py register  --id sb-TEST00000001   # prints the claim code
python tools/fake_strap.py low       --id sb-TEST00000001
python tools/fake_strap.py ok        --id sb-TEST00000001
python tools/fake_strap.py recal     --id sb-TEST00000001 --baseline 800
python tools/fake_strap.py drift     --id sb-TEST00000001 --baseline 805
python tools/fake_strap.py heartbeat --id sb-TEST00000001 --loop 60
python tools/fake_strap.py commands  --id sb-TEST00000001
```

It reads `DEVICE_PROVISION_SECRET` and `SMARTBAND_URL` (default `http://localhost:8000`) from the environment or `.env`. Like the real firmware, it answers a `recalibrate` command with a `recalibration` event.

### Tests

```bash
cd backend && pytest
```

The suite uses a controllable clock (no sleeping). It covers rules R1–R14, the webhook signature check, double taps, the four-jar threshold case, missing prices, pruning, `format_items_inline`, and the security matrix (`tests/test_hardening.py`).

## Messaging modes

Set `MESSAGING_MODE` in `.env` and restart the backend.

| Mode | Use |
|---|---|
| `simulator` (default) | Messages show in the dashboard's simulator panel. Use it for demos with no internet, too. |
| `twilio_sandbox` | Real WhatsApp through the Twilio sandbox (demo). |
| `twilio_production` | Registered WhatsApp sender with approved templates. |

### Twilio sandbox setup (demo)

1. Create a Twilio account. Put `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env`. Keep `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`.
2. **Join the sandbox from every phone** (the owner and the shopkeeper). Send `join <your-code>` to +1 415 523 8886 on WhatsApp. Sandbox sessions expire after about 3 days, so **re-join on the morning of the demo**.
3. Open a public HTTPS tunnel to the backend. Either:
   ```bash
   ngrok http 8000
   ```
   or
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   Set `PUBLIC_BASE_URL` to the tunnel URL (for example `https://abc123.ngrok.app`). It must match exactly, because the webhook signature is computed over it.
4. In the Twilio console, go to **Messaging → Try it out → WhatsApp sandbox settings**. Set **When a message comes in** to `PUBLIC_BASE_URL/webhooks/twilio` (HTTP POST).
5. In the dashboard **Settings**, set the owner's and the shop's WhatsApp numbers in E.164 format (`+91…`) and mark the shop as opted in.
6. **Check on day one whether interactive buttons work in your sandbox.** Without `TWILIO_CONTENT_SID_OWNER`, the list goes out as plain text ending in "Reply ORDER to send to the shop or NO to skip.". If you create a Quick Reply content template and buttons do arrive, set the SID. Typed ORDER / NO replies are accepted either way.

Every webhook is checked against `X-Twilio-Signature` before anything else runs. Unsigned or forged requests get `403`.

### Production checklist

- [ ] **WhatsApp sender:** register it in Twilio, which requires Meta Business verification. This takes days, so start early.
- [ ] **Two Content Templates,** category **Utility**, Quick Reply type, with no promotional wording, submitted and approved:
  - Owner: `Your pantry list is ₹{{2}}: {{1}}. Send this order to your shop?` with buttons **Order** (id `order:{{3}}:yes`) and **Not now** (id `order:{{3}}:no`). Put its SID in `TWILIO_CONTENT_SID_OWNER`.
  - Shop: `New order from {{1}}: {{2}}. Total ₹{{3}}. Please confirm delivery.` with no buttons. Put its SID in `TWILIO_CONTENT_SID_SHOP`.
- [ ] **Shopkeeper opt-in:** the shopkeeper must have opted in to receive messages. Record it with Settings → Shop → opted in. Without it, the backend refuses to send to the shop and tells the owner.
- [ ] **Webhook:** point the sender's incoming-message webhook at `https://<your-domain>/webhooks/twilio`.
- [ ] **Environment:** set `APP_ENV=production` and real values for `DASHBOARD_PASSWORD`, `SESSION_SECRET` and `DEVICE_PROVISION_SECRET`. The app refuses to start with `change-me` values.
- [ ] **Pricing:** cost per message = Meta fee + Twilio fee + 18% GST. When checked on 2026-10-02, the Twilio WhatsApp pricing page listed the **Twilio fee as $0.005 per message**. The Meta fee for India depends on the template category (utility) and whether the message falls inside the 24-hour service window. Read the current figure from Meta's WhatsApp rate card (linked from https://www.twilio.com/en-us/whatsapp/pricing) and check again before going live.

## Strap lifecycle

1. **Bench (optional).** Pre-register the strap and print a sticker with its claim code:
   ```bash
   python tools/provision.py --mac A1:B2:C3:D4:E5:F6 --url https://smartband.example.com
   ```
2. **First boot.** With no Wi-Fi in flash, the strap opens a hotspot named `IntelliStrap-XXXX`. Join it and fill in the Wi-Fi name, password and backend URL. The strap saves these to flash and reboots.
3. **Registration.** The strap registers with the backend, stores its token in flash, and prints its claim code to Serial. If it was pre-registered, the claim code is the same one as on the sticker.
4. **Adding.** In the dashboard, go to **Add strap**, enter the code, name the jar, and type its contents label and price.
5. **Reporting.** The strap sends `state_change` events (after the existing 5-count confirmation), plus a heartbeat about every 3 minutes and throttled baseline-drift events. A strap that is silent for 15 minutes shows as **Offline** (never as its last state), and the owner gets one WhatsApp alert.
6. **Button.** A short press recalibrates the strap. Holding it for 10 s performs a factory reset, which wipes Wi-Fi, token and baseline.

## Firmware

**The original detection code is needed.** `firmware/smartband_v5/detection.cpp` stops the build with an `#error` until the existing SmartBand v5 detection block (mutual capacitance, adaptive baseline, hysteresis, 5-count confirmation) is pasted in **unchanged**. The comments in that file show where it goes. The wrapper code has not been compiled yet. See `docs/DECISIONS.md`.

To build:

1. Copy `config.h.example` to `config.h` and fill in the pins, the provisioning secret and the backend CA certificate.
2. Build with PlatformIO (`pio run -t upload`) or open `smartband_v5.ino` in the Arduino IDE.

## Deployment notes (TLS)

- Run uvicorn behind a reverse proxy that terminates TLS (Caddy or nginx with Let's Encrypt). Start uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy-ip>` so rate limiting sees real client IPs. Example Caddyfile:
  ```
  smartband.example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```
- Put the CA that signed your certificate in the firmware's `BACKEND_CA_CERT` (ISRG Root X1 for Let's Encrypt).
- **MQTT (optional):** set `MQTT_ENABLED=true` and `MQTT_URL=mqtts://broker:8883`. TLS is required. Give each strap its own broker credentials, with an ACL that limits it to `smartband/<device_id>/events` (publish) and `smartband/<device_id>/commands` (subscribe).
- **Single process:** run one backend process. The scheduler and the rate limiter live in that process. Scheduler state is kept in the database, so restarts lose nothing.
- **Plain HTTP:** use only for local development on `localhost`.

## Hardware-dependent checks (manual)

| Case | How to check |
|---|---|
| No Wi-Fi password in firmware | `grep -ri password firmware/` shows only the setup-portal form and `SETUP_AP_PASSWORD` |
| Reboot on a full jar | Power-cycle the strap. Serial shows `baseline … loaded from flash`, and no `recalibration` event is logged |
| Jar refilled, strap LOW briefly | Refill the jar. The 5-count confirmation plus the 20-second hold absorb it, and the dashboard history shows no list entry |
| Buzzer without Wi-Fi | Switch the router off and empty a jar. The strap beeps twice; its events are queued and sent on reconnect |
| Strap silent | Unplug it. After 15 minutes the card shows **Offline**, and the owner gets one alert |
