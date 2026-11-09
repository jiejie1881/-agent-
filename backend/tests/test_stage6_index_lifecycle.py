import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.versioned_index import digest
from tests.test_rag_hybrid_safety import service


def test_free_lexical_upgrade_prepares_validated_candidate_then_cas_and_rollback(tmp_path,monkeypatch):
    rag=service(tmp_path)
    current=rag._configuration
    monkeypatch.setattr(rag,'_configuration',lambda:{k:v for k,v in current().items() if k!='lexical_policy'})
    rag.rebuild()
    old=rag.versions.load()[0]['version']
    monkeypatch.setattr(rag,'_configuration',current)
    with monkeypatch.context() as only_build:
        only_build.setattr(rag.embedding_client,'embed_documents',lambda *args:pytest.fail('reuse must not call embedding'))
        rag.rebuild(activate=False,reuse_embeddings=True)
    new=rag.last_built_version
    assert rag.versions.load()[0]['version']==old
    rag.versions.activate(new,expected_active_version=old,configuration=current())
    assert rag.search('车辆出勤')
    with pytest.raises(KnowledgeBaseNotReadyError,match='已变化'):
        rag.versions.activate(new,expected_active_version=old,configuration=current())
    # Rollback also requires the matching old code/configuration contract.
    legacy={k:v for k,v in current().items() if k!='lexical_policy'}
    rag.versions.activate(old,expected_active_version=new,configuration=legacy)
    monkeypatch.setattr(rag,'_configuration',lambda:legacy)
    assert rag.search('车辆出勤')[0].index_version==old


def test_switch_io_failure_and_corrupt_vectors_keep_old_active(tmp_path,monkeypatch):
    rag=service(tmp_path)
    rag.rebuild()
    old=rag.last_built_version
    rag.rebuild(activate=False,reuse_embeddings=True)
    new=rag.last_built_version
    original=rag.versions._write
    def fail(path,value):
        if path.name=='active.json':raise OSError('stage6 pointer I/O failure')
        return original(path,value)
    monkeypatch.setattr(rag.versions,'_write',fail)
    with pytest.raises(OSError):rag.versions.activate(new,expected_active_version=old,configuration=rag._configuration())
    assert rag.versions.load()[0]['version']==old
    monkeypatch.setattr(rag.versions,'_write',original)
    _,_chunks,store=rag.versions._read(rag.versions.root/(new+'.json'))
    saved=store._existing_collection().get(include=['embeddings'])
    row=list(saved['embeddings'][0]);row[0]+=0.5
    store._existing_collection().update(ids=[saved['ids'][0]],embeddings=[row])
    with pytest.raises(KnowledgeBaseNotReadyError):
        rag.versions.activate(new,expected_active_version=old,configuration=rag._configuration())
    assert rag.versions.load()[0]['version']==old


def test_readers_pin_a_single_version_during_switches(tmp_path):
    rag=service(tmp_path)
    rag.rebuild();old=rag.last_built_version
    rag.rebuild(activate=False,reuse_embeddings=True);new=rag.last_built_version
    def read(_):
        hits=rag.search('车辆出勤')
        assert len({h.index_version for h in hits})==1
        assert hits[0].index_version in {old,new}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(read,i) for i in range(20)]
        active=old
        for target in (new,old,new,old):
            rag.versions.activate(target,expected_active_version=active,configuration=rag._configuration())
            active=target
        for future in futures:future.result(timeout=30)


def test_model_document_or_dimension_changes_cannot_reuse_or_activate(tmp_path):
    rag=service(tmp_path);rag.rebuild();old=rag.last_built_version
    path=rag.versions.root/(old+'.json')
    data=json.loads(path.read_text(encoding='utf-8'))
    data['payload']['embedding_dimension']+=1
    data['sha256']=digest(data['payload']);path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(KnowledgeBaseNotReadyError):rag.search('派车')
