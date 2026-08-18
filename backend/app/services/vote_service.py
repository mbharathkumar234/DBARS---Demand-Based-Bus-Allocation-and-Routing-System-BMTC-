from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.database import get_db

logger = logging.getLogger("bmtc.services.vote")


class VoteFraudDetector:
    """A basic filter to catch bots or super-enthusiastic commuters spamming the same route."""

    async def check(self, user_id: str, current_stop: str, destination: str, ip: str | None) -> tuple[bool, str]:
        """Runs a few heuristic checks and returns a tuple: (is_suspicious, reason_why)."""
        async for db in get_db():
            now = datetime.now(timezone.utc)
            twenty_four_hours_ago = now - timedelta(hours=24)
            one_hour_ago = now - timedelta(hours=1)

            # Rule 1: check if someone is just mashing the vote button on the exact same route
            recent_same_route_count = await db.votes.count_documents({
                "user_id": user_id,
                "current_stop": current_stop,
                "destination": destination,
                "created_at": {"$gte": twenty_four_hours_ago}
            })
            if recent_same_route_count >= 10:
                return True, "Excessive repeat voting for same route (>10 in 24h)"

            # Rule 2: check if their total vote velocity is crazy high
            recent_total_count = await db.votes.count_documents({
                "user_id": user_id,
                "created_at": {"$gte": one_hour_ago}
            })
            if recent_total_count >= 30:
                return True, "Vote rate exceeds threshold (>30 votes/hour)"

            # Rule 3: block IPs that are spraying votes across accounts
            if ip:
                ip_count = await db.votes.count_documents({
                    "ip_address": ip,
                    "created_at": {"$gte": one_hour_ago}
                })
                if ip_count >= 50:
                    return True, f"IP {ip} is sending way too many votes (>50/hour)"

            # Rule 4: block users who are voting for a ton of completely different destinations (likely bots scraping)
            destinations = await db.votes.distinct("destination", {
                "user_id": user_id,
                "created_at": {"$gte": one_hour_ago}
            })
            if len(destinations) >= 15:
                return True, "Destination spray detected (>15 unique destinations/hour)"

        return False, ""


fraud_detector = VoteFraudDetector()


