"""Token-type separation.

Regression cover for a real auth bypass: get_current_user used a deny-list
naming "refresh" and "ticket", but e-ticket QR tokens are actually typed
"qr_ticket", so the guard never matched and a ticket QR authenticated as a
user session. The guard is now an allow-list (only "access" passes) and
tickets are additionally signed with their own key, so a ticket fails at the
signature layer before the type is even considered.
"""
from __future__ import annotations

import pytest

from app.auth.auth import (
    SECRET_KEY,
    TICKET_SECRET_KEY,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_TICKET,
    create_access_token,
    create_refresh_token,
    create_ticket_token,
    decode_ticket_token,
    decode_token,
)


def test_ticket_and_auth_keys_are_distinct() -> None:
    """The two barriers must be independent, even with no env config set."""
    assert TICKET_SECRET_KEY != SECRET_KEY


def test_access_token_is_typed_access() -> None:
    payload = decode_token(create_access_token("u1", "a@b.c", "commuter", "A"))
    assert payload["type"] == TOKEN_TYPE_ACCESS


def test_refresh_token_is_typed_refresh() -> None:
    payload = decode_token(create_refresh_token("u1"))
    assert payload["type"] == TOKEN_TYPE_REFRESH


def test_ticket_token_roundtrips_under_the_ticket_key() -> None:
    token = create_ticket_token({"ticket_id": "t-1"}, 3600)
    payload = decode_ticket_token(token)
    assert payload["ticket_id"] == "t-1"
    assert payload["type"] == TOKEN_TYPE_TICKET


def test_ticket_token_does_not_verify_under_the_auth_key() -> None:
    """The exact bypass: a ticket QR must not be a valid session credential."""
    token = create_ticket_token({"ticket_id": "t-1"}, 3600)
    with pytest.raises(Exception):
        decode_token(token)  # auth key -> signature mismatch


def test_auth_signed_token_claiming_to_be_a_ticket_is_rejected() -> None:
    """Claiming type=qr_ticket isn't enough; it must be signed as one."""
    from app.auth.auth import create_token

    forged = create_token({"ticket_id": "x", "type": TOKEN_TYPE_TICKET}, 3600)
    with pytest.raises(Exception):
        decode_ticket_token(forged)


@pytest.mark.parametrize("token_type", [TOKEN_TYPE_REFRESH, TOKEN_TYPE_TICKET, "anything-new"])
def test_only_access_tokens_authenticate(token_type: str) -> None:
    """Allow-list behaviour: a future token type can't silently become a session."""
    from fastapi.testclient import TestClient

    from app.auth.auth import create_token
    from app.main import app

    token = create_token({"sub": "u1", "type": token_type}, 3600)
    with TestClient(app) as client:
        response = client.get("/votes/my", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
