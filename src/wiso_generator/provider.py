from __future__ import annotations

import time
from typing import Any

import httpx

from .config import ALLOWED_MODELS, REASONING, Settings
from .errors import AgentConfigurationError, ProviderError
from .logging import log_event
from .schemas import GenerateRequest, GenerateResponse


class OpenAIResponsesProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        model = ALLOWED_MODELS.get(request.model)
        if not model:
            raise ProviderError("unsupported_model")
        if request.tier == "sol" and model != "gpt-5.6-sol":
            raise ProviderError("tier_model_mismatch")
        if request.tier == "terra" and model != "gpt-5.6-terra":
            raise ProviderError("tier_model_mismatch")
        if request.tier == "luna" and model != "gpt-5.6-luna":
            raise ProviderError("tier_model_mismatch")
        if not self.settings.openai_api_key:
            raise AgentConfigurationError("OPENAI_API_KEY is not configured")

        content: list[dict[str, Any]] = []
        for message in request.messages:
            content.append({"role": message.role, "content": message.content})
        # The current WISO contract primarily uses text/structured requests.
        # Image attachments are passed as data URLs in the final user message.
        if request.attachments:
            last = content[-1]
            if last["role"] == "user":
                parts: list[dict[str, Any]] = [{"type": "input_text", "text": last["content"]}]
                for attachment in request.attachments:
                    parts.append({
                        "type": "input_image",
                        "image_url": f"data:{attachment.mime_type};base64,{attachment.data_base64}",
                    })
                last["content"] = parts

        body: dict[str, Any] = {
            "model": model,
            "input": content,
            "max_output_tokens": request.max_tokens,
            "reasoning": {"effort": REASONING[model]},
        }
        if request.json_schema:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.json_schema.name,
                    "schema": request.json_schema.schema_,
                    "strict": True,
                }
            }

        started = time.perf_counter()
        timeout = httpx.Timeout(self.settings.request_timeout_seconds, connect=10.0)
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
            "X-WISO-Request-ID": request.request_id,
        }
        log_event(request.request_id, "provider_start", model=model, tier=request.tier)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.settings.openai_base_url}/responses",
                    headers=headers,
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("openai_timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai_transport_error:{type(exc).__name__}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            detail = response.text[:800].replace("\n", " ")
            raise ProviderError(f"openai_http_{response.status_code}:{detail}")

        payload = response.json()
        text = payload.get("output_text")
        if not isinstance(text, str):
            # Fallback for compatible response payloads that omit output_text.
            chunks: list[str] = []
            for item in payload.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
            text = "".join(chunks)
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        log_event(request.request_id, "provider_complete", model=model, latency_ms=latency_ms, total_tokens=total_tokens)
        return GenerateResponse(
            request_id=request.request_id,
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            model=model,
        )
