from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class PredictRequest(BaseModel):
    current_stop: str = Field(..., min_length=2, max_length=120, examples=["Silk Board"])
    destination: str = Field(..., min_length=2, max_length=120, examples=["Marathahalli"])
    limit: int = Field(50, ge=1, le=100)

    @field_validator("current_stop", "destination")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if any(char in cleaned for char in "<>{}[]\\"):
            raise ValueError("Input contains unsupported characters.")
        return cleaned


class TrainRequest(BaseModel):
    force: bool = False


class AutocompleteResponse(BaseModel):
    items: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    version: str
    model_ready: bool
    dataset_rows: int


class VerifyPassRequest(BaseModel):
    pass_id: str = Field(..., min_length=3, max_length=50, examples=["BMTC-PASS-88492"])
    conductor_id: str = Field("CND-402", max_length=50)
    route_id: str = Field("500-D", max_length=50)
    offline_mode: bool = False


class DeployBusRequest(BaseModel):
    """A depot manager marking a dispatch recommendation as reviewed.

    Previously this defaulted depot_name to a fictional "Agara Depot" and
    standby_buses_to_deploy to an invented count, which deploy_bus() then
    echoed back as a fabricated real-world dispatch confirmation. There is
    no real depot/fleet system connected to this app, so this only
    records what's actually true: a route was reviewed, with an optional
    free-text note from the real depot manager doing the reviewing.
    """
    route_number: str = Field(..., min_length=1, max_length=50, examples=["500-D"])
    note: str | None = Field(None, max_length=300)


class BlockingDecisionRequest(BaseModel):
    """A controller accepting or rejecting one proposed re-block.

    Recorded, not executed. Nothing in this app dispatches a bus, and the
    blocking panel is deliberately advisory: a transport corporation will not
    hand vehicle assignment to an algorithm, and a tool that proposes while a
    human decides is the version that can actually be deployed.
    """
    depot: str = Field(..., min_length=1, max_length=120)
    route_number: str = Field(..., min_length=1, max_length=50, examples=["375-D"])
    decision: str = Field(..., pattern="^(approve|reject)$")
    buses_released: int = Field(0, ge=0, le=500)
    note: str | None = Field(None, max_length=300)


class BlockingScenarioRequest(BaseModel):
    """A "what if" against the published timetable.

    Times are HH:MM on the service day; hours >= 24 are allowed and mean the
    small hours of the next morning, matching how the dataset itself encodes
    post-midnight departures.
    """
    route_number: str = Field(..., min_length=1, max_length=50, examples=["375-D"])
    action: str = Field(..., pattern="^(set_headway|add_trips|remove_trips)$")
    start_time: str = Field(..., pattern=r"^\d{1,2}:\d{2}$", examples=["08:00"])
    end_time: str = Field(..., pattern=r"^\d{1,2}:\d{2}$", examples=["10:00"])
    headway_minutes: int | None = Field(None, ge=1, le=240)
    trips: int | None = Field(None, ge=1, le=500)
    direction_id: int | None = Field(None, ge=0, le=1)


class CrewScenarioRequest(BaseModel):
    """A "what if" against the crew agreement rather than the timetable.

    Every field is optional and falls back to the CrewParameters default, so a
    caller can vary one rule at a time -- which is how a crew agreement is
    actually negotiated. Bounds here are sanity limits, not policy: a 20-hour
    working day is refused because it is certainly a typo, not because some
    agreement forbids it.
    """
    depot: str = Field("", max_length=120, description="Depot label; omit for the whole network")
    sign_on_minutes: int | None = Field(None, ge=0, le=120)
    sign_off_minutes: int | None = Field(None, ge=0, le=120)
    max_continuous_driving_minutes: int | None = Field(None, ge=60, le=720)
    min_break_minutes: int | None = Field(None, ge=5, le=240)
    max_working_minutes: int | None = Field(None, ge=120, le=720)
    max_spreadover_minutes: int | None = Field(None, ge=120, le=1080)
    min_relief_gap_minutes: int | None = Field(None, ge=0, le=120)
    allow_split_duties: bool | None = None


class CrowdReportRequest(BaseModel):
    route_number: str = Field(..., min_length=1, max_length=50, examples=["500-D"])
    crowding_level: str = Field(..., pattern="^(low|medium|high|full)$")
    bus_number: str | None = Field(None, max_length=50)
    stop_name: str | None = Field(None, max_length=150)


class ServiceAlertRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=3, max_length=1000)
    severity: str = Field(..., pattern="^(info|moderate|severe)$")
    affected_routes: list[str] = Field(default_factory=list, max_length=50)
    affected_stops: list[str] = Field(default_factory=list, max_length=50)


class TrustedContact(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=3, max_length=20)


class SaveTrustedContactsRequest(BaseModel):
    contacts: list[TrustedContact] = Field(..., max_length=5)


class CreateTripShareRequest(BaseModel):
    current_stop: str = Field(..., min_length=1, max_length=150)
    destination: str = Field(..., min_length=1, max_length=150)
    bus_number: str | None = Field(None, max_length=50)
    matched_current_stop: str | None = Field(None, max_length=150)
    matched_destination: str | None = Field(None, max_length=150)