"""Actual loopback HTTP + real SDK, deterministic protocol server; not a real LLM."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.agent.exceptions import AgentModelResponseError, AgentModelTimeoutError
from app.agent.langchain_client import LangChainModelClient
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.core.config import Settings


@pytest.mark.parametrize('mode',['valid','invalid','rate_limit','timeout'])
def test_sdk_loopback_is_bounded_no_retry_and_safe_errors(mode):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            if mode=='timeout':time.sleep(.25)
            status=429 if mode=='rate_limit' else 200
            payload={'error':{'message':'SECRET_PROVIDER_MUST_NOT_LEAK'}} if status==429 else {
                'id':'stage4-local','object':'chat.completion','created':1,'model':'local-protocol-standin',
                'choices':[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':[{
                    'id':'call1','type':'function','function':{'name':'submit_dispatch_candidate',
                     'arguments':'{"candidate_id":"stage4"}' if mode!='invalid' else '{broken'}}]},'finish_reason':'tool_calls'}],
                'usage':{'prompt_tokens':12,'completion_tokens':6,'total_tokens':18}}
            data=json.dumps(payload).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            try:self.wfile.write(data)
            except OSError:pass  # Client timeout can close the Windows socket in several ways.
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    settings=Settings(_env_file=None,database_url='sqlite://',jwt_secret_key='x'*40,
                      agent_provider='openai-compatible',agent_model='local-protocol-standin',
                      agent_api_key='test-only-local-key',agent_base_url=f'http://127.0.0.1:{server.server_port}/v1',
                      agent_timeout=.05 if mode=='timeout' else 3)
    client=LangChainModelClient(settings,max_output_tokens=128,operation_id=f'stage4-local-protocol-{mode}')
    tools=[{'type':'function','function':{'name':'submit_dispatch_candidate','parameters':{'type':'object','properties':{'candidate_id':{'type':'string'}}}}}]
    started=time.monotonic()
    try:
        request=client.chat([AgentModelMessage(role=AgentMessageRole.USER,content='非客户隔离运输测试')],tools)
        if mode=='valid':
            result=asyncio.run(request)
            assert result.tool_calls[0].arguments=={'candidate_id':'stage4'}
            assert result.token_usage.total_tokens==18
        else:
            expected=AgentModelTimeoutError if mode=='timeout' else AgentModelResponseError
            with pytest.raises(expected) as error:asyncio.run(request)
            assert 'SECRET_PROVIDER' not in str(error.value)
        assert len(calls)==1 and calls[0].get('max_completion_tokens',calls[0].get('max_tokens'))==128
        assert time.monotonic()-started<5
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
