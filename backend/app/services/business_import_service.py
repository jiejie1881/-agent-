"""Human-confirmed imports. Preview never writes master data; confirmation is atomic."""
import csv
import hashlib
import io
import zipfile
from defusedxml.ElementTree import fromstring as safe_xml
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import UserRole, DeliveryDemandStatus
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.models.business_operations import BusinessImport
from app.models.store import Store, StoreRoute
from app.models.route import Route
from app.models.vehicle import Vehicle, VehicleType
from app.models.user import User
from app.models.delivery_demand import DeliveryDemand
from app.schemas.store import StoreCreate
from app.schemas.route import RouteCreate
from app.schemas.vehicle import VehicleCreate
from app.schemas.delivery_demand import DeliveryDemandCreate
from app.services.store_service import StoreService
from app.services.route_service import RouteService
from app.services.vehicle_service import VehicleService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.audit_log_service import AuditLogService

HEADERS = {
    "stores": ("code", "name", "address", "contact_name", "contact_phone", "delivery_region", "longitude", "latitude", "route_codes"),
    "routes": ("code", "name", "start_address", "end_address", "geographic_notes", "distance_km", "duration_minutes", "route_data_source"),
    "vehicles": ("code", "plate_number", "vehicle_type_code", "driver_username", "organization", "rated_load", "daily_trip_limit", "operating_status", "allowed_route_codes"),
    "demands": ("date", "store_code", "period", "quantity", "priority"),
}
# Chinese files are normalized to the existing protocol; stored keys/enums stay unchanged.
CHINESE_HEADERS = {
    "stores": ("门店编码", "门店名称", "地址", "联系人", "联系电话", "所属区域", "经度", "纬度", "关联线路编码"),
    "routes": ("线路编码", "线路名称", "起点地址", "终点地址", "道路地形说明", "距离公里", "预计分钟", "资料来源"),
    "vehicles": ("车辆编码", "车牌或验收标识", "车型内部编码", "司机账号", "所属组织", "额定载重公斤", "每日趟次上限", "运行状态", "允许线路编码"),
    "demands": ("配送日期", "门店编码", "配送时段", "需求重量公斤", "优先级"),
}
IMPORT_VALUES = {
    "period": {"上午": "MORNING", "下午": "AFTERNOON"},
    "priority": {"普通": "NORMAL", "高": "HIGH", "加急": "URGENT"},
    "operating_status": {"正常": "ACTIVE", "维修": "MAINTENANCE", "退役": "RETIRED"},
}

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1000


def check_kind(kind: str) -> None:
    if kind not in HEADERS:
        raise BusinessError("不支持的导入类型", 422)


def template(kind: str, file_format: str, language: str = "en") -> bytes:
    check_kind(kind)
    if language not in {"en", "zh"}:
        raise BusinessError("模板语言仅支持中文或英文", 422)
    headers = CHINESE_HEADERS[kind] if language == "zh" else HEADERS[kind]
    if file_format == "csv":
        output = io.StringIO(newline="")
        csv.writer(output).writerow(headers)
        return output.getvalue().encode("utf-8-sig")
    if file_format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(headers)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        return output.getvalue()
    raise BusinessError("仅支持 csv 或 xlsx", 422)


