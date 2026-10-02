import json
import logging
import time
from typing import Any, Mapping

from ..config import Settings
from .base import MessagingError, ParsedReply, parse_reply_form

log = logging.getLogger(__name__)


def whatsapp_address(number: str) -> str:
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


class TwilioMessenger:
    """Shared Twilio plumbing. Subclasses decide between templates and free text."""

    mode = "twilio"
    attempts = 3
    backoff_s = 1.0

    def __init__(self, settings: Settings, client: Any = None, sleep=time.sleep):
        self.settings = settings
        self._client = client
        self._sleep = sleep

    @property
    def client(self):
        if self._client is None:
            if not (self.settings.twilio_account_sid and self.settings.twilio_auth_token):
                raise MessagingError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set")
            from twilio.rest import Client
            self._client = Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)
        return self._client

    def _create(self, to: str, *, body: str | None = None, content_sid: str | None = None,
                variables: Mapping[str, str] | None = None) -> str:
        """Send, retrying transient provider errors with exponential backoff (1 s, 2 s)."""
        for attempt in range(1, self.attempts + 1):
            try:
                return self._create_once(to, body=body, content_sid=content_sid, variables=variables)
            except MessagingError as exc:
                if not exc.transient or attempt == self.attempts:
                    raise
                log.warning("twilio send failed (attempt %d/%d): %s", attempt, self.attempts, exc)
                self._sleep(self.backoff_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _create_once(self, to: str, *, body: str | None, content_sid: str | None,
                     variables: Mapping[str, str] | None) -> str:
        from twilio.base.exceptions import TwilioRestException

        kwargs: dict[str, Any] = {"from_": self.settings.twilio_whatsapp_from, "to": whatsapp_address(to)}
        if content_sid:
            kwargs["content_sid"] = content_sid
            kwargs["content_variables"] = json.dumps(dict(variables or {}))
        else:
            kwargs["body"] = body
        try:
            message = self.client.messages.create(**kwargs)
        except TwilioRestException as exc:
            transient = exc.status == 429 or exc.status >= 500
            raise MessagingError(f"Twilio error {exc.code or exc.status}: {exc.msg}", transient=transient) from exc
        except MessagingError:
            raise
        except Exception as exc:  # network trouble: worth retrying
            raise MessagingError(f"could not reach Twilio: {exc}", transient=True) from exc
        log.info("twilio message %s queued (%s)", message.sid, "template" if content_sid else "text")
        return message.sid

    def send_text(self, to: str, text: str) -> str:
        return self._create(to, body=text)

    def parse_webhook(self, form: Mapping[str, str]) -> ParsedReply | None:
        return parse_reply_form(form)
