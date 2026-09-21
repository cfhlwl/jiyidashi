"""Typed Stage 3 OCR contracts.

OCR output is derived from a user-selected image and is always inference metadata.
It is not a confirmed fact and is never persisted by the OCR foundation.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OCRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID


class OCRBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, le=199)
    text: str = Field(min_length=1, max_length=4000)


class OCRProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_media_id: UUID
    gateway_request_id: str
    provider_request_id: str | None = None
    provider: str
    model: str
    purpose: Literal["ocr.extract"] = "ocr.extract"
    trust_class: Literal["inference"] = "inference"
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class OCRResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    text: str = Field(max_length=20000)
    blocks: list[OCRBlock] = Field(default_factory=list, max_length=200)
    provenance: OCRProvenance
