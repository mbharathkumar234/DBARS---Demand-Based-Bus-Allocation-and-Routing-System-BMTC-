"""Guards for conductor ticketing, Shakti counting and pass verification.

These are the tests that guard money. The failure modes are quiet ones: a
replayed offline batch that double-counts revenue, a Shakti ticket whose claim
value gets folded into cash takings, a pass that verifies because its id does
not happen to end in "FAIL". None of them raise; all of them misstate a figure
someone will eventually file with the state.

The pricing and verification logic is tested directly rather than through the
API, so these run without MongoDB -- the same way test_votes.py tests vote
ranking on fixture data.
"""

from __future__ import annotations

import pytest

from app.auth.auth import (
    TOKEN_TYPE_PASS,
    create_access_token,
    create_pass_token,
    create_ticket_token,
    decode_pass_token,
)
from app.models.waybill import PassengerType, PaymentMode
from app.services.waybill_service import (
    CONCESSION_MULTIPLIERS,
    ZERO_FARE_TYPES,
    WaybillError,
    price_ticket,
)


class _FakeRequest:
    """get_fare() needs a request only to reach the app's predictor."""

    def __init__(self, app):
        self.app = app


@pytest.fixture(scope="module")
def priced_request():
    from types import SimpleNamespace

    from app.core.config import settings
    from app.ml.predictor import BMTCBusPredictor

    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    predictor.train()
    return _FakeRequest(SimpleNamespace(state=SimpleNamespace(predictor=predictor)))


# ── Shakti: value vs collection ─────────────────────────────────────────────
def test_shakti_ticket_is_free_to_rider_and_claimable_by_bmtc(priced_request):
    """The distinction the whole feature rests on. A Shakti journey costs the
    passenger nothing and costs BMTC the full fare, which the state reimburses
    -- so both numbers must exist and must not be the same number."""
    pricing = price_ticket(
        "Majestic", "Marathahalli", [(PassengerType.SHAKTI, 2)], priced_request
    )

    assert pricing["fare_collected_inr"] == 0.0
    assert pricing["fare_value_inr"] > 0
    line = pricing["lines"][0]
    assert line["is_zero_fare"] is True
    assert line["scheme"] == "shakti"
    assert line["fare_value_inr"] == pytest.approx(pricing["adult_stage_fare_inr"] * 2)


def test_revenue_and_claim_are_separable_on_a_mixed_sale(priced_request):
    """A conductor sells to a paying adult and a Shakti passenger in one
    transaction. Revenue reporting must see one fare; the reimbursement claim
    must see the other."""
    pricing = price_ticket(
        "Majestic", "Marathahalli",
        [(PassengerType.ADULT, 1), (PassengerType.SHAKTI, 1)],
        priced_request,
    )
    adult = next(line for line in pricing["lines"] if line["passenger_type"] == "adult")
    shakti = next(line for line in pricing["lines"] if line["passenger_type"] == "shakti")

    assert pricing["fare_collected_inr"] == pytest.approx(adult["fare_value_inr"])
    assert pricing["fare_value_inr"] == pytest.approx(
        adult["fare_value_inr"] + shakti["fare_value_inr"]
    )
    # Conflating them would overstate revenue by exactly the claim.
    assert pricing["fare_value_inr"] > pricing["fare_collected_inr"]


def test_concessions_apply_to_value_and_are_still_collected(priced_request):
    pricing = price_ticket(
        "Majestic", "Marathahalli", [(PassengerType.STUDENT, 1)], priced_request
    )
    line = pricing["lines"][0]
    assert line["fare_value_inr"] == pytest.approx(
        pricing["adult_stage_fare_inr"] * CONCESSION_MULTIPLIERS[PassengerType.STUDENT], abs=0.01
    )
    # A concession is a discount, not a scheme: the passenger still pays.
    assert line["is_zero_fare"] is False
    assert line["fare_collected_inr"] == line["fare_value_inr"]
    assert line["scheme"] is None


def test_only_scheme_travel_is_zero_fare():
    """A concession that silently became zero-fare would quietly turn discount
    travel into a reimbursement claim against the state."""
    assert ZERO_FARE_TYPES == {PassengerType.SHAKTI}


