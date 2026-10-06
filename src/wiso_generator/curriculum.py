from __future__ import annotations

import base64
import io
import json

from pypdf import PdfReader

from .errors import ProviderError
from .provider import OpenAIResponsesProvider
from .schemas import CurriculumAnalyzeRequest, CurriculumAnalyzeResponse

CURRICULUM_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "page_start": {"type": ["integer", "null"]},
                    "page_end": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                    "needs_review": {"type": "boolean"},
                    "lessons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "page_start": {"type": ["integer", "null"]},
                                "page_end": {"type": ["integer", "null"]},
                                "confidence": {"type": "number"},
                                "needs_review": {"type": "boolean"},
                                "concepts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "description": {"type": "string"},
                                            "source_page": {"type": ["integer", "null"]},
                                        },
                                        "required": ["title", "description", "source_page"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["title", "page_start", "page_end", "confidence", "needs_review", "concepts"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "page_start", "page_end", "confidence", "needs_review", "lessons"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["units"],
    "additionalProperties": False,
}


async def analyze_curriculum(request: CurriculumAnalyzeRequest, provider: OpenAIResponsesProvider) -> CurriculumAnalyzeResponse:
    try:
        raw = base64.b64decode(request.pdf_base64, validate=True)
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError("invalid_pdf") from exc
    pages: list[dict[str, object]] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({"page_number": number, "text": text})
    toc_text = "\n".join(f"PAGE {p['page_number']}: {str(p['text'])[:1800]}" for p in pages[:40])
    full_text = "\n\n".join(f"PAGE {p['page_number']}\n{p['text']}" for p in pages)
    # Keep the document bounded while retaining TOC/headings first.
    if len(full_text) > 120000:
        full_text = full_text[:120000]
    from .schemas import Message, GenerateRequest, JsonSchemaSpec
    generation = GenerateRequest(
        request_id=request.request_id,
        task_type="curriculum_analysis",
        tier="luna",
        model="openai/gpt-5.6-luna",
        messages=[
            Message(role="system", content="Analyze the actual book structure. Prefer table of contents, headings and printed page numbers. Never invent lessons. Mark low-confidence results needs_review=true. Return only structured JSON."),
            Message(role="user", content=f"Subject: {request.subject_name}\nFilename: {request.filename}\nTABLE/HEADINGS SAMPLE:\n{toc_text}\nDOCUMENT:\n{full_text}"),
        ],
        max_tokens=8192,
        json_schema=JsonSchemaSpec(name="curriculum_analysis", schema=CURRICULUM_SCHEMA),
    )
    result = await provider.generate(generation)
    data = json.loads(result.text)
    return CurriculumAnalyzeResponse(request_id=request.request_id, page_count=len(pages), pages=pages, units=data.get("units", []))
