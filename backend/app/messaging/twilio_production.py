"""Production WhatsApp sender: business-initiated messages must use approved Content Templates."""
from .base import MessagingError, owner_template_variables, shop_template_variables
from .twilio_common import TwilioMessenger


class TwilioProductionMessenger(TwilioMessenger):
    mode = "twilio_production"

    def _template(self, sid: str, name: str) -> str:
        if not sid:
            raise MessagingError(f"{name} is not set; an approved WhatsApp template is required in production")
        return sid

    def send_owner_list(self, order) -> list[str]:
        sid = self._template(self.settings.twilio_content_sid_owner, "TWILIO_CONTENT_SID_OWNER")
        return [self._create(order.owner.whatsapp_number, content_sid=sid,
                             variables=owner_template_variables(order))]

    def send_shop_order(self, order) -> list[str]:
        sid = self._template(self.settings.twilio_content_sid_shop, "TWILIO_CONTENT_SID_SHOP")
        return [self._create(order.shop.whatsapp_number, content_sid=sid, variables=shop_template_variables(order))]

    # send_text (confirmations) is free-form: it is only used right after the owner has replied,
    # inside WhatsApp's 24-hour customer-service window.
