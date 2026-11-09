"""Exercise real FastAPI routes + MySQL in the disposable verification schema.

Never run against the presentation schema. Real AI calls are opt-in, not mocked.
"""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import base64
from datetime import date, timedelta
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.infrastructure.database.session import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.models.user import User
from app.models.vehicle import Vehicle
from tests.legacy_support.seed_compact_demo import AI_DEMANDS, demand_input, validate_target


def ai_texts(day):
    return [
        f"请预览{day}下午学士工业园店的配送需求，90公斤，普通优先级；等待管理员确认，不要直接保存。",
        f"请预览{day}的三条配送需求：下午含浦综合店60公斤，普通优先级；下午梅溪湖中央店40公斤，普通优先级；下午望月湖社区店30公斤，普通优先级。等待管理员确认，不要直接保存。",
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--real-ai", action="store_true")
    parser.add_argument("--manual-fixtures", action="store_true", help="Create the 4 reserved inputs through explicit manual batch confirmation; not AI verification")
    args = parser.parse_args()
    settings = get_settings()
    validate_target(settings.database_url, True, "logistics_dispatch_demo_verify")
    password = os.environ.get("DEMO_SEED_PASSWORD", "")
    report = {"database": "logistics_dispatch_demo_verify", "date": str(args.date), "checks": [], "ai": [], "agent": []}
    if len(password) < 8:
        raise SystemExit("请设置DEMO_SEED_PASSWORD")
    with SessionLocal() as session:
        if session.scalar(select(DispatchPlan.id).where(DispatchPlan.delivery_date == args.date)):
            raise SystemExit("验证日期已有方案，拒绝重复推进业务；选择新的验证日期并Seed")
        users = {u.username: u.id for u in session.scalars(select(User))}
        vehicles = {v.code: v.id for v in session.scalars(select(Vehicle))}
    with TestClient(app) as client:
        def request(method, path, actor="demo_admin", expected=200, **kwargs):
            headers = {"Authorization": "Bearer " + tokens[actor]}
            response = client.request(method, path, headers=headers, **kwargs)
            if response.status_code != expected:
                raise AssertionError(f"{method} {path}: {response.status_code}: {response.text[:1000]}")
            return response.json() if response.content else None

        tokens = {}
        for account in users:
            endpoint = "/api/driver/auth/login" if account.startswith("driver") else "/api/v1/auth/login"
            response = client.post(endpoint, json={"username": account, "password": password})
            assert response.status_code == 200, account
            tokens[account] = response.json()["access_token"]
        report["checks"].append("所有7个演示账号真实登录PASS")
        for account in (f"driver{i:02}" for i in range(1, 6)):
            request("GET", "/api/driver/profile", account)
            today_tasks = request("GET", "/api/driver/tasks/today", account)
            assert all(t["delivery_date"] == date.today().isoformat() for t in today_tasks)
        request("GET", "/api/v1/driver-management/leave-requests", "driver01", expected=403)
        report["checks"].append("DRIVER资料/今日任务接口及后台权限隔离PASS")
        leave = request("POST", "/api/driver/leaves", "driver02", json={"start_date": str(args.date), "end_date": str(args.date), "period": "MORNING", "reason": "精简Demo上午请假", "leave_type": "OTHER"})
        request("POST", f"/api/v1/driver-management/leave-requests/{leave['id']}/review", json={"decision": "APPROVED", "review_remark": "Demo管理员正式审批"})
        unavailable = request("GET", f"/api/v1/driver-management/effective-drivers?day={args.date}&period=MORNING")
        assert next(v for v in unavailable if v["vehicle_id"] == vehicles["VH-002"])["code"] == "DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE"
        v1 = request("POST", "/api/v1/auto-dispatch", json={"date": str(args.date)})
        assert v1["version"] == 1 and len(v1["unassigned_demands"]) == 1
        assert not any(t["period"] == "MORNING" and t["vehicle"]["id"] == vehicles["VH-002"] for t in v1["trips"])
        assert "DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE" in str(v1["unassigned_demands"])
        report["leave_v1"] = {"plan": v1["plan_id"], "unassigned": v1["unassigned_demands"]}
        candidates = request("GET", f"/api/v1/driver-management/substitution-candidates?day={args.date}&period=MORNING&vehicle_id={vehicles['VH-002']}")
        report["substitute_candidates"] = candidates
        proposal = request("POST", "/api/v1/driver-management/substitutions", json={"leave_request_id": leave["id"], "vehicle_id": vehicles["VH-002"], "substitute_driver_id": users["driver05"], "date": str(args.date), "period": "MORNING"})
        assert proposal["status"] == "PENDING"
        request("POST", f"/api/v1/driver-management/substitutions/{proposal['id']}/confirm")
        v2 = request("POST", "/api/v1/auto-dispatch", json={"date": str(args.date)})
        assert v2["version"] == 2 and not v2["unassigned_demands"]
        assert sum(len(t["stores"]) for t in v2["trips"]) == 8
        report["checks"].append("请假/正式审批/候选/待确认/确认代班/V1→V2完整重算PASS")
        # Failure must remain visible; manual confirmation does not count as AI success.
        ai_success = 0
        for text, expected_count in zip(ai_texts(args.date), (1, 3)):
            entry = {"input": text, "status": "NOT RUN"}
            if args.real_ai:
                parsed = client.post("/api/v1/delivery-demands/parse-text", headers={"Authorization": "Bearer " + tokens["demo_admin"]}, json={"text": text})
                if parsed.status_code == 200:
                    value = parsed.json()
                    entry["preview"] = value
                    rows = value["items"]
                    if len(rows) == expected_count and all(not row["missing_fields"] for row in rows):
                        confirmed = request("POST", "/api/v1/delivery-demands/confirm-batch", json={"request_key": str(uuid4()), "confirmed": True, "items": [row["data"] for row in rows]})
                        entry.update(status="PASS", confirmed=confirmed)
                        ai_success += expected_count
                    else:
                        entry.update(status="FAIL", reason="真实AI预览条数或必需字段不符合预期；不自动补字段")
                else:
                    entry.update(status="FAIL", http_status=parsed.status_code, error=parsed.json())
            report["ai"].append(entry)
        if args.manual_fixtures and not args.real_ai:
            from app.models.store import Store
            with SessionLocal() as session:
                stores = list(session.scalars(select(Store).order_by(Store.code)))
                items = [demand_input(args.date, row, stores).model_dump(mode="json") for row in AI_DEMANDS]
            report["manual_batch"] = request("POST", "/api/v1/delivery-demands/confirm-batch", json={"request_key": str(uuid4()), "confirmed": True, "items": items})
            report["checks"].append("4条预留需求通过管理员正式批量确认接口创建PASS；未验证真实AI文本解析")
            ai_success = 4  # allocated scope only; AI entries remain NOT RUN
        final = request("POST", "/api/v1/auto-dispatch", json={"date": str(args.date)})
        assert not final["unassigned_demands"]
        assert sum(len(t["stores"]) for t in final["trips"]) == 8 + ai_success
        assert len({t["vehicle"]["id"] for t in final["trips"]}) == 4
        report["final_plan"] = final
        plan_id = final["plan_id"]
        published = request("POST", f"/api/v1/dispatch-plans/{plan_id}/publish")
        assert published["status"] == "PUBLISHED"
        report["checks"].append("自动派车所有4台车有任务/未分配0/版本递增/发布前校验/正式发布PASS")
        with SessionLocal() as session:
            plan = session.get(DispatchPlan, plan_id)
            orders = [(o.id, next(name for name, uid in users.items() if uid == o.actual_driver_id), [d.id for d in o.details]) for o in plan.orders]
        proof_url = None
        for index, (order_id, account, stop_ids) in enumerate(orders):
            detail = request("GET", f"/api/driver/tasks/{order_id}", account)
            assert len(detail["stops"]) == len(stop_ids)
            other = "driver02" if account != "driver02" else "driver01"
            request("GET", f"/api/driver/tasks/{order_id}", other, expected=404)
            with SessionLocal() as session:
                audit_before = session.scalar(select(func.count()).select_from(AuditLog))
            request("POST", f"/api/driver/tasks/{order_id}/start", account)
            with SessionLocal() as session:
                audit_started = session.scalar(select(func.count()).select_from(AuditLog))
            assert audit_started > audit_before
            request("POST", f"/api/driver/tasks/{order_id}/complete", account, expected=409)
            with SessionLocal() as session:
                assert session.scalar(select(func.count()).select_from(AuditLog)) == audit_started
            for stop_id in stop_ids:
                stop_path = f"/api/driver/tasks/{order_id}/stops/{stop_id}"
                request("POST", stop_path + "/arrive", account)
                if index == 0:
                    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZAAAAABJRU5ErkJggg==")
                    proof = request("POST", stop_path + "/proofs", account, files={"file": ("demo.png", png, "image/png")})
                    proof_url = proof["url"]
                    assert client.get(proof_url, headers={"Authorization": "Bearer " + tokens[account]}).status_code == 200
                    assert client.get(proof_url).status_code == 401
                if index == len(orders) - 1:
                    request("POST", stop_path + "/fail", account, json={"failure_reason": "STORE_CLOSED", "remark": "受控Demo闭店异常"})
                else:
                    request("POST", stop_path + "/sign", account, json={"receiver_name": "Demo收货员", "remark": "真实接口签收验收"})
            completed = request("POST", f"/api/driver/tasks/{order_id}/complete", account)
            assert completed["status"] == "COMPLETED"
        report["checks"].append("司机实际归属/越权404/未处理禁止完成/到店/回单/签收/异常/整趟完成/失败无成功审计PASS")
        report["proof_url"] = proof_url
        report["history"] = request("GET", f"/api/driver/tasks/history?start_date={args.date}&end_date={args.date}", "driver05")
        assert report["history"]["total"] >= 1
        report["exceptions"] = request("GET", f"/api/v1/daily-exceptions?date={args.date}")
        assert report["exceptions"]["reference_plan"]["id"] == plan_id
        assert report["exceptions"]["failed_stops"]["count"] >= 1
        with SessionLocal() as session:
            vehicle = session.get(Vehicle, vehicles["VH-002"])
            assert vehicle.driver_user_id == users["driver02"]
            from app.services.driver_scheduling_service import DriverSchedulingService
            from app.services.vehicle_attendance_service import VehicleAttendanceService
            from app.schemas.vehicle_attendance import VehicleAttendanceCreate
            from app.schemas.driver_scheduling import ScheduleInput
            scheduling = DriverSchedulingService(session)
            next_day = args.date + timedelta(days=1)
            admin = session.get(User, users["demo_admin"])
            VehicleAttendanceService(session).create(VehicleAttendanceCreate(date=next_day, vehicle_id=vehicle.id, available=True))
            scheduling.assign(ScheduleInput(date=next_day, period="MORNING", vehicle_id=vehicle.id, driver_id=users["driver02"]), admin)
            assert scheduling.resolve(next_day, "MORNING", vehicle.id).id == users["driver02"]
            historical_order = next(o for o in session.get(DispatchPlan, plan_id).orders if o.vehicle_id == vehicle.id and o.period.value == "MORNING")
            assert historical_order.actual_driver_id == users["driver05"]
            report["demand_statuses"] = [(s.value, n) for s, n in session.execute(select(DeliveryDemand.status, func.count()).where(DeliveryDemand.date == args.date).group_by(DeliveryDemand.status))]
            report["audit_count"] = session.scalar(select(func.count()).select_from(AuditLog))
        report["checks"].append("代班历史任务归属/常驻绑定保留/每日异常真实失败记录PASS")
        if args.real_ai:
            for question in (f"请查询{args.date}的配送需求和车辆出勤情况，用真实数据汇总。", "请查询知识库，说明当前派车规则与不支持的特殊运输能力。"):
                response = client.post("/api/v1/agent/chat", headers={"Authorization": "Bearer " + tokens["demo_admin"]}, json={"message": question})
                report["agent"].append({"input": question, "status": "PASS" if response.status_code == 200 else "FAIL", "http_status": response.status_code, "result": response.json()})
    Path("/tmp/compact-demo-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