def parse_file(kind: str, filename: str, content: bytes) -> list[dict]:
    check_kind(kind)
    if not content or len(content) > MAX_BYTES:
        raise BusinessError("文件不能为空且不得超过 5MB", 422)
    try:
        if filename.lower().endswith(".csv"):
            reader = csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True)
            cells = []
            for row in reader:
                cells.append(row)
                if len(cells) > MAX_ROWS + 1:
                    raise BusinessError("单次最多导入 1000 行", 422)
        elif filename.lower().endswith(".xlsx"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.infolist()) > 1000:
                    raise BusinessError("工作簿组件数量超限", 422)
                if sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                    raise BusinessError("工作簿解压大小超限", 422)
                if any("externallinks/" in item.filename.lower() for item in archive.infolist()):
                    raise BusinessError("不允许包含外部链接", 422)
                for item in archive.infolist():
                    if item.filename.lower().endswith(('.xml','.rels')):
                        safe_xml(archive.read(item),forbid_dtd=True,forbid_entities=True,forbid_external=True)
            from openpyxl import load_workbook
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
            try:
                if len(workbook.worksheets) != 1:
                    raise BusinessError("仅允许一个工作表", 422)
                cells = []
                for row in workbook.active.iter_rows():
                    if any(cell.data_type == "f" for cell in row):
                        raise BusinessError("导入文件不得包含公式", 422)
                    cells.append([cell.value for cell in row])
                    if len(cells) > MAX_ROWS + 1:
                        raise BusinessError("单次最多导入 1000 行", 422)
            finally:
                workbook.close()
        else:
            raise BusinessError("仅支持 UTF-8 CSV 或 XLSX 文件", 422)
    except (ValueError, UnicodeError, csv.Error, zipfile.BadZipFile, KeyError, OSError, DefusedXmlException, ParseError, RuntimeError, NotImplementedError) as exc:
        raise BusinessError("文件格式无效，请使用空白模板", 422) from exc
    if not cells or tuple(str(cell or "").strip() for cell in cells[0]) not in {HEADERS[kind], CHINESE_HEADERS[kind]}:
        raise BusinessError("列名或顺序与模板不一致", 422)
    rows = []
    for row in cells[1:]:
        if not any(cell is not None and str(cell).strip() for cell in row):
            continue
        if len(row) != len(HEADERS[kind]):
            raise BusinessError("数据列数量与模板不一致", 422)
        normalized = {key: str(value).strip() if value is not None else "" for key, value in zip(HEADERS[kind], row)}
        for key, values in IMPORT_VALUES.items():
            if key in normalized:
                normalized[key] = values.get(normalized[key], normalized[key])
        rows.append(normalized)
    if not rows:
        raise BusinessError("模板中没有业务数据", 422)
    return rows


