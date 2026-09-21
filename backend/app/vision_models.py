"""Typed Stage 3 Vision contracts.

Vision output is a user-triggered, inference-only description of directly visible
scene/object/activity candidates. Provider output never supplies arbitrary descriptive
text to the public contract; the service maps a bounded observation code to its label.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

VisionObservationKind = Literal["SCENE", "OBJECT", "ACTIVITY"]
VisionObservationCode = Literal[
    "INDOOR",
    "OUTDOOR",
    "ROOM",
    "OFFICE_LIKE",
    "KITCHEN_LIKE",
    "STREET_LIKE",
    "VEHICLE_INTERIOR",
    "NATURE",
    "RETAIL_LIKE",
    "OTHER_VISIBLE_SCENE",
    "PERSON",
    "ANIMAL",
    "VEHICLE",
    "FURNITURE",
    "ELECTRONIC_DEVICE",
    "BAG",
    "BOOK_OR_DOCUMENT",
    "CONTAINER",
    "FOOD_OR_DRINK",
    "TOOL",
    "CLOTHING",
    "PLANT",
    "SIGN_OR_DISPLAY",
    "OTHER_VISIBLE_OBJECT",
    "PERSON_STANDING",
    "PERSON_SITTING",
    "PERSON_WALKING",
    "PERSON_RUNNING",
    "PERSON_EATING_OR_DRINKING",
    "PERSON_READING",
    "PERSON_WRITING",
    "PERSON_COOKING",
    "PERSON_DRIVING",
    "PERSON_CYCLING",
    "PERSON_USING_DEVICE",
    "PERSON_HOLDING_OBJECT",
    "PERSON_INTERACTING_WITH_OBJECT",
    "OTHER_VISIBLE_ACTIVITY",
]


class VisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID


class VisionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, le=49)
    kind: VisionObservationKind
    code: VisionObservationCode
    label: str = Field(min_length=1, max_length=80)
    trust_class: Literal["inference"] = "inference"


class VisionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_media_id: UUID
    gateway_request_id: str
    provider_request_id: str | None = None
    provider: str
    model: str
    purpose: Literal["vision.observe"] = "vision.observe"
    trust_class: Literal["inference"] = "inference"
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    observations: list[VisionObservation] = Field(default_factory=list, max_length=50)
    provenance: VisionProvenance
