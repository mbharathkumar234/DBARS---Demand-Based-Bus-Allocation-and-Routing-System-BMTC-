"""Guards for Shakti scheme eligibility and the free e-ticket it produces.

The scheme is money: every free ticket is an amount BMTC bills the state for.
That makes the failure modes financial rather than functional. Charging an
entitled passenger is the visible one. The quiet ones are worse -- a free
ticket whose claim value was never recorded (BMTC absorbs the cost silently),
or a chargeable AC journey counted into the claim (BMTC bills the state for
money it already took from the passenger).
"""

from __future__ import annotations

import pytest

from app.core.shakti import (
    DISCLOSURE,
    SCHEME_NAME,
    SHAKTI_ELIGIBLE_GENDERS,
    Gender,
    is_shakti_eligible,
)
from app.models.tickets import TicketResponse
from app.models.waybill import PassengerType
from app.services.waybill_service import price_ticket


# ── eligibility rule ────────────────────────────────────────────────────────
def test_women_and_transgender_passengers_travel_free():
    """Transgender passengers are covered by the scheme as enacted, not as an
    extension of it. Omitting them would implement a stricter rule than the
    one that exists."""
    assert SHAKTI_ELIGIBLE_GENDERS == {Gender.FEMALE.value, Gender.TRANSGENDER.value}
    assert is_shakti_eligible("female")[0] is True
    assert is_shakti_eligible("transgender")[0] is True


def test_other_passengers_pay_and_are_not_told_why():
    """A male passenger is not "denied" free travel -- the scheme simply does
    not apply, and returning an explanation would imply he was assessed."""
    eligible, reason = is_shakti_eligible("male")
    assert eligible is False
    assert reason is None


def test_ac_services_are_chargeable_for_everyone():
    """The real rule most likely to surprise: the scheme covers ordinary
    services only. Vajra (AC) and Vayu Vajra (airport) are paid by all."""
    eligible, reason = is_shakti_eligible("female", is_ac=True)
    assert eligible is False
    assert "non-AC" in reason


def test_an_account_without_a_gender_is_told_how_to_fix_it():
    eligible, reason = is_shakti_eligible(None)
    assert eligible is False
    assert "gender" in reason.lower()

    # "Prefer not to say" is a deliberate answer, and the scheme cannot be
    # applied without one. It must not silently behave like a male account.
    eligible, reason = is_shakti_eligible(Gender.PREFER_NOT_TO_SAY.value)
    assert eligible is False


# ── the e-ticket ────────────────────────────────────────────────────────────
def test_a_scheme_ticket_keeps_the_normal_ticket_shape():
    """Same QR token, same six-character code, same expiry. A conductor
    verifies a free ticket with the identical scan -- the scheme changes who
    pays, not what a valid ticket looks like."""
    ticket = TicketResponse(
        ticket_id="t1", user_id="u1", source_stop="Majestic", destination_stop="Marathahalli",
        fare_amount=0.0, fare_value_inr=27.0, fare_collected_inr=0.0,
        is_zero_fare=True, scheme=SCHEME_NAME, scheme_note=DISCLOSURE,
        issue_time="2026-08-10T06:00:00+00:00", expiry_time="2026-08-10T08:00:00+00:00",
        status="ISSUED", qr_token="a.b.c", short_code="A1B2C3",
    )
    assert len(ticket.short_code) == 6
    assert ticket.short_code.isalnum()
    assert ticket.qr_token
    # Free to the passenger, worth something to BMTC. Both must be present.
    assert ticket.fare_amount == 0.0
    assert ticket.fare_collected_inr == 0.0
    assert ticket.fare_value_inr > 0


def test_tickets_issued_before_the_scheme_still_deserialise():
    """Historical tickets have none of the scheme fields. A required field
    would break every past ticket in /api/tickets/history."""
    legacy = TicketResponse(
        ticket_id="old", user_id="u1", source_stop="A", destination_stop="B",
        fare_amount=25.0, issue_time="2026-01-01T00:00:00+00:00",
        expiry_time="2026-01-01T02:00:00+00:00", status="EXPIRED",
        qr_token="x.y.z", short_code="ZZ9999",
    )
    assert legacy.is_zero_fare is False
    assert legacy.scheme is None
    assert legacy.fare_value_inr is None


# ── the conductor path agrees with the app path ─────────────────────────────
@pytest.fixture(scope="module")
def priced_request():
    from types import SimpleNamespace

    from app.core.config import settings
    from app.ml.predictor import BMTCBusPredictor

    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    predictor.train()
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(predictor=predictor)))


def test_conductor_sale_applies_the_same_ac_rule(priced_request):
    """Both paths share app/core/shakti.py's rule. If they drifted, a passenger
    could be told in the app that her AC journey is free and then charged for
    it on the bus -- failed by the software twice."""
    ordinary = price_ticket(
        "Majestic", "Marathahalli", [(PassengerType.SHAKTI, 1)], priced_request, is_ac=False
    )
    assert ordinary["fare_collected_inr"] == 0.0
    assert ordinary["lines"][0]["is_zero_fare"] is True

    ac = price_ticket(
        "Majestic", "Marathahalli", [(PassengerType.SHAKTI, 1)], priced_request, is_ac=True
    )
    assert ac["fare_collected_inr"] > 0
    assert ac["lines"][0]["is_zero_fare"] is False
    # Still recorded as a Shakti passenger, so a depot reviewing the waybill
    # sees a scheme traveller on a service the scheme does not cover.
    assert ac["lines"][0]["scheme"] == SCHEME_NAME


def test_a_chargeable_ac_journey_is_never_billed_to_the_state(priced_request):
    """The quiet failure: counting a paid journey into the reimbursement claim
    bills the state for money already taken from the passenger."""
    ac = price_ticket(
        "Majestic", "Marathahalli", [(PassengerType.SHAKTI, 2)], priced_request, is_ac=True
    )
    claimable = [line for line in ac["lines"] if line["scheme"] == SCHEME_NAME and line["is_zero_fare"]]
    assert claimable == []