class BusinessImportService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def authorize(kind: str, actor: User):
        check_kind(kind)
        permitted = {UserRole.ADMIN, UserRole.DISPATCHER} if kind == "demands" else {UserRole.ADMIN}
        if actor.role not in permitted or not actor.is_active:
            raise PermissionDeniedError()

    def _lookup(self, model, field: str, value: str):
        record = self.session.scalar(select(model).where(getattr(model, field) == value).with_for_update())
        if record is None or not record.is_active:
            raise BusinessError(f"{field}={value} 对应的启用记录不存在", 422)
        return record

    def _routes(self, value: str) -> list[int]:
        codes = value.split("|") if value else []
        if len(codes) != len(set(codes)):
            raise BusinessError("线路编码重复", 422)
        return [self._lookup(Route, "code", code).id for code in codes]

    def _prepare(self, kind: str, row: dict):
        data = {key: value for key, value in row.items() if value != ""}
        if kind == "stores":
            routes = self._routes(data.pop("route_codes", ""))
            schema = StoreCreate(**data)
            model, unique = Store, ("code", "name")
            extras = routes
        elif kind == "routes":
            schema = RouteCreate(**data)
            RouteService._validate_source(schema.model_dump())
            model, unique, extras = Route, ("code", "name"), None
        elif kind == "vehicles":
            vehicle_type = self._lookup(VehicleType, "code", data.pop("vehicle_type_code", ""))
            driver_name = data.pop("driver_username", "")
            driver = self._lookup(User, "username", driver_name) if driver_name else None
            if driver and driver.role != UserRole.DRIVER:
                raise BusinessError("车辆只能绑定司机账号", 422)
            allowed = data.pop("allowed_route_codes", "")
            schema = VehicleCreate(**data, vehicle_type_id=vehicle_type.id,
                driver_user_id=driver.id if driver else None,
                allowed_route_ids=self._routes(allowed) if allowed else None)
            VehicleService(self.session)._validate_operating_fields(schema.model_dump(), vehicle_type.id)
            model, unique, extras = Vehicle, ("code", "plate_number"), None
        else:
            store = self._lookup(Store, "code", data.pop("store_code", ""))
            schema = DeliveryDemandCreate(**data, store_id=store.id)
            if self.session.scalar(select(DeliveryDemand.id).where(DeliveryDemand.date == schema.date,
                DeliveryDemand.store_id == store.id, DeliveryDemand.period == schema.period)):
                raise ConflictError("该门店当天同一时段已有需求")
            return schema, None, (schema.date.isoformat(), store.id, schema.period.value)
        keys = []
        for field in unique:
            value = getattr(schema, field)
            if self.session.scalar(select(model.id).where(getattr(model, field) == value)):
                raise ConflictError(f"{field}={value} 已存在")
            keys.append((field, value.casefold() if isinstance(value, str) else value))
        return schema, extras, tuple(keys)

    def validate(self, kind: str, rows: list[dict]):
        prepared, errors, seen = [], [], set()
        for number, row in enumerate(rows, start=2):
            try:
                schema, extras, key = self._prepare(kind, row)
                keys = [key] if kind == "demands" else list(key)
                if any(item in seen for item in keys):
                    raise ConflictError("文件内业务键重复")
                seen.update(keys)
                prepared.append((schema, extras))
            except (BusinessError, ValidationError) as exc:
                message = exc.message if isinstance(exc, BusinessError) else "; ".join(f"{'.'.join(map(str,e['loc']))}: {e['msg']}" for e in exc.errors())
                errors.append({"row": number, "message": message})
        return prepared, errors

    def preview(self, kind: str, filename: str, content: bytes, actor: User):
        self.authorize(kind, actor)
        digest = hashlib.sha256(content).hexdigest()
        existing = self.session.scalar(select(BusinessImport).where(BusinessImport.actor_id == actor.id,
            BusinessImport.kind == kind, BusinessImport.file_sha256 == digest))
        if existing:
            if existing.status != "IMPORTED":
                _, errors = self.validate(kind, existing.rows)
                existing.status = "INVALID" if errors else "PREVIEW"
                existing.errors = errors
                existing.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
                AuditLogService(self.session).add(actor, "BUSINESS_IMPORT_PREVIEW_REFRESHED", "BusinessImport", existing.id,
                    {"error_count": len(errors)})
                self.session.commit()
            return existing
        rows = parse_file(kind, filename, content)
        _, errors = self.validate(kind, rows)
        batch = BusinessImport(actor_id=actor.id, kind=kind, file_sha256=digest,
            status="INVALID" if errors else "PREVIEW", rows=rows, errors=errors, result_ids=[],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))
        self.session.add(batch)
        try:
            self.session.flush()
            AuditLogService(self.session).add(actor, "BUSINESS_IMPORT_PREVIEWED", "BusinessImport", batch.id,
                {"kind": kind, "row_count": len(rows), "error_count": len(errors), "file_sha256": digest})
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return self.session.scalar(select(BusinessImport).where(BusinessImport.actor_id == actor.id,
                BusinessImport.kind == kind, BusinessImport.file_sha256 == digest))
        return batch

    def get(self, batch_id: int, actor: User, *, lock=False):
        query = select(BusinessImport).where(BusinessImport.id == batch_id, BusinessImport.actor_id == actor.id)
        batch = self.session.scalar(query.with_for_update() if lock else query)
        if batch is None:
            raise NotFoundError("导入批次不存在")
        self.authorize(batch.kind, actor)
        return batch

    def history(self, actor: User, offset: int, limit: int):
        if actor.role not in {UserRole.ADMIN, UserRole.DISPATCHER}:
            raise PermissionDeniedError()
        return self.session.scalars(select(BusinessImport).where(BusinessImport.actor_id == actor.id)
            .order_by(BusinessImport.id.desc()).offset(offset).limit(limit)).all()

    def confirm(self, batch_id: int, actor: User, confirmed: bool):
        if not confirmed:
            raise BusinessError("需要人工确认导入", 422)
        try:
            batch = self.get(batch_id, actor, lock=True)
            if batch.status == "IMPORTED":
                self.session.commit()
                return batch
            if batch.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
                raise ConflictError("预览已过期，请重新上传并核对")
            prepared, errors = self.validate(batch.kind, batch.rows)
            if errors:
                batch.status, batch.errors = "INVALID", errors
                AuditLogService(self.session).add(actor, "BUSINESS_IMPORT_REJECTED", "BusinessImport", batch.id,
                    {"error_count": len(errors)})
                self.session.commit()
                raise BusinessError("重新校验失败，请查看该批次错误记录", 409, "IMPORT_REVALIDATION_FAILED")
            ids = []
            for schema, extras in prepared:
                if batch.kind == "stores":
                    record = StoreService(self.session).create(schema, commit=False)
                    for route_id in extras:
                        self.session.add(StoreRoute(store_id=record.id, route_id=route_id))
                elif batch.kind == "routes":
                    record = RouteService(self.session).create(schema, commit=False)
                elif batch.kind == "vehicles":
                    record = VehicleService(self.session).create(schema, actor, commit=False)
                else:
                    record = DeliveryDemandService(self.session).create(schema, actor, commit=False)
                self.session.flush()
                ids.append(record.id)
            batch.status, batch.result_ids, batch.errors = "IMPORTED", ids, []
            AuditLogService(self.session).add(actor, "BUSINESS_IMPORT_CONFIRMED", "BusinessImport", batch.id,
                {"kind": batch.kind, "result_ids": ids, "row_count": len(ids)})
            self.session.commit()
            return batch
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("并发数据冲突，整批导入已回滚，请刷新预览") from exc
        except Exception:
            self.session.rollback()
            raise
