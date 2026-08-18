"""Shakti scheme eligibility, in one place.

Karnataka's Shakti scheme gives free bus travel to women and transgender
persons on non-premium services. Two code paths need that rule -- the
conductor's onboard sale and the commuter's in-app e-ticket -- and they must
not disagree: a passenger told the app that her journey is free, then charged
for it on the bus, has been failed by the software twice.

WHAT IS REAL VS WHAT IS SIMULATED
---------------------------------
The RULE below is the real scheme rule. What is simulated is the entitlement
CHECK: the real scheme requires a government-issued ID proving residency in
Karnataka, verified by the conductor. DBARS has no access to any such register,
so it takes the gender recorded at registration at face value. That is enough
to model the scheme's operational and financial shape -- who travels free, what
it costs, what BMTC claims back -- and it is not an identity check. Every
ticket issued this way says so.
"""

from __future__ import annotations

from enum import Enum


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    TRANSGENDER = "transgender"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


# The scheme covers women and transgender persons. Transgender passengers are
# included in the scheme as enacted, not an extension of it -- omitting them
# would be implementing a stricter rule than the one that exists.
SHAKTI_ELIGIBLE_GENDERS = frozenset({Gender.FEMALE.value, Gender.TRANSGENDER.value})

SCHEME_NAME = "shakti"


def is_shakti_eligible(gender: str | None, *, is_ac: bool = False) -> tuple[bool, str | None]:
    """Does this journey travel free under the scheme?

    Returns (eligible, reason_if_not). The reason is written to be shown to the
    passenger: someone who expected a free ticket and got a priced one needs to
    know which rule applied, not just that something did not happen.
    """
    if not gender:
        return False, (
            "Free travel under the Shakti scheme needs a gender on your account. "
            "You can add one from your profile."
        )
    if gender not in SHAKTI_ELIGIBLE_GENDERS:
        return False, None          # Not applicable; nothing to explain.
    if is_ac:
        # The real rule, and the one most likely to surprise: the scheme covers
        # ordinary services only. Vajra (AC) and Vayu Vajra (airport) journeys
        # are paid by everyone.
        return False, (
            "The Shakti scheme covers ordinary (non-AC) services only. "
            "AC and airport services are chargeable for all passengers."
        )
    return True, None


DISCLOSURE = (
    "Issued free under the Karnataka Shakti scheme. Eligibility is taken from the gender "
    "recorded on this account -- DBARS does not verify residency or government ID, which "
    "the real scheme requires and a conductor checks."
)
