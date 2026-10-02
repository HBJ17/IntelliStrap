"""Optional MQTT ingest (MQTT_ENABLED=true).

Topics: smartband/{device_id}/events (strap -> backend, same JSON as HTTP) and
smartband/{device_id}/commands (backend -> strap). Each strap has its own broker credentials and
the broker ACL only lets it publish to its own events topic, so the topic's device_id is trusted.
TLS is required (mqtts://).
"""
import json
import logging
import re
import ssl
from urllib.parse import urlparse

from pydantic import ValidationError

from .config import get_settings
from .db import session_scope
from .ingest import PayloadError, ingest_event, pop_commands
from .models import Strap
from .schemas import DeviceEvent

log = logging.getLogger(__name__)

EVENTS_TOPIC = "smartband/+/events"
_TOPIC_RE = re.compile(r"^smartband/(sb-[0-9A-Z]{12})/events$")
MAX_PAYLOAD = 4096

_client = None


def commands_topic(device_id: str) -> str:
    return f"smartband/{device_id}/commands"


def handle_message(client, topic: str, payload: bytes) -> bool:
    """Ingest one MQTT event. Returns True when it was accepted."""
    match = _TOPIC_RE.match(topic)
    if not match or len(payload) > MAX_PAYLOAD:
        log.warning("mqtt: ignoring message on %s", topic)
        return False
    device_id = match.group(1)
    try:
        event = DeviceEvent.model_validate(json.loads(payload))
    except (ValueError, ValidationError):
        log.warning("mqtt: bad event from %s", device_id)
        return False
    with session_scope() as db:
        strap = db.get(Strap, device_id)
        if strap is None:
            log.warning("mqtt: unknown device %s", device_id)
            return False
        try:
            ingest_event(db, strap, event.type, event.payload)
        except PayloadError:
            log.warning("mqtt: invalid payload from %s", device_id)
            return False
        commands = pop_commands(strap)
    if commands:
        client.publish(commands_topic(device_id), json.dumps({"commands": commands}), qos=1)
    return True


def publish_command(device_id: str, command: str) -> bool:
    """Push a command straight to the strap. The pending_command column stays as the HTTP fallback."""
    if _client is None:
        return False
    _client.publish(commands_topic(device_id), json.dumps({"commands": [command]}), qos=1)
    return True


def start():
    global _client
    import paho.mqtt.client as mqtt

    settings = get_settings()
    url = urlparse(settings.mqtt_url)
    if url.scheme not in ("mqtts", "ssl"):
        raise RuntimeError("MQTT_URL must use mqtts:// (TLS)")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="smartband-backend")
    client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("mqtt connected (%s); subscribing to %s", reason_code, EVENTS_TOPIC)
        c.subscribe(EVENTS_TOPIC, qos=1)

    def on_message(c, userdata, msg):
        try:
            handle_message(c, msg.topic, msg.payload)
        except Exception:
            log.exception("mqtt: failed to handle message on %s", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(url.hostname, url.port or 8883)
    client.loop_start()
    _client = client
    return client


def stop() -> None:
    global _client
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
