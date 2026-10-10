from enum import Enum


class DeliveryPeriod(str, Enum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


class DispatchPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class DeliveryDemandStatus(str, Enum):
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryPriority(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class VehicleTypeCode(str, Enum):
    FOUR_METER = "FOUR_METER"
    BIG_VAN = "BIG_VAN"
    SMALL_VAN = "SMALL_VAN"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    DISPATCHER = "DISPATCHER"
    VIEWER = "VIEWER"
    DRIVER = "DRIVER"


class DriverTaskStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    MIXED = "MIXED"


class DeliveryStopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    SIGNED = "SIGNED"
    FAILED = "FAILED"


class DeliveryProofReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeliveryFailureReason(str, Enum):
    STORE_CLOSED = "STORE_CLOSED"
    REJECTED = "REJECTED"
    ADDRESS_ERROR = "ADDRESS_ERROR"
    CARGO_DAMAGED = "CARGO_DAMAGED"
    OTHER = "OTHER"


class AgentConversationMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class AgentPendingActionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
