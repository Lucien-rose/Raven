from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from raven.contracts import Item, SourceBinding


class FetchBatch(BaseModel):
    items: list[Item] = Field(default_factory=list)
    cursor: str | None = None


class SourceAdapter(Protocol):
    async def fetch(self, source: SourceBinding, cursor: str | None = None) -> FetchBatch: ...
