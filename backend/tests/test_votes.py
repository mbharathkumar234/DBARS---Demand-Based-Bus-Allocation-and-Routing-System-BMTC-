import pytest
from unittest.mock import AsyncMock, patch
from app.api.votes import _allocated_bus, _depot_review, _other_options
from app.services.vote_service import get_pair_demand, submit_vote

@pytest.mark.asyncio
async def test_flagged_vote_returns_flag_reason() -> None:
    fake_detector = AsyncMock()
    fake_detector.check.return_value = (True, "Rapid repeated voting detected")

    mock_db = AsyncMock()
    mock_db.votes.insert_one.return_value = AsyncMock(inserted_id="507f1f77bcf86cd799439011")
    mock_db.users.find_one.return_value = None

    async def mock_get_db():
        yield mock_db

    with patch("app.services.vote_service.fraud_detector", fake_detector), \
         patch("app.services.vote_service.get_db", mock_get_db):
        res = await submit_vote(
            user_id="507f1f77bcf86cd799439011",
            current_stop="Silk Board",
            destination="Marathahalli",
            time_preference="morning",
            ip_address="127.0.0.1",
        )

    assert res["is_flagged"] is True
    assert res["flag_reason"] == "Rapid repeated voting detected"
    assert res["vote_id"] == "507f1f77bcf86cd799439011"


# ── GET /votes/allocation: the bus shown back to the commuter who voted ──


@pytest.mark.asyncio
async def test_pair_demand_collapses_time_preference_rows() -> None:
    """One figure per stop pair, built from the per-time-preference rows.

    Genuine votes must exclude the ones the fraud detector already flagged,
    and unique voters must NOT be summed across rows -- one person voting for
    the morning and the evening is still one voter, and adding them would
    inflate the demand the commuter is shown.
    """
    rows = [
        {"current_stop": "Silk Board", "destination": "Marathahalli",
         "time_preference": "morning_peak", "vote_count": 10, "unique_voters": 4,
         "flagged_count": 2, "last_vote": None},
        {"current_stop": "Silk Board", "destination": "Marathahalli",
         "time_preference": "evening_peak", "vote_count": 6, "unique_voters": 3,
         "flagged_count": 0, "last_vote": None},
    ]

    mock_db = AsyncMock()
    mock_db.votes.count_documents.return_value = 3

    async def mock_get_db():
        yield mock_db

    with patch("app.services.vote_service.get_vote_aggregation", AsyncMock(return_value=rows)), \
         patch("app.services.vote_service.get_db", mock_get_db):
        demand = await get_pair_demand("Silk Board", "Marathahalli", days=30, user_id="u1")

    assert demand["available"] is True
    assert demand["total_votes"] == 16
    assert demand["flagged_votes"] == 2
    assert demand["genuine_votes"] == 14
    assert demand["unique_voters"] == 4
    assert demand["your_votes"] == 3
    assert [row["time_preference"] for row in demand["by_time_preference"]] == [
        "morning_peak", "evening_peak"
    ]


def test_allocated_bus_is_none_when_engine_found_nothing() -> None:
    """No route between these stops must stay "no route", never a named bus."""
    assert _allocated_bus({"best_match": None, "alternatives": []}) is None


def test_allocated_bus_keeps_a_transfer_journey_as_a_chain() -> None:
    """A two-bus journey must never be presented as one allocated bus."""
    prediction = {
        "best_match": {
            "bus_number": "500-D",
            "bus_chain": "500-D -> KBS-1K",
            "transfers": 1,
            "matched_current_stop": "Central Silk Board",
            "matched_destination": "Marathahalli",
            "transfer_stops": ["Marathahalli Bridge"],
            "trip_count": 132,
            "first_trips": ["05:25:00"],
            "legs": [
                {"bus_number": "500-D", "from_stop": "Central Silk Board",
                 "to_stop": "Marathahalli Bridge", "trip_count": 132, "first_trips": ["05:25:00"]},
                {"bus_number": "KBS-1K", "from_stop": "Marathahalli Bridge",
                 "to_stop": "Marathahalli", "trip_count": 40, "first_trips": ["06:00:00"]},
            ],
        },
        "alternatives": [],
    }

    allocated = _allocated_bus(prediction)

    # bus_number is the bus to board FIRST, and the chain still names both.
    assert allocated["bus_number"] == "500-D"
    assert allocated["bus_chain"] == "500-D -> KBS-1K"
    assert allocated["transfers"] == 1
    assert [leg["bus_number"] for leg in allocated["legs"]] == ["500-D", "KBS-1K"]
    assert allocated["board_at"] == "Central Silk Board"
    assert allocated["alight_at"] == "Marathahalli"


def test_other_options_skips_the_allocated_journey() -> None:
    """alternatives[0] IS the allocated journey; listing it again is a duplicate."""
    prediction = {
        "best_match": {"bus_number": "500-D"},
        "alternatives": [
            {"bus_chain": "500-D", "transfers": 0, "total_stops": 12,
             "legs": [{"from_stop": "A", "to_stop": "B"}]},
            {"bus_chain": "501-C", "transfers": 0, "total_stops": 14,
             "legs": [{"from_stop": "A", "to_stop": "B"}]},
        ],
    }

    options = _other_options(prediction)

    assert [option["bus_chain"] for option in options] == ["501-C"]


def test_depot_review_reports_the_latest_and_hides_who_reviewed_it() -> None:
    """Only the acknowledgement, and never another user's id."""
    from app.api.routes import DEPLOYED_BUSES

    DEPLOYED_BUSES.extend([
        {"route_number": "500-D", "note": "first look", "timestamp": "09:00:00",
         "status": "Reviewed by depot manager", "reviewed_by": "depot-user-1"},
        {"route_number": "500-D", "note": "adding a peak trip", "timestamp": "10:15:00",
         "status": "Reviewed by depot manager", "reviewed_by": "depot-user-2"},
        {"route_number": "999-Z", "note": "unrelated", "timestamp": "11:00:00",
         "status": "Reviewed by depot manager", "reviewed_by": "depot-user-3"},
    ])
    try:
        review = _depot_review({"500-D"})
    finally:
        DEPLOYED_BUSES.clear()

    assert review["route_number"] == "500-D"
    assert review["note"] == "adding a peak trip"
    assert review["at"] == "10:15:00"
    assert "reviewed_by" not in review


def test_depot_review_is_none_for_an_unreviewed_route() -> None:
    from app.api.routes import DEPLOYED_BUSES

    assert not DEPLOYED_BUSES
    assert _depot_review({"500-D"}) is None
