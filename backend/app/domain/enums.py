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


class VehicleTypeCode(str, Enum):
    FOUR_METER = "FOUR_METER"
    BIG_VAN = "BIG_VAN"
    SMALL_VAN = "SMALL_VAN"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    DISPATCHER = "DISPATCHER"
    VIEWER = "VIEWER"


class AgentConversationMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
