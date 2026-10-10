"""LangChain model transport; business validation remains outside the model."""
import json
import httpx
import openai
from langchain_openai import ChatOpenAI
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.model_types import AgentModelResponse, AgentToolCall
from app.agent.exceptions import AgentModelConnectionError, AgentModelResponseError, AgentModelTimeoutError


class LangChainModelClient(OpenAICompatibleModelClient):
    async def chat(self, messages, tools=None):
        model, key, url = self._validated_configuration()
        try:
            async with httpx.AsyncClient(timeout=self._settings.agent_timeout, transport=self._transport) as client:
                chat = ChatOpenAI(model=model, api_key=key, base_url=url,
                                  timeout=self._settings.agent_timeout, max_retries=0,
                                  use_responses_api=False, http_async_client=client)
                bound = chat.bind_tools(list(tools)) if tools else chat
                response = await bound.ainvoke([self._serialize_message(item) for item in messages])
            if response.invalid_tool_calls:
                raise AgentModelResponseError('Agent模型返回了无效工具参数')
            content = response.content
            if not isinstance(content, str):
                raise AgentModelResponseError()
            calls = tuple(AgentToolCall(id=item['id'], name=item['name'], arguments=item['args']) for item in response.tool_calls)
            return AgentModelResponse(content=content or None, tool_calls=calls)
        except openai.APITimeoutError:
            raise AgentModelTimeoutError() from None
        except openai.APIConnectionError:
            raise AgentModelConnectionError() from None
        except openai.APIStatusError as exc:
            raise AgentModelResponseError(self._safe_http_error_message(exc.response)) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
            raise AgentModelResponseError() from None
