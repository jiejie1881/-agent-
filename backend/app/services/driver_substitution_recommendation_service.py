from app.services.driver_leave_service import DriverLeaveService
from app.domain.exceptions import NotFoundError
from app.domain.enums import DeliveryDemandStatus


class DriverSubstitutionRecommendationService:
    """Read-only, explainable ranking using actual published task workload."""
    def __init__(self, session):
        self.workflow = DriverLeaveService(session)

    def recommend(self, day, period, vehicle_id):
        vehicle = self.workflow.scheduling.repository.lock_vehicle(vehicle_id, for_update=False)
        if vehicle is None:
            raise NotFoundError("车辆不存在")
        task_locked = any(d.delivery_demand.status in {DeliveryDemandStatus.DELIVERING, DeliveryDemandStatus.COMPLETED} for o in self.workflow.scheduling.repository.orders(day, period, vehicle_id, for_update=False) for d in o.details)
        candidates, rejected = [], []
        for driver in self.workflow.scheduling.repository.drivers():
            reason = self.workflow.candidate_reason(day, period, driver.id, vehicle_id)
            if vehicle and driver.id == vehicle.driver_user_id:
                reason = "常驻司机本人不属于代班候选"
            if task_locked:
                reason = "目标车辆存在配送中或已完成任务，不能普通代班"
            row = {"driver_id": driver.id, "name": driver.display_name or driver.username}
            if reason:
                rejected.append({**row, "reason": reason})
                continue
            workload = len(self.workflow.repository.driver_orders(driver.id, day, day))
            candidates.append({**row, "daily_task_count": workload, "reasons": ["目标时段无其他车辆任务", f"当日已发布任务 {workload} 趟"], "validated_constraints": ["DRIVER/启用", "出勤", "请假", "排班", "已发布任务", "常驻车辆不失去司机"]})
        candidates.sort(key=lambda c: (c['daily_task_count'], c['driver_id']))
        for rank, row in enumerate(candidates, 1):
            row['rank'] = rank
        return {"candidates": candidates, "rejected": rejected, "qualification_notice": "当前未建模驾驶证/准驾资质，未使用虚构资质或车型熟悉度评分"}
