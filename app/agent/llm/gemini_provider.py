"""Google Gemini SDK implementation of the LLMProvider abstraction."""

import json
import logging
from typing import Any
from uuid import uuid4

from google import genai
from google.genai import errors, types

from app.agent.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.core.exceptions import LLMProviderError

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """LLM provider implementation backed by Google's official google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.0,
        client: genai.Client | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature

        if client is not None:
            self._client = client
        else:
            if not api_key:
                raise LLMProviderError(
                    "Gemini API key is required. "
                    "Set SANDBOX_LLM_API_KEY or pass api_key explicitly."
                )
            self._client = genai.Client(api_key=api_key)

    @property
    def client(self) -> genai.Client:
        """Return the underlying genai.Client."""
        return self._client

    def _format_contents(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[types.Content]]:
        """Separate system instructions and convert remaining messages to Gemini Content models."""
        system_parts = [
            msg.content for msg in messages if msg.role == "system" and msg.content
        ]
        system_instruction = "\n\n".join(system_parts) if system_parts else None

        contents: list[types.Content] = []
        for msg in messages:
            if msg.role == "system":
                continue
            elif msg.role == "user":
                part = types.Part.from_text(text=msg.content or "")
                if contents and contents[-1].role == "user":
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
            elif msg.role == "assistant":
                parts: list[types.Part] = []
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        # 1. Preserve any preceding/associated thought parts
                        thought_parts = getattr(tc, "thought_parts", None)
                        if thought_parts:
                            for tp in thought_parts:
                                if isinstance(tp, types.Part):
                                    parts.append(tp)
                                elif isinstance(tp, dict):
                                    parts.append(types.Part.model_validate(tp))

                        # 2. Preserve function call part with its exact thought_signature
                        raw_part = getattr(tc, "raw_part", None)
                        if raw_part is not None:
                            if isinstance(raw_part, types.Part):
                                parts.append(raw_part)
                            elif isinstance(raw_part, dict):
                                parts.append(types.Part.model_validate(raw_part))
                            else:
                                parts.append(
                                    types.Part(
                                        function_call=types.FunctionCall(
                                            name=tc.name,
                                            args=tc.arguments
                                            if isinstance(tc.arguments, dict)
                                            else {},
                                            id=tc.id,
                                        ),
                                        thought_signature=tc.thought_signature,
                                    )
                                )
                        else:
                            parts.append(
                                types.Part(
                                    function_call=types.FunctionCall(
                                        name=tc.name,
                                        args=tc.arguments
                                        if isinstance(tc.arguments, dict)
                                        else {},
                                        id=tc.id,
                                    ),
                                    thought_signature=tc.thought_signature,
                                )
                            )

                if msg.content:
                    has_text = any(getattr(p, "text", None) == msg.content for p in parts)
                    if not has_text:
                        if parts:
                            parts.insert(0, types.Part.from_text(text=msg.content))
                        else:
                            parts.append(types.Part.from_text(text=msg.content))

                if not parts:
                    parts.append(types.Part.from_text(text=""))

                if contents and contents[-1].role == "model":
                    contents[-1].parts.extend(parts)
                else:
                    contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                resp_dict: dict[str, Any]
                if msg.content:
                    try:
                        parsed = json.loads(msg.content)
                        if isinstance(parsed, dict):
                            resp_dict = parsed
                        else:
                            resp_dict = {"result": parsed}
                    except Exception:
                        resp_dict = {"output": msg.content}
                else:
                    resp_dict = {}

                part = types.Part(
                    function_response=types.FunctionResponse(
                        name=msg.name or "tool",
                        response=resp_dict,
                        id=msg.tool_call_id,
                    )
                )
                if contents and contents[-1].role == "user":
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))

        return system_instruction, contents

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[types.Tool]:
        """Convert standard tool schemas into Gemini FunctionDeclarations wrapped in a Tool."""
        function_declarations: list[types.FunctionDeclaration] = []
        for tool in tools:
            name = tool.get("name")
            description = tool.get("description")
            params = tool.get("parameters") or tool.get("parameters_json_schema")
            if not name:
                continue
            function_declarations.append(
                types.FunctionDeclaration(
                    name=name,
                    description=description,
                    parameters_json_schema=params,
                )
            )
        return [types.Tool(function_declarations=function_declarations)]

    async def generate_response(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send chat messages and tool declarations to Gemini and return normalized response."""
        system_instruction, contents = self._format_contents(messages)

        gemini_tools = self._format_tools(tools) if tools else None

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            system_instruction=system_instruction,
            tools=gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        try:
            response: types.GenerateContentResponse = (
                await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
            )
        except errors.APIError as exc:
            logger.error(f"Gemini API error during generation: {exc}")
            raise LLMProviderError(f"Gemini API generation failed: {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected error communicating with Gemini API: {exc}")
            raise LLMProviderError(f"Gemini API communication error: {exc}") from exc

        # Extract function calls and their native Part objects with thought signatures
        tool_calls: list[ToolCallRequest] = []
        candidate = response.candidates[0] if response.candidates else None
        candidate_parts: list[types.Part] = (
            list(candidate.content.parts)
            if (candidate and candidate.content and candidate.content.parts)
            else []
        )

        pending_thought_parts: list[types.Part] = []
        for part in candidate_parts:
            if part.function_call is not None:
                fc = part.function_call
                call_id = fc.id or f"call_{uuid4().hex[:8]}"
                args = fc.args if isinstance(fc.args, dict) else {}
                thought_sig = getattr(part, "thought_signature", None)

                tool_calls.append(
                    ToolCallRequest(
                        id=call_id,
                        name=fc.name,
                        arguments=args,
                        thought_signature=thought_sig,
                        raw_part=part,
                        thought_parts=list(pending_thought_parts),
                    )
                )
                pending_thought_parts.clear()
            else:
                pending_thought_parts.append(part)

        # Fallback if function_calls convenience attribute has calls not in candidate_parts
        if not tool_calls and response.function_calls:
            for fc in response.function_calls:
                call_id = fc.id or f"call_{uuid4().hex[:8]}"
                args = fc.args if isinstance(fc.args, dict) else {}
                tool_calls.append(
                    ToolCallRequest(
                        id=call_id,
                        name=fc.name,
                        arguments=args,
                    )
                )

        # Extract text content directly from candidate parts
        content_text: str | None = None
        finish_reason = "stop"
        if response.candidates and response.candidates[0].content:
            text_parts = [
                part.text
                for part in (response.candidates[0].content.parts or [])
                if getattr(part, "text", None) is not None
            ]
            if text_parts:
                content_text = "".join(text_parts)
            if response.candidates[0].finish_reason:
                raw_fr = response.candidates[0].finish_reason
                fr_str = getattr(raw_fr, "value", str(raw_fr)).lower()
                finish_reason = fr_str.split(".")[-1]

        if tool_calls:
            finish_reason = "tool_calls"

        usage: dict[str, int] = {}
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