async def submit_vote(
    user_id: str,
    current_stop: str,
    destination: str,
    time_preference: str = "any",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Handle the entire vote submission process including fraud checks."""
    is_flagged, flag_reason = await fraud_detector.check(user_id, current_stop, destination, ip_address)

    now = datetime.now(timezone.utc)
    day_of_week = now.weekday()

    async for db in get_db():
        vote_payload = {
            "user_id": user_id,
            "current_stop": current_stop,
            "destination": destination,
            "time_preference": time_preference,
            "day_of_week": day_of_week,
            "ip_address": ip_address,
            "is_flagged": int(is_flagged),
            "created_at": now
        }
        insert_result = await db.votes.insert_one(vote_payload)
        vote_id = str(insert_result.inserted_id)

        # if they tripped the fraud detector, ding their account reliability score
        if is_flagged:
            from bson import ObjectId
            from bson.errors import InvalidId
            try:
                oid = ObjectId(user_id)
                user_obj = await db.users.find_one({"_id": oid})
                if user_obj:
                    new_rel = max(0, user_obj.get("reliability", 1.0) - 0.05)
                    await db.users.update_one({"_id": oid}, {"$set": {"reliability": new_rel}})
            except InvalidId:
                pass

    return {
        "vote_id": vote_id,
        "is_flagged": is_flagged,
        "flag_reason": flag_reason if is_flagged else None,
        "current_stop": current_stop,
        "destination": destination,
        "time_preference": time_preference,
    }


async def get_vote_aggregation(
    current_stop: str | None = None,
    destination: str | None = None,
    days: int = 30,
) -> list[dict]:
    """Get aggregated vote counts, optionally filtered by stops."""
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    match_cond = {"created_at": {"$gte": start_date}}
    if current_stop:
        match_cond["current_stop"] = current_stop
    if destination:
        match_cond["destination"] = destination

    pipeline = [
        {"$match": match_cond},
        {"$group": {
            "_id": {
                "current_stop": "$current_stop",
                "destination": "$destination",
                "time_preference": "$time_preference"
            },
            "vote_count": {"$sum": 1},
            "unique_voters_set": {"$addToSet": "$user_id"},
            "last_vote": {"$max": "$created_at"},
            "flagged_count": {"$sum": "$is_flagged"}
        }},
        {"$project": {
            "current_stop": "$_id.current_stop",
            "destination": "$_id.destination",
            "time_preference": "$_id.time_preference",
            "vote_count": 1,
            "unique_voters": {"$size": "$unique_voters_set"},
            "last_vote": 1,
            "flagged_count": 1,
            "_id": 0
        }},
        {"$sort": {"vote_count": -1}},
        {"$limit": 100}
    ]

    async for db in get_db():
        rows = await db.votes.aggregate(pipeline).to_list(None)
        return rows
    return []


async def get_pair_demand(
    current_stop: str,
    destination: str,
    days: int = 30,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Demand for ONE origin-destination pair, as the commuter who voted for it sees it.

    get_vote_aggregation above returns one row per time preference, which is
    what the depot dashboard wants. A commuter asking "what did my vote do?"
    wants a single figure for their pair, so this collapses those rows the
    same way rank_dispatch_recommendations does -- genuine votes are the total
    minus the ones the fraud detector already flagged, and unique voters is a
    max rather than a sum because one person voting at two different times is
    still one voter.

    Stop names are matched exactly, against the raw strings submit_vote stored.
    That is the honest join: a vote is recorded for the words the commuter
    typed, so a count for those words is a count of real votes rather than a
    count assembled by re-resolving them through the fuzzy stop matcher.
    """
    rows = await get_vote_aggregation(current_stop, destination, days)
    total_votes = sum(row["vote_count"] for row in rows)
    flagged_votes = sum(row.get("flagged_count", 0) for row in rows)
    unique_voters = max((row.get("unique_voters", 0) for row in rows), default=0)
    last_votes = [row["last_vote"] for row in rows if row.get("last_vote")]

    your_votes = 0
    if user_id:
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        async for db in get_db():
            your_votes = await db.votes.count_documents({
                "user_id": user_id,
                "current_stop": current_stop,
                "destination": destination,
                "created_at": {"$gte": start_date},
            })

    return {
        "available": True,
        "period_days": days,
        "total_votes": total_votes,
        "flagged_votes": flagged_votes,
        "genuine_votes": max(total_votes - flagged_votes, 0),
        "unique_voters": unique_voters,
        "your_votes": your_votes,
        "last_vote_at": max(last_votes).isoformat() if last_votes else None,
        "by_time_preference": sorted(
            (
                {"time_preference": row["time_preference"], "votes": row["vote_count"]}
                for row in rows
            ),
            key=lambda item: -item["votes"],
        ),
    }


async def get_route_vote_scores(current_stop: str, destination: str) -> dict[str, float]:
    """Get vote-based demand scores for a specific origin-destination pair.
    Returns a dict mapping time_preference to normalized demand score."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    async for db in get_db():
        # Get max votes across all OD pairs for normalization
        max_votes_pipeline = [
            {"$match": {"is_flagged": 0, "created_at": {"$gte": thirty_days_ago}}},
            {"$group": {"_id": {"current_stop": "$current_stop", "destination": "$destination"}, "cnt": {"$sum": 1}}},
            {"$group": {"_id": None, "max_cnt": {"$max": "$cnt"}}}
        ]
        max_cursor = await db.votes.aggregate(max_votes_pipeline).to_list(1)
        max_votes = max_cursor[0]["max_cnt"] if max_cursor and max_cursor[0].get("max_cnt") else 1

        # Get counts for the specific OD pair
        od_pipeline = [
            {"$match": {
                "current_stop": current_stop,
                "destination": destination,
                "is_flagged": 0,
                "created_at": {"$gte": thirty_days_ago}
            }},
            {"$group": {"_id": "$time_preference", "cnt": {"$sum": 1}}}
        ]
        rows = await db.votes.aggregate(od_pipeline).to_list(None)

    scores = {}
    for row in rows:
        scores[row["_id"]] = min(row["cnt"] / max_votes, 1.0)

    return scores
