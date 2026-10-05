"""Twilio WhatsApp sandbox (demo).

Interactive buttons are only used when TWILIO_CONTENT_SID_OWNER is set and has been checked to
work in the sandbox. Otherwise the list goes out as plain text ending in the ORDER / NO prompt.
Keyword replies are parsed in every case.
"""
from .base import (KEYWORD_FOOTER, SHOP_KEYWORD_FOOTER, owner_list_text, owner_template_variables, shop_order_text,
                   shop_template_variables)
from .twilio_common import TwilioMessenger


class TwilioSandboxMessenger(TwilioMessenger):
    mode = "twilio_sandbox"

    def send_owner_list(self, order) -> list[str]:
        to = order.owner.whatsapp_number
        sid = self.settings.twilio_content_sid_owner
        if sid:
            return [self._create(to, content_sid=sid, variables=owner_template_variables(order))]
        return [self._create(to, body=f"{owner_list_text(order)}\n{KEYWORD_FOOTER} (order #{order.id})")]

    def send_shop_order(self, order) -> list[str]:
        to = order.shop.whatsapp_number
        sid = self.settings.twilio_content_sid_shop
        if sid:
            return [self._create(to, content_sid=sid, variables=shop_template_variables(order))]
        return [self._create(to, body=f"{shop_order_text(order)} {SHOP_KEYWORD_FOOTER}")]
