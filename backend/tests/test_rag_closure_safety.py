"""Synthetic-only regressions for accidentally reusing a sealed test budget."""
import asyncio
import hashlib
import time

import httpx
import pytest

from app.core.model_budget import BudgetDenied, BudgetPolicy, ModelBudget, BudgetedSyncTransport, BudgetedAsyncTransport


def budget_in(folder):
    folder.mkdir(parents=True, exist_ok=True)
    budget = ModelBudget(folder / ModelBudget.FILENAME, BudgetPolicy(2, 20, 10))
    budget.initialize_new(expires_at=time.time() + 60)
    return budget


def seal(folder, budget):
    # A marker's presence is enough to fail closed; no historical JSON is opened.
    digest = hashlib.sha256(budget.path.read_bytes()).hexdigest()
    (folder / 'SHA256_MANIFEST.json').write_text('{}', encoding='utf8')
    return digest


@pytest.mark.parametrize('nested', [False, True])
def test_sealed_budget_denied_before_sqlite_metadata_or_contents_change(tmp_path, nested):
    root = tmp_path / 'sealed'
    budget = budget_in(root / 'billing' if nested else root)
    digest = seal(root, budget)
    before = budget.path.stat()
    with pytest.raises(BudgetDenied) as error:
        budget.reserve('closure-operation', 'digest', 'chat')
    assert error.value.reason == 'sealed_evidence_budget'
    after = budget.path.stat()
    assert (after.st_size, after.st_mtime_ns, after.st_atime_ns) == (before.st_size, before.st_mtime_ns, before.st_atime_ns)
    assert hashlib.sha256(budget.path.read_bytes()).hexdigest() == digest
    assert not list(root.rglob('*journal*'))


def test_initializing_under_sealed_evidence_creates_no_file(tmp_path):
    (tmp_path / 'SHA256_MANIFEST.json').write_text('{}', encoding='utf8')
    budget = ModelBudget(tmp_path / ModelBudget.FILENAME, BudgetPolicy(2, 20, 10))
    with pytest.raises(BudgetDenied) as error:
        budget.initialize_new(expires_at=time.time() + 60)
    assert error.value.reason == 'sealed_evidence_budget'
    assert not budget.path.exists()


def test_sealing_inflight_budget_blocks_settlement_without_rewriting_history(tmp_path):
    budget = budget_in(tmp_path / 'active')
    budget.reserve('closure-operation', 'digest', 'chat')
    digest = seal(budget.path.parent, budget)
    with pytest.raises(BudgetDenied) as error:
        budget.finish('closure-operation', True)
    assert error.value.reason == 'sealed_evidence_budget'
    assert hashlib.sha256(budget.path.read_bytes()).hexdigest() == digest
    # The pending call remains conservative; sealing must wait for settlement.


@pytest.mark.parametrize('asynchronous', [False, True])
def test_sealed_budget_blocks_model_transport_before_mock_upstream(tmp_path, asynchronous):
    budget = budget_in(tmp_path / 'sealed')
    seal(budget.path.parent, budget)
    sent = []
    def upstream(request):
        sent.append(request)
        return httpx.Response(200, json={})
    endpoint = 'https://model.example/v1/embeddings'
    request = httpx.Request('POST', endpoint, json={'input':['synthetic']})
    with pytest.raises(BudgetDenied):
        if asynchronous:
            async def call():
                transport = BudgetedAsyncTransport(budget, endpoint, 'embedding', httpx.MockTransport(upstream))
                try:
                    await transport.handle_async_request(request)
                finally:
                    await transport.aclose()
            asyncio.run(call())
        else:
            with BudgetedSyncTransport(budget, endpoint, 'embedding', httpx.MockTransport(upstream)) as transport:
                transport.handle_request(request)
    assert sent == []


def test_active_sibling_budget_is_not_blocked_by_sealed_sibling(tmp_path):
    sealed = tmp_path / 'old-evidence'
    old = budget_in(sealed)
    seal(sealed, old)
    active = budget_in(tmp_path / 'new-active-budget')
    active.reserve('closure-operation', 'digest', 'embedding')
    active.finish('closure-operation', True)
