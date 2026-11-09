"""Shadow-only transport contracts; statuses are not DispatchPlan states."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field
from app.domain.enums import DispatchPlanStatus

from app.agent.model_types import AgentNetworkEvent, AgentTokenUsage
from app.schemas.dispatch_candidate import (
    CandidateValidationResult,
    DispatchCandidate,
    PlanningModel,
)


class ShadowDispatchRequest(PlanningModel):
    delivery_date: date
    compare_greedy: bool = False
    authorize_external: bool = False
    expected_snapshot_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ShadowTripMetric(PlanningModel):
    vehicle_id: int
    trip_no: int
    period: str
    load: Decimal
    capacity: Decimal
    utilization: Decimal | None


class ShadowMetrics(PlanningModel):
    total_demands: int = 0
    assigned_count: int = 0
    unassigned_count: int = 0
    used_vehicles: int = 0
    trips: tuple[ShadowTripMetric, ...] = ()


class ShadowAttempt(PlanningModel):
    generation: int
    candidate: DispatchCandidate | None
    validation: CandidateValidationResult


class ShadowComparison(PlanningModel):
    status: Literal["PASS", "BLOCKED"]
    metrics: ShadowMetrics | None = None
    validation: CandidateValidationResult | None = None
    elapsed_ms: float = 0
    error_code: str | None = None


class ShadowNodeTiming(PlanningModel):
    node: str
    elapsed_ms: float
    status: Literal["OK", "ERROR", "CANCELLED"]


class ShadowModelCall(PlanningModel):
    generation: int
    elapsed_ms: float
    status: str
    timeout_phase: str | None = None
    token_usage: AgentTokenUsage | None = None
    reserved_tokens: int
    network_events: tuple[AgentNetworkEvent, ...] = ()


class ShadowDispatchResult(PlanningModel):
    run_id: str
    acceptance_receipt: str | None = None
    status: Literal["SUCCESS", "REJECTED", "BLOCKED"]
    reason_code: str
    message: str
    snapshot_version: str | None = None
    stale_context: bool = False
    freshness_checked: bool = False
    candidate: DispatchCandidate | None = None
    validation: CandidateValidationResult | None = None
    attempts: tuple[ShadowAttempt, ...] = ()
    metrics: ShadowMetrics = Field(default_factory=ShadowMetrics)
    generation_count: int = 0
    validation_count: int = 0
    revision_count: int = 0
    elapsed_ms: float = 0
    token_usage: AgentTokenUsage | None = None
    token_usage_status: Literal["UNKNOWN", "PARTIAL", "PROVIDER_REPORTED"] = "UNKNOWN"
    reserved_tokens: int = 0
    estimated_cost: Decimal | None = None
    cost_currency: str | None = None
    cost_status: Literal["UNKNOWN", "PARTIAL", "ESTIMATED"] = "UNKNOWN"
    node_timings: tuple[ShadowNodeTiming, ...] = ()
    model_calls: tuple[ShadowModelCall, ...] = ()
    comparison: ShadowComparison | None = None


class AgentDraftAcceptanceRequest(PlanningModel):
    candidate: DispatchCandidate
    acceptance_receipt: str = Field(min_length=20, max_length=2048)
    confirmed: bool


class AgentDraftAcceptanceResponse(PlanningModel):
    plan_id: int
    delivery_date: date
    version: int
    status: DispatchPlanStatus
