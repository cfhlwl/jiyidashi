"""Typed API contract for explicit user-owned Memory feedback."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.memory_feedback_models import MemoryFeedbackAction


class MemoryFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryFeedbackAction
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def validate_action_payload(self):
        correction_fields = self.model_fields_set.intersection({"title", "content"})
        if self.action == MemoryFeedbackAction.CORRECT:
            if not correction_fields:
                raise ValueError("CORRECT requires title and/or content")
            if "content" in correction_fields:
                if self.content is None or not self.content.strip():
                    raise ValueError("content must not be empty")
        elif correction_fields:
            raise ValueError("CONFIRM/DELETE do not accept correction fields")
        return self


class MemoryFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    memory_id: UUID
    memory_revision: int
    result_revision: int | None
    action: MemoryFeedbackAction
    created_at: datetime
