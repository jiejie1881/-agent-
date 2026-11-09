from app.services.audit_log_service import redact_audit_changes
def test_audit_redacts_nested_credentials_and_contacts_without_mutating_input():
    data={'after':{'contact_phone':'13912345678','password':'never-log','database_url':'never-log'},'rows':[{'vehicle_id':7,'api_key':'never-log'}]}
    result=redact_audit_changes(data)
    assert result['after']=={'contact_phone':'*******5678','password':'[REDACTED]','database_url':'[REDACTED]'}
    assert result['rows'][0]=={'vehicle_id':7,'api_key':'[REDACTED]'}
    assert data['after']['password']=='never-log'
def test_audit_preserves_business_state_and_empty_contacts():
    data={'source_order_id':123,'before_status':'DRAFT','after_status':'PUBLISHED','receiver_phone':None}
    assert redact_audit_changes(data)==data
