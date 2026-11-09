import csv
import io
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, func
from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError
from app.models.store import Store
from app.models.route import Route
from app.models.business_operations import BusinessImport, ExceptionCaseEvent
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.services.auth_service import AuthService
from app.services.business_import_service import BusinessImportService, HEADERS, parse_file, template
from app.services.exception_case_service import ExceptionCaseService

def actor(session, name="import-admin", role=UserRole.ADMIN):
    return AuthService(session).create_user(name, "BusinessPass123!", role)
def content(kind, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEADERS[kind]); writer.writeheader(); writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")

@pytest.mark.parametrize("kind", HEADERS)
def test_templates_blank(kind):
    data = template(kind,"csv")
    assert data.decode('utf-8-sig').strip() == ','.join(HEADERS[kind])
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(template(kind,"xlsx")))
    assert wb.active.max_row == 1
    wb.close()

def test_preview_confirm_idempotency(session):
    admin=actor(session); service=BusinessImportService(session)
    data=content("stores",[{"code":"REAL_STORE_1","name":"业务门店","delivery_region":"北区"}])
    batch=service.preview("stores","stores.csv",data,admin)
    assert batch.status=="PREVIEW" and session.scalar(select(func.count()).select_from(Store))==0
    assert service.preview("stores","stores.csv",data,admin).id==batch.id
    saved=service.confirm(batch.id,admin,True)
    assert saved.status=="IMPORTED" and len(saved.result_ids)==1
    assert service.confirm(batch.id,admin,True).result_ids==saved.result_ids
    assert session.get(Store,saved.result_ids[0]).delivery_region=="北区"
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=="BUSINESS_IMPORT_CONFIRMED"))==1

def test_duplicate_file_rows_and_reference_errors(session):
    admin=actor(session);service=BusinessImportService(session)
    batch=service.preview("stores","s.csv",content("stores",[{"code":"X","name":"店一"},{"code":"X","name":"店二"},{"code":"Y","name":"店三","route_codes":"UNKNOWN"}]),admin)
    assert len(batch.errors)==2 and batch.status=="INVALID"
    with pytest.raises(BusinessError):service.confirm(batch.id,admin,True)
    assert session.scalar(select(func.count()).select_from(Store))==0

def test_confirm_revalidates_and_keeps_error_record(session):
    admin=actor(session);service=BusinessImportService(session)
    batch=service.preview("routes","r.csv",content("routes",[{"code":"R","name":"真实线路"}]),admin)
    session.add(Route(code="R",name="他人新建线路"));session.commit()
    with pytest.raises(BusinessError,match="重新校验失败"): service.confirm(batch.id,admin,True)
    session.expire_all(); assert session.get(BusinessImport,batch.id).status=="INVALID"
    assert session.get(BusinessImport,batch.id).errors

def test_mid_batch_exception_rolls_back(session,monkeypatch):
    from app.services.store_service import StoreService
    admin=actor(session);service=BusinessImportService(session)
    batch=service.preview("stores","s.csv",content("stores",[{"code":"A","name":"一"},{"code":"B","name":"二"}]),admin)
    original=StoreService.create
    def failing(self,data,**kwargs):
        result=original(self,data,**kwargs)
        if data.code=="B":raise RuntimeError("fault injection")
        return result
    monkeypatch.setattr(StoreService,"create",failing)
    with pytest.raises(RuntimeError):service.confirm(batch.id,admin,True)
    assert session.scalar(select(func.count()).select_from(Store))==0
    assert session.get(BusinessImport,batch.id).status=="PREVIEW"
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=="BUSINESS_IMPORT_CONFIRMED"))==0

