"""Twilio webhook signature verification.

POST /sms/webhook runs the full prediction pipeline (two O(n) stop-resolution
scans plus a graph search), so it must only be callable by Twilio. These tests
pin both directions: a genuine signature is accepted, and everything else --
missing, wrong, or tampered-with -- is refused.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app.api import sms
from app.api.sms import _expected_twilio_signature
from app.main import app

AUTH_TOKEN = "test-twilio-auth-token"
WEBHOOK_URL = "http://testserver/sms/webhook"


@pytest.fixture(scope="module")
def client():
    """One client for the module -- app startup trains the predictor, which is
    far too slow to repeat per test."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def twilio_configured(monkeypatch: pytest.MonkeyPatch):
    """Point the sms module at a known auth token for one test.

    Settings is a frozen dataclass, so the token can't be assigned in place --
    swap in a modified copy on the module that reads it instead.
    """
    monkeypatch.setattr(
        sms, "settings", dataclasses.replace(sms.settings, twilio_auth_token=AUTH_TOKEN)
    )
    yield


def _sign(params: dict[str, str], token: str = AUTH_TOKEN, url: str = WEBHOOK_URL) -> str:
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    ).decode()


def test_signature_matches_twilios_documented_scheme() -> None:
    """Our helper reproduces Twilio's url + sorted(k+v) + HMAC-SHA1 + base64."""
    params = {"Body": "Majestic to Whitefield", "From": "+919999999999"}
    assert _expected_twilio_signature(WEBHOOK_URL, params, AUTH_TOKEN) == _sign(params)


def test_valid_signature_is_accepted(client, twilio_configured) -> None:
    params = {"Body": "Majestic to Whitefield", "From": "+919999999999"}
    response = client.post(
        "/sms/webhook", data=params, headers={"X-Twilio-Signature": _sign(params)}
    )
    assert response.status_code == 200
    assert "<Response><Message>" in response.text


def test_tampered_body_is_rejected(client, twilio_configured) -> None:
    """A signature valid for one body must not authorise a different one."""
    signed = {"Body": "Majestic to Whitefield", "From": "+919999999999"}
    tampered = {"Body": "Silk Board to Marathahalli", "From": "+919999999999"}
    response = client.post(
        "/sms/webhook", data=tampered, headers={"X-Twilio-Signature": _sign(signed)}
    )
    assert response.status_code == 403


def test_missing_signature_is_rejected(client, twilio_configured) -> None:
    response = client.post("/sms/webhook", data={"Body": "Majestic to Whitefield"})
    assert response.status_code == 403


def test_unconfigured_token_refuses_rather_than_falls_open(client) -> None:
    """With no TWILIO_AUTH_TOKEN we cannot verify anything, so we must refuse."""
    response = client.post(
        "/sms/webhook",
        data={"Body": "Majestic to Whitefield"},
        headers={"X-Twilio-Signature": "anything"},
    )
    assert response.status_code == 503
