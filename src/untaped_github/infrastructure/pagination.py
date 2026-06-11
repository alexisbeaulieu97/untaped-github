"""Link-header pagination for GitHub's REST API.

GitHub paginates list and search endpoints with an ``RFC 5988 Link``
response header (``Link: <url>; rel="next", <url>; rel="last"``). The
``next`` URL is absolute and carries every cursor parameter the server
needs to resume; we follow it verbatim until exhausted or the caller's
``limit`` is reached.

Only the GitHub-specific knowledge lives here: parsing the ``Link``
header and the ``items``-envelope vs raw-array payload shapes. The loop
itself — limit handling, the cursor-cycle guard, and the page-count cap —
is core's ``paginate_pages``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from untaped.api import HttpClient, paginate_pages

_NEXT_LINK = re.compile(r'<(?P<url>[^>]+)>;\s*rel="next"')


def _parse_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = _NEXT_LINK.search(link_header)
    return match.group("url") if match else None


def _paginate(
    http: HttpClient,
    path: str,
    *,
    params: dict[str, str],
    per_page: int,
    limit: int | None,
    extract: str | None,
) -> Iterator[dict[str, Any]]:
    # When the caller wants fewer rows than a full page, ask GitHub for
    # exactly that many on the first request; ``next`` URLs carry their
    # own cursor parameters and are followed verbatim.
    first_page = min(per_page, limit) if limit is not None else per_page
    first_params = {**params, "per_page": str(first_page)}

    def fetch(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        response = http.get(cursor or path, params=first_params if cursor is None else None)
        payload = response.json()
        items = payload[extract] if extract is not None else payload
        if not isinstance(items, list):
            # A 200 with a non-list body short-circuits gracefully —
            # defensive against odd error envelopes.
            return [], None
        return items, _parse_next(response.headers.get("link"))

    return paginate_pages(fetch, limit=limit)


def paginate_search(
    http: HttpClient,
    path: str,
    *,
    params: dict[str, str],
    per_page: int = 100,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows from a GitHub ``/search/*`` endpoint.

    Search payloads nest results under ``items``; total counts and the
    ``incomplete_results`` flag are ignored — callers that need them
    can issue the request manually.
    """
    return _paginate(http, path, params=params, per_page=per_page, limit=limit, extract="items")


def paginate_list(
    http: HttpClient,
    path: str,
    *,
    params: dict[str, str] | None = None,
    per_page: int = 100,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows from a non-search list endpoint (raw JSON array body)."""
    return _paginate(
        http, path, params=dict(params or {}), per_page=per_page, limit=limit, extract=None
    )