def test_expiry_ownership_permissions(session):
    admin=actor(session);other=actor(session,"other");driver=actor(session,"driver",UserRole.DRIVER)
    service=BusinessImportService(session)
    batch=service.preview("stores","s.csv",content("stores",[{"code":"A","name":"门店"}]),admin)
    with pytest.raises(BusinessError) as exc:service.get(batch.id,other)
    assert exc.value.status_code==404
    with pytest.raises(BusinessError) as exc:service.preview("stores","s.csv",b"",driver)
    assert exc.value.status_code==403
    batch.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);session.commit()
    with pytest.raises(BusinessError,match="过期"):service.confirm(batch.id,admin,True)

@pytest.mark.parametrize("filename,data",[("file.exe",b"xx"),("s.csv",b"wrong\n"),("s.xlsx",b"notzip"),("s.csv",b"")])
def test_reject_invalid_file(filename,data):
    with pytest.raises(BusinessError):parse_file("stores",filename,data)

def test_reject_formula():
    from openpyxl import Workbook
    wb=Workbook();wb.active.append(HEADERS["stores"]);wb.active.append(["=1+1","名字"])
    data=io.BytesIO();wb.save(data);wb.close()
    with pytest.raises(BusinessError,match="公式"):parse_file("stores","s.xlsx",data.getvalue())

def test_reject_xml_entity_payload():
    import zipfile
    original=template('stores','xlsx');output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(output,'w') as target:
        for item in source.infolist():
            data=source.read(item)
            if item.filename=='xl/workbook.xml':
                data=b'<!DOCTYPE workbook [<!ENTITY attack SYSTEM "file:///etc/passwd">]><workbook>&attack;</workbook>'
            target.writestr(item,data)
    with pytest.raises(BusinessError,match='文件格式无效'):parse_file('stores','s.xlsx',output.getvalue())

def test_reject_malformed_xml():
    import zipfile
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as target:target.writestr('xl/workbook.xml',b'<broken')
    with pytest.raises(BusinessError,match='文件格式无效'):parse_file('stores','s.xlsx',output.getvalue())

def test_import_http_and_rbac(client,session):
    response=client.post('/api/v1/business-imports/stores/preview',files={'file':('s.csv',content('stores',[{'code':'HTTP_S','name':'接口门店'}]),'text/csv')})
    assert response.status_code==200,response.text
    batch=response.json()
    assert client.post(f"/api/v1/business-imports/{batch['id']}/confirm",json={'confirmed':False}).status_code==422
    result=client.post(f"/api/v1/business-imports/{batch['id']}/confirm",json={'confirmed':True})
    assert result.status_code==200 and result.json()['status']=='IMPORTED'
    dispatcher=actor(session,'dispatcher',UserRole.DISPATCHER)
    login=client.post('/api/v1/auth/login',json={'username':dispatcher.username,'password':'BusinessPass123!'})
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    assert client.post('/api/v1/business-imports/stores/preview',headers=headers,files={'file':('s.csv',b'','text/csv')}).status_code==403

def test_exception_case_version_and_audit(session):
    admin=actor(session);session.add(Store(code='S',name='业务门店'));session.flush()
    demand=DeliveryDemand(date=datetime.now().date(),store_id=1,period='MORNING',quantity=10,status='PENDING');session.add(demand);session.commit()
    service=ExceptionCaseService(session)
    item=service.create('UNASSIGNED_DEMAND',demand.id,admin.id,admin)
    assert service.create('UNASSIGNED_DEMAND',demand.id,admin.id,admin).id==item.id
    service.update(item.id,1,'IN_PROGRESS',admin.id,'安排调度',admin)
    with pytest.raises(BusinessError,match='他人修改'):service.update(item.id,1,'RESOLVED',admin.id,'关闭',admin)
    with pytest.raises(BusinessError,match='仍然存在'):service.update(item.id,2,'RESOLVED',admin.id,'关闭',admin)
    demand.status='PLANNED';session.commit()
    item=service.update(item.id,2,'RESOLVED',admin.id,'已纳入草稿',admin)
    assert item.revision==3 and item.status=='RESOLVED' and demand.status=='PLANNED'
    assert len(service.events(item.id,admin))==3
    assert session.scalar(select(func.count()).select_from(ExceptionCaseEvent))==3
