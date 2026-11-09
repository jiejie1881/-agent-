import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.rag.bm25_index import LEXICAL_POLICY, tokenize, tokenize_search
from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
from app.rag.exceptions import KnowledgeBaseEmbeddingError, KnowledgeBaseNotReadyError
from tests.test_rag_hybrid_safety import service


def embed(data):
    config = Settings(_env_file=None, rag_embedding_provider='openai-compatible',
                      rag_embedding_base_url='https://protocol.invalid/v1',
                      rag_embedding_model='protocol-only',rag_embedding_api_key='fake-not-a-real-key')
    transport = httpx.MockTransport(lambda request: httpx.Response(200,json={'data':data}))
    return OpenAICompatibleEmbeddingClient(config,transport).embed_documents(['first','second'])


@pytest.mark.parametrize('data',[
    [{'index':0,'embedding':[1]},{'index':0,'embedding':[2]}],
    [{'index':1,'embedding':[1]},{'index':2,'embedding':[2]}],
    [{'index':False,'embedding':[1]},{'index':1,'embedding':[2]}],
    [{'index':0,'embedding':[1]},{'index':1,'embedding':[2,3]}],
    [{'index':0,'embedding':['NaN']},{'index':1,'embedding':[2]}],
    [{'index':0,'embedding':['Infinity']},{'index':1,'embedding':[2]}],
    {'index':0,'embedding':[1]},
])
def test_embedding_rejects_ambiguous_order_or_invalid_vectors(data):
    with pytest.raises(KnowledgeBaseEmbeddingError,match='格式异常'):
        embed(data)


def test_embedding_restores_exact_input_order():
    assert embed([{'index':1,'embedding':[2,3]},{'index':0,'embedding':[0,1]}]) == [[0,1],[2,3]]


def test_search_subwords_and_identifiers_preserve_original_contract():
    text = '物流管理系统 人工确认 配送需求 STORE-021 /api/v1/dispatch-plans'
    tokens = tokenize_search(text)
    assert set(tokenize(text)).issubset(tokens)
    assert '物流' in tokens and '管理' in tokens
    assert 'store-021' in tokens and '/api/v1/dispatch-plans' in tokens


def test_lexical_policy_change_requires_explicit_index_rebuild(tmp_path,monkeypatch):
    rag = service(tmp_path)
    current = rag._configuration
    monkeypatch.setattr(rag,'_configuration',lambda:{k:v for k,v in current().items() if k!='lexical_policy'})
    rag.rebuild()
    monkeypatch.setattr(rag,'_configuration',current)
    assert current()['lexical_policy']==LEXICAL_POLICY
    with pytest.raises(KnowledgeBaseNotReadyError,match='配置已变化'):
        rag.search('车辆出勤')
    rag.rebuild()
    assert rag.search('车辆出勤')


@pytest.mark.parametrize('payload,code', [({'status':'ready'},0),([],2),(None,2),('ready',2)])
def test_monitor_cli_handles_actual_http_json_shape(payload,code):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        tool=Path(__file__).resolve().parents[1]/'tools/monitor_health.py'
        result=subprocess.run([sys.executable,str(tool),'--url',f'http://127.0.0.1:{server.server_port}/health/ready'],
                              capture_output=True,text=True,timeout=15,check=False)
        assert result.returncode==code
        assert json.loads(result.stdout)['event']==('health_ok' if code==0 else 'health_alert')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
