from __future__ import annotations

from typing import Any

from raven.contracts import Item

_MEANINGFUL_FIELDS = ("title", "content", "url", "author", "metadata")


def diff_items(previous: Item | None, current: Item) -> dict[str, Any]:
    if previous is None:
        return {"_new": True}

    diff: dict[str, Any] = {}
    for field in _MEANINGFUL_FIELDS:
        before = getattr(previous, field)
        after = getattr(current, field)
        if before != after:
            diff[field] = {"before": before, "after": after}
    return diff
