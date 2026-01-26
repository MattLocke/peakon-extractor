from peakon_ingest.auth import _extract_token


def test_extract_token_variants():
    assert _extract_token({"token": "abc"}) == "abc"
    assert _extract_token({"access_token": "abc"}) == "abc"
    assert _extract_token({"data": {"attributes": {"token": "abc"}}}) == "abc"
    assert _extract_token("abc") == "abc"
