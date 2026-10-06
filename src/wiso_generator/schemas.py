from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mime_type: str
    data_base64: str
    name: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str


class JsonSchemaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    schema_: dict[str, Any] = Field(alias="schema")


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^wiso_[A-Za-z0-9_-]+$")
    task_type: str = Field(min_length=1, max_length=80)
    tier: Literal["luna", "terra", "sol"]
    model: str
    messages: list[Message] = Field(min_length=1, max_length=20)
    attachments: list[Attachment] = Field(default_factory=list, max_length=8)
    temperature: float = 1.0
    max_tokens: int = Field(default=4096, ge=256, le=8192)
    json_schema: JsonSchemaSpec | None = None


class GenerateResponse(BaseModel):
    request_id: str
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    model: str


class BatchGenerateRequest(BaseModel):
    """A batch of structured generation calls sharing one WISO request id."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^wiso_[A-Za-z0-9_-]+$")
    requested_count: int = Field(ge=1, le=500)
    accepted_count: int = Field(default=0, ge=0)
    items: list[GenerateRequest] = Field(min_length=1)


class BatchItemResult(BaseModel):
    index: int
    ok: bool
    response: GenerateResponse | None = None
    error: str | None = None


class BatchGenerateResponse(BaseModel):
    request_id: str
    requested_count: int
    accepted_count: int
    remaining_count: int
    succeeded: int
    failed: int
    items: list[BatchItemResult]

class CurriculumAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^wiso_[A-Za-z0-9_-]+$")
    subject_name: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    pdf_base64: str = Field(min_length=20)

class CurriculumConcept(BaseModel):
    title: str
    description: str = ""
    source_page: int | None = None

class CurriculumLesson(BaseModel):
    title: str
    page_start: int | None = None
    page_end: int | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_review: bool = False
    concepts: list[CurriculumConcept] = Field(default_factory=list)

class CurriculumUnit(BaseModel):
    title: str
    page_start: int | None = None
    page_end: int | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_review: bool = False
    lessons: list[CurriculumLesson] = Field(default_factory=list)

class CurriculumAnalyzeResponse(BaseModel):
    request_id: str
    page_count: int
    pages: list[dict[str, Any]]
    units: list[CurriculumUnit]
    analysis_version: str = "wiso-curriculum-v1"
