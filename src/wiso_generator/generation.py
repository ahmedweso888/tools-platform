from __future__ import annotations

import asyncio
import json

from .errors import AgentError
from .logging import log_event
from .provider import OpenAIResponsesProvider
from .schemas import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    BatchItemResult,
    GenerateRequest,
    GenerateResponse,
)


class GenerationService:
    def __init__(self, provider: OpenAIResponsesProvider) -> None:
        self.provider = provider

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        response = await self.provider.generate(request)
        if request.json_schema:
            # Force a machine-readable contract at the service boundary.
            json.loads(response.text)
        return response

    async def generate_batch(
        self, request: BatchGenerateRequest, max_concurrency: int
    ) -> BatchGenerateResponse:
        """Runs a bounded, concurrent batch. Item failures never fail the batch."""
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run(index: int, item: GenerateRequest) -> BatchItemResult:
            async with semaphore:
                try:
                    return BatchItemResult(index=index, ok=True, response=await self.generate(item))
                except AgentError as exc:
                    log_event(request.request_id, "batch_item_failed", index=index, error=str(exc))
                    return BatchItemResult(index=index, ok=False, error=str(exc))
                except ValueError:
                    log_event(request.request_id, "batch_item_invalid_output", index=index)
                    return BatchItemResult(index=index, ok=False, error="invalid_structured_output")

        results = await asyncio.gather(*(run(i, item) for i, item in enumerate(request.items)))
        succeeded = sum(1 for r in results if r.ok)
        return BatchGenerateResponse(
            request_id=request.request_id,
            requested_count=request.requested_count,
            accepted_count=request.accepted_count,
            remaining_count=max(0, request.requested_count - request.accepted_count),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            items=list(results),
        )
