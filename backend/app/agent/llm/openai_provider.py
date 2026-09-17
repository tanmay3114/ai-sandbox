"""OpenAI SDK implementation of the LLMProvider abstraction."""

import json
import logging
from typing import Any

import openai
from openai import AsyncOpenAI
from openai._types import NOT_GIVEN

from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.core.exceptions import LLMProviderError

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider implementation backed by OpenAI's official AsyncOpenAI client."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        temperature: float = 0.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature

        if client is not None:
            self._client = client
        else:
            if not api_key:
                raise LLMProviderError(
                    "OpenAI API key is required. "
                    "Set SANDBOX_LLM_API_KEY or pass api_key explicitly."
                )
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )

    @property
    def client(self) -> AsyncOpenAI:
        """Return the underlying AsyncOpenAI client."""
        return self._client

    def _format_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert normalized LLMMessage models into OpenAI Chat Completions payload."""
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                entry["content"] = msg.content
            if msg.name is not None:
                entry["name"] = msg.name

            if msg.role == "assistant" and msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": (
                                json.dumps(tc.arguments)
                                if isinstance(tc.arguments, dict)
                                else str(tc.arguments)
                            ),
                        },
                    }
                    for tc in msg.tool_calls
                ]

            if msg.role == "tool":
                if not msg.tool_call_id:
                    raise LLMProviderError(
                        "Messages with role='tool' must supply a non-empty tool_call_id."
                    )
                entry["tool_call_id"] = msg.tool_call_id

            formatted.append(entry)
        return formatted

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize tools into OpenAI function calling format."""
        formatted: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                formatted.append(tool)
            else:
                formatted.append({"type": "function", "function": tool})
        return formatted

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Execute Chat Completion via OpenAI API and return normalized response."""
        openai_messages = self._format_messages(messages)
        openai_tools = self._format_tools(tools) if tools else NOT_GIVEN

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                tools=openai_tools,
                temperature=self.temperature,
            )
        except openai.OpenAIError as exc:
            logger.error(f"OpenAI API call failed: {exc}")
            raise LLMProviderError(
                f"OpenAI API completion failed: {exc}",
                details={"model": self.model, "error_type": type(exc).__name__},
            ) from exc
        except Exception as exc:
            logger.error(f"Unexpected error calling OpenAI API: {exc}")
            raise LLMProviderError(
                f"Unexpected error communicating with LLM provider: {exc}",
                details={"model": self.model},
            ) from exc

        if not response.choices:
            raise LLMProviderError(
                "OpenAI API returned an empty choices list.",
                details={"model": self.model},
            )

        choice = response.choices[0]
        parsed_tool_calls: list[ToolCallRequest] = []

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Failed to parse tool call JSON arguments for {tc.function.name}"
                    )
                    args = {"raw": raw_args}
                parsed_tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage: dict[str, int] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=choice.message.content,
            tool_calls=parsed_tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
