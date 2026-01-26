from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _extract_token(payload: Any) -> Optional[str]:
    """Extract bearer token from Peakon auth response.

    The JS reference implementation (index.js) expects the token at:
      response.data.data.id

    So the primary supported shape is:
      { "data": { "id": "<bearer-token>", ... } }

    We also keep a few fallback patterns for robustness.
    """
    if payload is None:
        return None

    # Some APIs return token as plain text
    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    if not isinstance(payload, dict):
        return None

    # 1) Peakon shape used by index.js: payload.data.id
    data = payload.get("data")
    if isinstance(data, dict):
        v = data.get("id")
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v).strip()

    # 2) Common alternative keys (fallback)
    for k in ("token", "access_token", "bearer_token", "bearerToken"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 3) Nested attributes fallbacks
    if isinstance(data, dict):
        attrs = data.get("attributes")
        if isinstance(attrs, dict):
            for k in ("token", "access_token", "bearer_token", "bearerToken"):
                v = attrs.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    attrs = payload.get("attributes")
    if isinstance(attrs, dict):
        for k in ("token", "access_token", "bearer_token", "bearerToken"):
            v = attrs.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return None


async def fetch_bearer_token(client: httpx.AsyncClient, base_url: str, app_token: str) -> str:
    """Exchange an application token for a bearer token.

    Mirrors the JS script (index.js):
      - POST /auth/application
      - Content-Type: application/json
      - body: { token: <APP_TOKEN> }
      - return payload.data.id
    """
    url = f"{base_url.rstrip('/')}/auth/application"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    resp = await client.post(url, json={"token": app_token}, headers=headers)
    resp.raise_for_status()

    payload = resp.json()
    token = _extract_token(payload)

    if not token:
        top_keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        raise RuntimeError(
            "Auth response did not include a recognizable bearer token. "
            "Expected JSON like {'data': {'id': '<bearer-token>'}}. "
            f"Top-level keys/type: {top_keys}"
        )

    logger.info("Fetched bearer token via /auth/application.")
    return token
