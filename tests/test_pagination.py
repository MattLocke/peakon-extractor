import pytest
import respx
import httpx

from peakon_ingest.http import PeakonClient
from peakon_ingest.pagination import paginate_json


@pytest.mark.asyncio
async def test_paginate_chases_links_next():
    client = PeakonClient("https://example.com/api/v1", app_token="x", timeout_seconds=2)

    async def fake_ensure():
        return "bearer"

    client.ensure_bearer = fake_ensure  # type: ignore

    with respx.mock(assert_all_called=True) as mock:
        def responder(request: httpx.Request) -> httpx.Response:
            continuation = request.url.params.get("continuation")
            if continuation == "2":
                return httpx.Response(
                    200,
                    json={"data": [{"id": "2"}], "links": {}},
                )
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "1"}],
                    "links": {
                        "next": "https://example.com/api/v1/answers/export?continuation=2"
                    },
                },
            )

        route = mock.route(method="GET", url="https://example.com/api/v1/answers/export").mock(side_effect=responder)

        pages = []
        async for page in paginate_json(client, "/answers/export"):
            pages.append(page)

        assert len(pages) == 2
        assert pages[0]["data"][0]["id"] == "1"
        assert pages[1]["data"][0]["id"] == "2"
        assert route.call_count == 2

    await client.aclose()
