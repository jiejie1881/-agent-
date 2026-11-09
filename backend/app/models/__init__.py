from app.models.agent_conversation import (
    AgentConversation,
    AgentConversationMessage,
)
from app.models.agent_dispatch_acceptance import (
    AgentDispatchOperation,
    AgentDispatchPlanSource,
    DispatchDateGuard,
)
from app.models.agent_pending_action import AgentPendingAction
from app.models.audit_log import AuditLog
from app.models.knowledge import (  # noqa: F401 - metadata registration
    KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeJob,
    KnowledgeIndexVersion, KnowledgeChunkRecord, KnowledgeEvaluationRun,
)
from app.models.cargo_category import CargoCategory
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import (
    DeliveryProof,
    DeliveryProofReview,
    DispatchOrder,
    DispatchOrderDetail,
    DispatchPlan,
    DispatchPlanUnassignedDemand,
)
from app.models.driver_scheduling import (
    DriverAttendance,
    DriverAttendanceRule,
    DriverLeave,
    DriverSchedule,
    DriverSubstitution,
)
from app.models.route import Route, RouteTerrainConfig
from app.models.store import Store, StoreRoute
from app.models.terrain import Terrain
from app.models.user import User
from app.models.vehicle import (
    Vehicle,
    VehicleType,
    VehicleTypeCargoCapability,
    VehicleTypeTerrainPermission,
)
from app.models.vehicle_attendance import VehicleAttendance

__all__ = [
    "AgentConversation",
    "AgentConversationMessage",
    "AgentDispatchOperation",
    "AgentDispatchPlanSource",
    "AgentPendingAction",
    "AuditLog",
    "BusinessImport",
    "CargoCategory",
    "DeliveryDemand",
    "DeliveryProof",
    "DeliveryProofReview",
    "DemandBatchReceipt",
    "DispatchDateGuard",
    "DispatchOrder",
    "DispatchOrderDetail",
    "DispatchPlan",
    "DispatchPlanUnassignedDemand",
    "DispatchQualityReport",
    "DriverAttendance",
    "DriverAttendanceRule",
    "DriverLeave",
    "DriverOperationReceipt",
    "DriverSchedule",
    "DriverSubstitution",
    "ExceptionCase",
    "ExceptionCaseEvent",
    "Route",
    "RouteTerrainConfig",
    "Store",
    "StoreRoute",
    "Terrain",
    "User",
    "Vehicle",
    "VehicleAttendance",
    "VehicleType",
    "VehicleTypeCargoCapability",
    "VehicleTypeTerrainPermission",
]
from app.models.ai_operations import DemandBatchReceipt, DispatchQualityReport
from app.models.business_operations import (
    BusinessImport,
    ExceptionCase,
    ExceptionCaseEvent,
)
from app.models.driver_operation import DriverOperationReceipt
from app.models.agent_memory import (  # noqa: F401 - metadata registration
    AgentMemory,
    AgentMemoryAudit,
    AgentMemoryOutbox,
    AgentMemoryVersion,
    AgentSessionSummary,
    AgentUserMemory,
)