def test_an_unrecognised_stop_is_refused_rather_than_priced_by_guess(priced_request):
    """get_fare() fuzzy-matches and prices anything, logging a warning. That is
    defensible for a commuter e-ticket -- the rider picked both stops from
    autocomplete and can see them. It is not defensible for a cash sale on a
    bus, so this path refuses instead, and names what it thought was meant."""
    with pytest.raises(WaybillError, match="Could not confidently identify"):
        price_ticket(
            "Nowhere At All", "Somewhere Else Entirely",
            [(PassengerType.ADULT, 1)], priced_request,
        )


def test_a_colloquial_stop_name_still_prices(priced_request):
    """The confidence gate must not reject the names riders actually use.
    "Majestic" is an alias for Kempegowda Bus Station and has to work."""
    pricing = price_ticket("Majestic", "Marathahalli", [(PassengerType.ADULT, 1)], priced_request)
    assert pricing["fare_collected_inr"] > 0
    # The conductor's screen shows what was priced, not just what was typed.
    assert pricing["resolved_from"] and pricing["resolved_to"]


def test_pricing_uses_the_shared_fare_table(priced_request):
    """A second pricing path here would drift from the commuter e-ticket's, and
    two fare answers for the same journey is how a fare system starts lying."""
    from app.core.fares import get_fare

    pricing = price_ticket("Majestic", "Marathahalli", [(PassengerType.ADULT, 1)], priced_request)
    assert pricing["adult_stage_fare_inr"] == pytest.approx(
        get_fare("Majestic", "Marathahalli", priced_request, False)
    )


# ── passes: real verification ───────────────────────────────────────────────
def test_a_signed_pass_verifies_offline():
    token = create_pass_token(
        {"pass_id": "BP-202608-ABC123", "holder_name": "A. Rider", "pass_type": "Student Monthly"},
        expires_seconds=30 * 86400,
    )
    payload = decode_pass_token(token)
    assert payload["pass_id"] == "BP-202608-ABC123"
    assert payload["type"] == TOKEN_TYPE_PASS


def test_a_tampered_pass_is_rejected():
    """The check the old stub never performed: it computed an HMAC and then
    decided validity from whether the id ended in "FAIL"."""
    from fastapi import HTTPException

    token = create_pass_token({"pass_id": "BP-1", "holder_name": "A"}, expires_seconds=86400)
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{'a' * len(signature)}"

    with pytest.raises(HTTPException):
        decode_pass_token(forged)


def test_an_expired_pass_is_rejected_without_a_network_call():
    from fastapi import HTTPException

    token = create_pass_token({"pass_id": "BP-OLD"}, expires_seconds=-1)
    with pytest.raises(HTTPException):
        decode_pass_token(token)


def test_pass_tokens_are_a_separate_domain_from_sessions_and_tickets():
    """Three keys, three types. A pass is a long-lived bearer credential cached
    on a shared device in a bus -- it must not be able to become a session."""
    from fastapi import HTTPException

    session = create_access_token("u1", "a@b.c", "commuter", "A")
    ticket = create_ticket_token({"ticket_id": "T1"}, 600)

    for foreign in (session, ticket):
        with pytest.raises(HTTPException):
            decode_pass_token(foreign)


def test_demo_mode_is_off_by_default_and_labels_itself():
    from app.services.pass_service import demo_mode_enabled, demo_verify

    assert demo_mode_enabled() is False
    result = demo_verify("ANYTHING", conductor_id="C1", route_id="500-D")
    # A demo result must be impossible to mistake for a real verification.
    assert result["demo_mode"] is True
    assert "DEMO" in result["verification_mode"]


# ── payment modes ───────────────────────────────────────────────────────────
def test_payment_modes_cover_the_scheme_case():
    """Scheme travel where nothing changes hands still needs a payment mode, or
    it lands in the cash column by default."""
    assert PaymentMode.FREE.value == "free"
    assert {mode.value for mode in PaymentMode} >= {"cash", "upi", "pass", "free"}
