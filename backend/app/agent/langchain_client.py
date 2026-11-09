"""LangChain model transport; business validation remains outside the model."""
import json
from time import perf_counter

import httpx
import openai
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agent.exceptions import (
    AgentModelConnectionError,
    AgentModelConfigurationError,
    AgentModelResponseError,
    AgentModelTimeoutError,
)
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.model_types import (
    AgentModelResponse,
    AgentNetworkEvent,
    AgentTokenUsage,
    AgentToolCall,
)
from app.agent.observability import no_automatic_trace
from app.core.model_budget import BudgetDenied, BudgetedAsyncTransport, budget_for


class LangChainModelClient(OpenAICompatibleModelClient):
    def __init__(self, settings=None, transport=None, *, max_output_tokens=None, operation_id=None):
        super().__init__(settings=settings, transport=transport, operation_id=operation_id)
        self.max_output_tokens = max_output_tokens

    @no_automatic_trace
    async def chat(self, messages, tools=None):
        from app.agent.stream_events import sink
        if sink.get() is not None and getattr(self, 'phase', '') == 'summary' and getattr(self, 'stream_final', False) and not tools:
            return await self._stream_summary(messages)
        model, key, url = self._validated_configuration()
        started, events = perf_counter(), []

        async def attach_trace(request):
            async def trace(name, info):
                # Never retain info: it can contain URLs, headers and API keys.
                if name.startswith(("connection.", "http11.", "http2.")) and name.endswith((".started", ".complete", ".failed")):
                    events.append(AgentNetworkEvent(event=name, elapsed_ms=(perf_counter() - started) * 1000))
            request.extensions["trace"] = trace

        try:
            async with httpx.AsyncClient(timeout=self._settings.agent_timeout,
                                         transport=BudgetedAsyncTransport(budget_for(self._settings),
                                             f"{url.rstrip('/')}/chat/completions", "chat", self._transport,
                                             self.operation_id),
                                         event_hooks={"request": [attach_trace]}) as client:
                chat = ChatOpenAI(model=model, api_key=key, base_url=url,
                                  timeout=self._settings.agent_timeout, max_retries=0,
                                  http_socket_options=(),
                                  use_responses_api=False, http_async_client=client,
                                  **({"max_tokens": self.max_output_tokens} if self.max_output_tokens is not None else {}))
                bound = chat.bind_tools(list(tools)) if tools else chat
                response = await bound.ainvoke([self._serialize_message(item) for item in messages])
            if response.invalid_tool_calls:
                raise AgentModelResponseError('Agent模型返回了无效工具参数')
            content = response.content
            if not isinstance(content, str):
                raise AgentModelResponseError()
            calls = tuple(AgentToolCall(id=item['id'], name=item['name'], arguments=item['args']) for item in response.tool_calls)
            usage = None
            if response.usage_metadata:
                try:
                    usage = AgentTokenUsage.model_validate(response.usage_metadata)
                except ValidationError:
                    pass  # Unusable provider accounting is UNKNOWN, never fabricated.
            return AgentModelResponse(content=content or None, tool_calls=calls,
                finish_reason=response.response_metadata.get("finish_reason"), token_usage=usage,
                network_events=tuple(events))
        except BudgetDenied:
            raise AgentModelConfigurationError("模型预算保护未通过，本次不允许调用模型") from None
        except openai.APITimeoutError as exc:
            cause, phase, seen = exc, "UNKNOWN", set()
            for _ in range(8):
                if cause is None or id(cause) in seen:
                    break
                seen.add(id(cause))
                phase = next((name for kind, name in (
                    (httpx.ConnectTimeout, "CONNECT"), (httpx.ReadTimeout, "READ"),
                    (httpx.WriteTimeout, "WRITE"), (httpx.PoolTimeout, "POOL"),
                ) if isinstance(cause, kind)), "UNKNOWN")
                if phase != "UNKNOWN":
                    break
                cause = cause.__cause__ or cause.__context__
            error = AgentModelTimeoutError(phase=phase)
            error.network_events = tuple(events)
            raise error from None
        except openai.APIConnectionError:
            raise AgentModelConnectionError() from None
        except openai.APIStatusError as exc:
            raise AgentModelResponseError(self._safe_http_error_message(exc.response)) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
            raise AgentModelResponseError() from None

    async def _stream_summary(self, messages):
        from app.agent.stream_events import emit
        from uuid import uuid4
        model, key, url = self._validated_configuration()
        started = perf_counter()
        first = None
        try:
            async with httpx.AsyncClient(timeout=self._settings.agent_timeout,
                transport=BudgetedAsyncTransport(budget_for(self._settings),
                    f"{url.rstrip('/')}/chat/completions", 'chat_stream', self._transport,
                    self.operation_id or uuid4().hex)) as client:
                chat = ChatOpenAI(model=model, api_key=key, base_url=url, max_retries=0,
                    http_socket_options=(), use_responses_api=False, http_async_client=client,
                    max_tokens=self.max_output_tokens or 2048, stream_usage=True)
                aggregate = None
                async for chunk in chat.astream([self._serialize_message(m) for m in messages]):
                    aggregate = chunk if aggregate is None else aggregate + chunk
                    if isinstance(chunk.content, str) and chunk.content:
                        if first is None:
                            first = perf_counter()
                        emit('token', {'text': chunk.content})
            if aggregate is None or aggregate.tool_calls or aggregate.invalid_tool_calls:
                raise AgentModelResponseError()
            usage = AgentTokenUsage.model_validate(aggregate.usage_metadata) if aggregate.usage_metadata else None
            elapsed = perf_counter() - started
            output = usage.output_tokens if usage else None
            in_price = self._settings.agent_input_price_per_million
            out_price = self._settings.agent_output_price_per_million
            currency = self._settings.agent_cost_currency
            cost = ((usage.input_tokens * in_price + usage.output_tokens * out_price) / 1_000_000
                    if usage is not None and in_price is not None and out_price is not None and currency else 'UNKNOWN')
            emit('model_metrics', {'model': model, 'usage': usage.model_dump() if usage else None,
                'latency_ms': elapsed * 1000, 'ttft_ms': (first-started)*1000 if first else None,
                'tpot_ms': (perf_counter()-first)*1000/(output-1) if first and output and output > 1 else None,
                'tps': output/elapsed if output is not None and elapsed > 0 else None, 'cost': cost,
                'currency': currency, 'cost_source': 'CALCULATED' if cost != 'UNKNOWN' else 'UNKNOWN',
                'input_price_per_million': in_price, 'output_price_per_million': out_price})
            return AgentModelResponse(content=aggregate.content, token_usage=usage)
        except BudgetDenied:
            raise AgentModelConfigurationError('模型预算保护未通过，本次不允许流式调用') from None
        except openai.APITimeoutError:
            raise AgentModelTimeoutError() from None
        except (openai.APIConnectionError, httpx.RequestError):
            raise AgentModelConnectionError() from None
        except openai.APIStatusError:
            raise AgentModelResponseError() from None
