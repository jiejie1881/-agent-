"""Bind trusted assessments to authorized evidence, not a semantic classifier.

No model output deserializer, question IDs, score threshold or external I/O.
Unknown semantic support stays unknown. Routing is a hint, never tool execution.
"""
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import math

from app.rag.answerability import ServerAssessment,Decision,Status,assess


class FactKind(str,Enum):
    RULE='RULE'
    PROCEDURE='PROCEDURE'
    STATIC='STATIC'
    LIVE_ORDER='LIVE_ORDER'
    LIVE_VEHICLE='LIVE_VEHICLE'
    LIVE_DELIVERY='LIVE_DELIVERY'
    UNKNOWN='UNKNOWN'


@dataclass(frozen=True)
class BoundChunk:
    chunk_id:str
    document_id:str
    version:str
    text:str
    kind:FactKind
    authorized:bool
    current:bool
    scores:tuple[tuple[str,float],...]=()

    def __post_init__(self):
        if any(not isinstance(v,str) or not v for v in (self.chunk_id,self.document_id,self.version,self.text)):
            raise ValueError('Evidence identity/text required')
        if type(self.kind) is not FactKind or type(self.authorized) is not bool or type(self.current) is not bool:
            raise TypeError('Explicit server evidence metadata required')
        if not isinstance(self.scores,tuple) or any(not isinstance(k,str) or type(v) not in (float,int) or not math.isfinite(v) for k,v in self.scores):
            raise ValueError('Invalid diagnostic score')


# Verified against current registered read-tool projections. No arrival-time
# capability is invented: list_transport_tasks only exposes plan/task metadata.
READ_CAPABILITIES={
    'vehicle_operating_status':'list_vehicles',
    'driver_attendance':'list_drivers',
    'transport_plan_status':'list_transport_tasks',
}


def read_tool_hint(capability,registry,actor):
    from app.domain.permissions import has_permission
    name=READ_CAPABILITIES.get(capability)
    if not name or actor is None or not getattr(actor,'is_active',False):return None
    try:definition=registry.get(name)
    except Exception:return None  # A missing/failed catalogue grants no ability.
    if not definition.read_only or not has_permission(actor.role,definition.required_permission):return None
    return name


def assess_bound(value,kind,chunks):
    """Only trusted typed server assessments can establish positive support."""
    if type(value) is not ServerAssessment or type(kind) is not FactKind or type(chunks) is not tuple:
        raise TypeError('Trusted immutable assessment and evidence required')
    if any(type(c) is not BoundChunk for c in chunks):raise TypeError('Bound chunks required')
    if value.authorization!='ALLOW':return assess(value)
    if any(not c.authorized for c in chunks):return Decision(Status.PERMISSION_DENIED)
    if any(not c.current for c in chunks):return Decision(Status.INSUFFICIENT_EVIDENCE)
    identities={}
    for c in chunks:
        identity=(c.document_id,c.version,c.text,c.kind)
        if c.chunk_id in identities and identities[c.chunk_id]!=identity:return Decision(Status.CONFLICT)
        identities[c.chunk_id]=identity
    if kind in {FactKind.LIVE_ORDER,FactKind.LIVE_VEHICLE,FactKind.LIVE_DELIVERY}:
        capability=value.required_business_capability
        # KB source spans cannot be relabelled as real-time tool observations.
        allowed=value.approved_business_capabilities & frozenset(READ_CAPABILITIES)
        return assess(replace(value,intent='LIVE',approved_business_capabilities=allowed))
    if kind is FactKind.UNKNOWN:return Decision(Status.INSUFFICIENT_EVIDENCE)
    if value.candidates!=len(identities):return Decision(Status.INSUFFICIENT_EVIDENCE)
    allowed_kinds={FactKind.RULE:{FactKind.RULE},FactKind.PROCEDURE:{FactKind.PROCEDURE,FactKind.RULE},
                   FactKind.STATIC:{FactKind.STATIC}}[kind]
    by_id={c.chunk_id:c for c in chunks}
    for span in value.spans:
        chunk=by_id.get(span.chunk_id)
        if chunk is None:return Decision(Status.INSUFFICIENT_EVIDENCE)
        if chunk.version!=span.document_version or chunk.text!=span.source_text:return Decision(Status.CONFLICT)
        if chunk.kind not in allowed_kinds:return Decision(Status.CONDITION_MISMATCH)
    return assess(value)


def shadow_observation(query,hits):
    """Metadata-only observation after caller's fresh ACL revalidation.

    Retrieval alone supplies no claim support. Do NOT turn this observation
    into an automatic refusal/positive semantic score or an active policy.
    """
    from app.rag.reference_policy import instance_event_request
    from app.rag.bm25_index import tokenize_search
    types={'dispatch_rule':FactKind.RULE,'cold_chain':FactKind.RULE,'cargo_rule':FactKind.RULE,
           'exception_manual':FactKind.PROCEDURE}
    chunks=[];metadata=[]
    for h in hits:
        if not isinstance(h,dict):return dict(status='INSUFFICIENT_EVIDENCE',reason='INVALID_METADATA',mode='shadow')
        key=h.get('chunk_id');version=h.get('index_version');text=h.get('content');source=h.get('document_id') or h.get('source')
        if not all(isinstance(v,str) and v for v in (key,version,text,source)):
            return dict(status='INSUFFICIENT_EVIDENCE',reason='MISSING_VERSION_OR_SOURCE',mode='shadow')
        scores=tuple((k,float(h[k])) for k in ('score','bm25_score','rrf_score','reranker_score')
                     if type(h.get(k)) in (int,float) and math.isfinite(h[k]))
        kind=types.get(h.get('document_type'),FactKind.UNKNOWN)
        chunks.append(BoundChunk(key,source,version,text,kind,True,version!='legacy',scores))
        metadata.append(dict(chunk_id=key,document_id=source,version=version,kind=kind.value,scores=dict(scores)))
    kind=FactKind.LIVE_DELIVERY if instance_event_request(query,tokenize_search(query)) else FactKind.UNKNOWN
    value=ServerAssessment(authorization='ALLOW',candidates=len({c.chunk_id for c in chunks}),
                           versions_valid=bool(chunks),required_business_capability='actual_arrival_time' if kind is FactKind.LIVE_DELIVERY else None)
    decision=assess_bound(value,kind,tuple(chunks))
    return dict(policy='bound-evidence-v1',mode='shadow',query_sha256=hashlib.sha256(query.encode()).hexdigest(),
                status=decision.status.value,may_answer=decision.may_answer,
                action='BUSINESS_CAPABILITY_REQUIRED' if kind is FactKind.LIVE_DELIVERY else 'SERVER_ASSESSMENT_REQUIRED',
                evidence=metadata,reason='Retrieval scores do not establish semantic support')
