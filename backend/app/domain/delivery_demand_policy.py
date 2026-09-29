from app.domain.enums import DeliveryDemandStatus


def can_edit_delivery_demand_core_fields(
    status: DeliveryDemandStatus,
) -> bool:
    return status == DeliveryDemandStatus.PENDING
