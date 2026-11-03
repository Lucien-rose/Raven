from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from raven.contracts import CandidateContext


class CandidateReadyEvent(BaseModel):
    type: str = "candidate.ready"
    candidate: CandidateContext


class EventDispatcher(Protocol):
    async def publish(self, event: CandidateReadyEvent) -> None: ...
