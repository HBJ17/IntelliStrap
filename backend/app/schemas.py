from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
