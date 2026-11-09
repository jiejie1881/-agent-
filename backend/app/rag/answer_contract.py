"""Opt-in, isolated extractive answer contract. Not an NLP entailment model.

The resolver is a trusted SERVER dependency, never model/user JSON. Production
does not install it. Unknown support is blocked, not scored as a correct refusal.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path

from app.rag.answerability import ServerAssessment, Status
from app.rag.evidence_binding import BoundChunk, FactKind, assess_bound, read_tool_hint


class AnswerStatus(str, Enum):
    ANSWERABLE = 'ANSWERABLE'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
    NO_RELEVANT_EVIDENCE = 'NO_RELEVANT_EVIDENCE'
    REQUIRES_BUSINESS_TOOL = 'REQUIRES_BUSINESS_TOOL'
    BUSINESS_DATA_UNAVAILABLE = 'BUSINESS_DATA_UNAVAILABLE'
    EVIDENCE_CONFLICT = 'EVIDENCE_CONFLICT'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class EvidenceContext:
    original_query: str
    queries: tuple[str, ...]
    chunks: tuple[BoundChunk, ...]
    sha256: str
    valid: bool


def snapshot(state):
    """Bind owner, original question, ALL rewrites, actual results and metadata."""
    original = next((m.get('content', '') for m in reversed(state['messages']) if m['role'] == 'user'), '')
    rows = state.get('read_results', {})
    queries, chunks = [], []
    valid = bool(original)
    kinds = {'dispatch_rule': FactKind.RULE, 'cold_chain': FactKind.RULE,
             'cargo_rule': FactKind.RULE, 'exception_manual': FactKind.PROCEDURE,
             'system_manual': FactKind.PROCEDURE}
    for row in rows.values():
        if row.get('tool_name') != 'search_knowledge_base':
            continue
        data = row.get('data', {})
        query, hits = data.get('query'), data.get('results')
        if not isinstance(query, str) or not query or not isinstance(hits, list):
            valid = False
            continue
        queries.append(query)
        for hit in hits:
            if not isinstance(hit, dict):
                valid = False
                continue
            values = [hit.get('chunk_id'), hit.get('document_id') or hit.get('source'),
                      hit.get('index_version'), hit.get('content')]
            if any(not isinstance(v, str) or not v for v in values):
                valid = False
                continue
            # ACL/current state is revalidated by the real executor at each
            # boundary. Missing identity/version never becomes trusted evidence.
            chunks.append(BoundChunk(*values, kinds.get(hit.get('document_type'), FactKind.UNKNOWN),
                                     True, values[2] != 'legacy'))
    identity = dict(owner=state['user_id'], conversation=state.get('conversation_id'),
                    original=original, results=rows)
    return EvidenceContext(original, tuple(queries), tuple(chunks), digest(identity), valid)


@dataclass(frozen=True)
class SupportProof:
    context_sha256: str
    assessment: ServerAssessment
    kind: FactKind


@dataclass(frozen=True)
class BusinessRequest:
    context_sha256: str
    capability: str
    arguments_json: str
    subject_id: int
    date: str | None = None

    def key(self, original):
        return digest([original, self.capability, self.arguments_json, self.subject_id, self.date])


class IsolatedAnswerContract:
    """An explicit test-only dependency, with no environment auto-enablement."""
    def __init__(self, resolver):
        if not callable(resolver):
            raise TypeError('Trusted resolver required')
        self.resolver = resolver

    def validate_installation(self, checkpoint_path):
        from app.core.config import get_settings
        root = Path(__file__).resolve().parents[3] / 'docs' / 'evidence'
        if (get_settings().app_environment != 'test' or checkpoint_path is None or
                not Path(checkpoint_path).resolve().is_relative_to(root.resolve())):
            raise ValueError('Answer contract is restricted to isolated test evidence checkpoints')

    def resolve(self, context):
        proof = self.resolver(context)
        if proof is not None and type(proof) not in (SupportProof, BusinessRequest):
            raise TypeError('Model/user dictionaries are not server proofs')
        return proof

    def decision(self, context, proof):
        if not context.valid or proof is None or proof.context_sha256 != context.sha256:
            return AnswerStatus.INSUFFICIENT_EVIDENCE, ()
        if type(proof) is BusinessRequest:
            return AnswerStatus.REQUIRES_BUSINESS_TOOL, ()
        value = assess_bound(proof.assessment, proof.kind, context.chunks)
        if value.status == Status.SUPPORTED:
            return AnswerStatus.ANSWERABLE, value.references
        if value.status == Status.CONFLICT:
            return AnswerStatus.EVIDENCE_CONFLICT, ()
        if value.status in (Status.NOT_FOUND_IN_SEARCH, Status.NO_KB_ANSWER_VERIFIED):
            return AnswerStatus.NO_RELEVANT_EVIDENCE, ()
        if value.status == Status.CAPABILITY_UNAVAILABLE:
            return AnswerStatus.BUSINESS_DATA_UNAVAILABLE, ()
        return AnswerStatus.INSUFFICIENT_EVIDENCE, ()

    @staticmethod
    def render(content, spans, required_claims):
        """Only complete verified quotations, not arbitrary cited model prose.

        A substring could drop a negation or applicability condition. Requiring
        the complete approved span is deliberately conservative and measurable.
        """
        value = json.loads(content)
        if type(value) is not dict or set(value) != {'citations'} or not isinstance(value['citations'], list):
            raise ValueError('Invalid extractive response')
        matched = []
        for citation in value['citations']:
            if not isinstance(citation, dict) or set(citation) != {'chunk_id', 'quote'}:
                raise ValueError('Invalid citation')
            span = next((s for s in spans if s.chunk_id == citation['chunk_id'] and
                         s.source_text[s.start:s.end] == citation['quote']), None)
            if span is None or span in matched:
                raise ValueError('Unverified or duplicate quotation')
            matched.append(span)
        if not matched or not required_claims <= frozenset(c for s in matched for c in s.supports):
            raise ValueError('Incomplete evidence coverage')
        return '\n'.join(f'{s.source_text[s.start:s.end]} [{s.chunk_id}]' for s in matched)

    @staticmethod
    def business_tool(request, registry, actor):
        # Deliberately closed output projections. Plan metadata is not delivery
        # status, and no arrival-time/geolocation capability is invented.
        if (type(request.subject_id) is not int or request.subject_id <= 0 or
                request.capability not in {'vehicle_operating_status', 'driver_attendance'}):
            return None
        name = read_tool_hint(request.capability, registry, actor)
        if not name:
            return None
        arguments = registry.validate_arguments(name, json.loads(request.arguments_json))
        if name == 'list_drivers' and (not request.date or str(arguments.date) != request.date):
            return None
        if name == 'list_vehicles' and request.date is not None:
            return None  # current status cannot prove historical/future status
        return name, arguments.model_dump(mode='json')

    @staticmethod
    def business_answer(request, result):
        field = {'vehicle_operating_status': 'operating_status', 'driver_attendance': 'attendance'}[request.capability]
        if request.capability == 'driver_attendance' and result.get('date') != request.date:
            return None
        if not isinstance(result.get('items'), list):
            return None
        matches = [row for row in result['items'] if type(row) is dict and
                   type(row.get('id')) is int and row['id'] == request.subject_id]
        if len(matches) != 1 or field not in matches[0] or matches[0][field] is None:
            return None
        value = matches[0][field]
        if request.capability == 'vehicle_operating_status':
            if type(value) is not str or value not in {'ACTIVE', 'MAINTENANCE', 'RETIRED'}:
                return None
        elif (type(value) is not dict or set(value) != {'MORNING', 'AFTERNOON'} or
              any(type(v) is not bool for v in value.values())):
            return None
        return '业务工具已核验：' + canonical(dict(id=request.subject_id, date=request.date,
                                              **{field: value}))
