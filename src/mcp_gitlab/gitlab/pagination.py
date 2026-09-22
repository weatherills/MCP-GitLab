"""GitLab offset-pagination metadata (PRD-00 section 10)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PageInfo:
    page: int | None = None
    per_page: int | None = None
    next_page: int | None = None
    prev_page: int | None = None
    total: int | None = None
    """Omitted by GitLab for very large collections, so it may be None even with more pages."""
    total_pages: int | None = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "PageInfo":
        return cls(
            page=_header_int(headers, "x-page"),
            per_page=_header_int(headers, "x-per-page"),
            next_page=_header_int(headers, "x-next-page"),
            prev_page=_header_int(headers, "x-prev-page"),
            total=_header_int(headers, "x-total"),
            total_pages=_header_int(headers, "x-total-pages"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "per_page": self.per_page,
            "next_page": self.next_page,
            "prev_page": self.prev_page,
            "total": self.total,
            "total_pages": self.total_pages,
            "has_more": self.next_page is not None,
        }


@dataclass(frozen=True, slots=True)
class Page:
    items: list[Any]
    info: PageInfo

    def to_dict(self) -> dict[str, Any]:
        return {"items": self.items, "pagination": self.info.to_dict()}


def _header_int(headers: Mapping[str, str], name: str) -> int | None:
    value = (headers.get(name) or "").strip()
    return int(value) if value.isdigit() else None
