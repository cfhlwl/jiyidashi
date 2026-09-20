"""Typed control-plane contract for deterministic intent routing.

These values describe where a request may be sent; they are never Memory/Evidence
and must not be persisted as personal facts.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IntentKind(StrEnum):
    FIND_OBJECT = "FIND_OBJECT"
    FIND_PLACE = "FIND_PLACE"
    FIND_EVENT = "FIND_EVENT"
    MEMORY_SEARCH = "MEMORY_SEARCH"
    UNKNOWN = "UNKNOWN"


class IntentCapability(StrEnum):
    OBJECT_LOCATION_QUERY = "OBJECT_LOCATION_QUERY"
    PLACE_HISTORY_QUERY = "PLACE_HISTORY_QUERY"
    MEMORY_QUERY = "MEMORY_QUERY"


class IntentRouteReason(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    NO_SUPPORTED_RULE = "NO_SUPPORTED_RULE"


class IntentRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class IntentRouteResult(BaseModel):
    # Routing is control metadata only. It must never be persisted as a Memory
    # or treated as evidence about the user.
    intent: IntentKind
    capability: IntentCapability | None = None
    reason: IntentRouteReason
