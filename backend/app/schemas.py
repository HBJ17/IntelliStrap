from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EventType

DEVICE_ID_PATTERN = r"^sb-[0-9A-Z]{12}$"
Finite = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]


# --- device protocol -------------------------------------------------------

class RegisterRequest(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    provision_secret: str = Field(max_length=200)


class RegisterResponse(BaseModel):
    device_token: str
    claim_code: str | None


class DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EventType
    payload: dict = Field(default_factory=dict)


class StateChangePayload(BaseModel):
    state: Literal["OK", "LOW"]
    gap: Finite | None = None
    baseline: Finite | None = None


class RecalibrationPayload(BaseModel):
    baseline: Finite


class DriftPayload(BaseModel):
    baseline: Finite


class HeartbeatPayload(BaseModel):
    gap: Finite | None = None
    baseline: Finite | None = None
    rssi: int | None = Field(default=None, ge=-127, le=0)
    uptime_s: int | None = Field(default=None, ge=0)


PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.state_change: StateChangePayload,
    EventType.recalibration: RecalibrationPayload,
    EventType.baseline_drift: DriftPayload,
    EventType.heartbeat: HeartbeatPayload,
}


class DeviceEventResponse(BaseModel):
    ok: bool = True
    stored: bool
    commands: list[str]


class CommandsResponse(BaseModel):
    commands: list[str]


# --- dashboard -------------------------------------------------------------

E164 = r"^(\+[1-9]\d{6,14})?$"  # empty string = not set yet


class LoginRequest(BaseModel):
    password: str = Field(max_length=200)


class ClaimRequest(BaseModel):
    claim_code: str = Field(min_length=6, max_length=6)
    display_name: str = Field(min_length=1, max_length=80)
    item_id: int | None = None
    # Free-text contents label; matched to the catalog by name, or added to it.
    label: str | None = Field(default=None, max_length=80)
    price_inr: int | None = Field(default=None, ge=0, le=1_000_000)  # sets the label's catalog price


class StrapPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    item_id: int | None = None
    label: str | None = Field(default=None, max_length=80)
    price_inr: int | None = Field(default=None, ge=0, le=1_000_000)


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="", max_length=20)
    pack_size: str = Field(default="", max_length=40)
    price_inr: int | None = Field(default=None, ge=0, le=1_000_000)


class OwnerSettings(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    whatsapp_number: str | None = Field(default=None, pattern=E164)
    list_threshold_inr: int | None = Field(default=None, ge=1, le=1_000_000)


class ShopSettings(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    whatsapp_number: str | None = Field(default=None, pattern=E164)
    opted_in: bool | None = None


class GlobalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hold_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    reminder_hours: int | None = Field(default=None, ge=1, le=24 * 7)
    expiry_days: int | None = Field(default=None, ge=1, le=60)
    offline_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    event_retention_days: int | None = Field(default=None, ge=1, le=3650)
    drift_throttle_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    refill_reminder_days: int | None = Field(default=None, ge=1, le=60)
    fill_gap_full: int | None = Field(default=None, ge=1, le=100_000)


class SettingsUpdate(BaseModel):
    owner: OwnerSettings | None = None
    shop: ShopSettings | None = None
    global_: GlobalSettings | None = Field(default=None, alias="global")


class ListAdd(BaseModel):
    strap_id: str | None = Field(default=None, max_length=32)
    item_id: int | None = None

    @model_validator(mode="after")
    def _one_of(self):
        if (self.strap_id is None) == (self.item_id is None):
            raise ValueError("give exactly one of strap_id or item_id")
        return self


class SimReply(BaseModel):
    order_id: int
    action: Literal["order", "not_now"]


class SimEvent(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    type: EventType
    payload: dict = Field(default_factory=dict)
