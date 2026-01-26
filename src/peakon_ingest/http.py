from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from .auth import fetch_bearer_token

logger = logging.getLogger(__name__)


def _should_retry_exception(exc: BaseException) -> bool:  # type: ignore[name-defined]
    """Return True for retryable exceptions (network, timeouts, 5xx, 429)."""
    if isinstance(exc, (httpx.TransportError, httpx.ReadTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        status = exc.response.status_code
        return status >= 500 or status == 429
    return False


class PeakonClient:
    def __init__(self, base_url: str, app_token: str | None, timeout_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token
        self.timeout_seconds = timeout_seconds
        self._bearer_token: str | None = None

        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ensure_bearer(self) -> str:
        if self._bearer_token:
            return self._bearer_token
        if not self.app_token:
            raise RuntimeError("PEAKON_APP_TOKEN is required to authenticate.")
        self._bearer_token = await fetch_bearer_token(self._client, self.base_url, self.app_token)
        return self._bearer_token

    def set_bearer(self, token: str) -> None:
        self._bearer_token = token

    async def _request(self, method: str, url: str, *, headers: Optional[Dict[str, str]] = None, **kwargs) -> httpx.Response:
        hdrs = dict(headers or {})
        if not url.startswith("http"):
            url = f"{self.base_url}/{url.lstrip('/')}"  # join

        bearer = await self.ensure_bearer()
        hdrs["Authorization"] = f"Bearer {bearer}"
        hdrs.setdefault("Accept", "application/json")

        return await self._client.request(method, url, headers=hdrs, **kwargs)

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30), retry=retry_if_exception(_should_retry_exception), reraise=True)  # type: ignore[arg-type]
    async def get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = await self._request("GET", url, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Let retry handle 429/5xx; but still include body in logs for debugging
            logger.warning("HTTP error %s for %s: %s", resp.status_code, resp.url, resp.text[:500])
            raise e
        return resp.json()

    async def get_json_with_reauth_on_401(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return await self.get_json(url, params=params)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 401:
                logger.info("401 received; re-authenticating and retrying once...")
                # refresh bearer and retry once
                self._bearer_token = None
                await self.ensure_bearer()
                return await self.get_json(url, params=params)
            raise
