from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from .http import PeakonClient

logger = logging.getLogger(__name__)


def _get_next_link(payload: Dict[str, Any]) -> Optional[str]:
    links = payload.get("links")
    if isinstance(links, dict):
        nxt = links.get("next")
        if isinstance(nxt, str) and nxt.strip():
            return nxt.strip()
    return None


def _split_url(full_url: str, base_url: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Split a next-link URL into a path and params suitable for PeakonClient.

    Handles both absolute and relative URLs and avoids duplicating the API path
    segment already present in PeakonClient.base_url (e.g. `/api/v1`).
    """
    parsed = urlparse(full_url)
    path = parsed.path

    if base_url:
        base_parsed = urlparse(base_url)
        base_path = base_parsed.path.rstrip("/")
        if base_path:
            base_prefix = base_path.lstrip("/")
            path_no_lead = path.lstrip("/")
            # If the next-link path already includes the base API prefix, strip it
            # so that PeakonClient does not end up with `/api/v1/api/v1/...`.
            if path_no_lead == base_prefix:
                path = "/"
            elif path_no_lead.startswith(base_prefix + "/"):
                path = "/" + path_no_lead[len(base_prefix) + 1 :]

    qs = parse_qs(parsed.query)
    params: Dict[str, Any] = {k: v[-1] if isinstance(v, list) else v for k, v in qs.items()}
    return path, params


async def paginate_json(
    client: PeakonClient,
    first_url: str,
    *,
    first_params: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield each page JSON by chasing links.next."""
    url = first_url
    params = dict(first_params or {})

    page_num = 0
    while True:
        page_num += 1
        payload = await client.get_json_with_reauth_on_401(url, params=params)
        logger.info("Fetched page %s for %s", page_num, first_url)
        yield payload

        nxt = _get_next_link(payload)
        if not nxt:
            break

        # Normalize next links (absolute or relative) against the client's base URL
        # so that we don't duplicate the API prefix (e.g. `/api/v1`).
        url, params = _split_url(nxt, client.base_url)
