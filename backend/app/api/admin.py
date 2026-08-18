from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.auth import UserRole, get_current_user, require_role
from app.db.database import get_db
from app.services.analytics_service import get_pilot_metrics

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/pilot-metrics")
async def pilot_metrics(
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Real, measured usage for a pilot report -- see analytics_service.py.

    Every number here comes from genuinely logged events or genuine
    database rows. There is no synthetic/example data anywhere in this
    endpoint; before a real pilot has run, this honestly reports
    status: "no_data" rather than a placeholder-populated dashboard.
    """
    return await get_pilot_metrics(days=days)


@router.get("/dashboard")
async def admin_dashboard(user: dict = Depends(require_role(UserRole.ADMIN))) -> dict:
    """Gather all the top-level metrics for the admin overview."""
    async for db in get_db():
        # break down how many users we have for each role
        role_counts_cursor = await db.users.aggregate([{"$group": {"_id": "$role", "count": {"$sum": 1}}}]).to_list(None)
        role_counts = {r["_id"]: r["count"] for r in role_counts_cursor}

        # count total votes cast in the last 30 days
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        total_votes_30d = await db.votes.count_documents({"created_at": {"$gte": thirty_days_ago}})

        # Active users today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        active_users_list = await db.votes.distinct("user_id", {"created_at": {"$gte": today_start}})
        active_today = len(active_users_list)

        # Flagged votes
        flagged = await db.votes.count_documents({"is_flagged": 1})

        # figure out our prediction accuracy based on user feedback
        acc_pipeline = [
            {"$match": {"was_helpful": {"$ne": None}}},
            {"$group": {"_id": None, "total": {"$sum": 1}, "helpful": {"$sum": {"$cond": [{"$eq": ["$was_helpful", 1]}, 1, 0]}}}}
        ]
        acc_cursor = await db.predictions.aggregate(acc_pipeline).to_list(1)
        if acc_cursor:
            accuracy = round(acc_cursor[0]["helpful"] / max(acc_cursor[0]["total"], 1) * 100, 1)
        else:
            accuracy = 0.0

        # calculate the average time it takes the AI to spit out a prediction
        avg_pipeline = [
            {"$match": {"response_ms": {"$ne": None}}},
            {"$group": {"_id": None, "avg_ms": {"$avg": "$response_ms"}}}
        ]
        avg_cursor = await db.predictions.aggregate(avg_pipeline).to_list(1)
        avg_ms = avg_cursor[0]["avg_ms"] if avg_cursor else 0.0

        # pull the most requested routes so we know where the demand is
        top_routes_pipeline = [
            {"$match": {"created_at": {"$gte": thirty_days_ago}, "is_flagged": 0}},
            {"$group": {"_id": {"current_stop": "$current_stop", "destination": "$destination"}, "votes": {"$sum": 1}}},
            {"$sort": {"votes": -1}},
            {"$limit": 10},
            {"$project": {"current_stop": "$_id.current_stop", "destination": "$_id.destination", "votes": 1, "_id": 0}}
        ]
        top_routes = await db.votes.aggregate(top_routes_pipeline).to_list(None)

        # group the votes by hour to see when the app is busiest
        hour_pipeline = [
            {"$match": {"created_at": {"$gte": thirty_days_ago}}},
            {"$group": {"_id": {"$hour": "$created_at"}, "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
            {"$project": {"hour": "$_id", "count": 1, "_id": 0}}
        ]
        votes_by_hour = await db.votes.aggregate(hour_pipeline).to_list(None)

        # check what languages our users prefer
        lang_pipeline = [{"$group": {"_id": "$preferred_lang", "count": {"$sum": 1}}}]
        lang_cursor = await db.users.aggregate(lang_pipeline).to_list(None)
        lang_dist = {r["_id"] or "en": r["count"] for r in lang_cursor}

        # get a rolling daily trend for the past two weeks
        fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)
        daily_trend_pipeline = [
            {"$match": {"created_at": {"$gte": fourteen_days_ago}}},
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
            {"$project": {"day": "$_id", "count": 1, "_id": 0}}
        ]
        daily_trend = await db.votes.aggregate(daily_trend_pipeline).to_list(None)

        # find the routes that nobody really cares about
        underused_pipeline = [
            {"$match": {"created_at": {"$gte": thirty_days_ago}, "is_flagged": 0}},
            {"$group": {"_id": "$destination", "vote_count": {"$sum": 1}}},
            {"$sort": {"vote_count": 1}},
            {"$limit": 10},
            {"$project": {"destination": "$_id", "vote_count": 1, "_id": 0}}
        ]
        underused = await db.votes.aggregate(underused_pipeline).to_list(None)

    return {
        "kpi": {
            "total_commuters": role_counts.get("commuter", 0),
            "total_admins": role_counts.get("admin", 0),
            "total_depot_managers": role_counts.get("depot_manager", 0),
            "total_votes_30d": total_votes_30d,
            "active_today": active_today,
            "flagged_votes": flagged,
            "prediction_accuracy_pct": accuracy,
            "avg_response_ms": round(avg_ms, 1),
        },
        "top_routes": top_routes,
        "votes_by_hour": votes_by_hour,
        "language_distribution": lang_dist,
        "daily_trend": daily_trend,
        "underused_destinations": underused,
    }


from bson.errors import InvalidId
from pydantic import BaseModel, EmailStr, Field

def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid id.")


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    name: str = Field(..., min_length=2, max_length=100)
    role: str = Field("commuter", pattern="^(commuter|admin|depot_manager|conductor)$")


@router.post("/users", status_code=201)
async def create_user_by_admin(
    payload: CreateUserRequest,
    admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Provision a new user account with a specific role (Admin only)."""
    from app.auth.auth import hash_password
    async for db in get_db():
        existing = await db.users.find_one({"email": payload.email.lower().strip()})
        if existing:
            raise HTTPException(status_code=400, detail="User with this email already exists.")

        user_doc = {
            "email": payload.email.lower().strip(),
            "name": payload.name.strip(),
            "password_hash": hash_password(payload.password),
            "role": payload.role,
            "preferred_lang": "en",
            "reliability": 1.0,
            "is_active": 1,
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(user_doc)
        return {
            "id": str(res.inserted_id),
            "email": user_doc["email"],
            "name": user_doc["name"],
            "role": user_doc["role"],
            "message": f"User created successfully with role '{payload.role}'.",
        }
    raise HTTPException(status_code=503, detail="Database unavailable.")


@router.get("/users")
async def list_users(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    role: str | None = Query(None),
    search: str | None = Query(None),
) -> dict:
    """List all users with filtering (without password_hash or trusted_contacts)."""
    query: dict[str, Any] = {}
    if role:
        query["role"] = role
    if search:
        query["$or"] = [
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"email": {"$regex": re.escape(search), "$options": "i"}}
        ]
        
    async for db in get_db():
        cursor = db.users.find(query, {"password_hash": 0, "trusted_contacts": 0}).sort("created_at", -1).skip(offset).limit(limit)
        rows = await cursor.to_list(None)
        
        # Convert _id to id string
        formatted_rows = []
        for row in rows:
            row["id"] = str(row.pop("_id"))
            formatted_rows.append(row)
            
        total = await db.users.count_documents(query)

    return {"users": formatted_rows, "total": total}


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: str,
    admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Activate or deactivate a user account."""
    oid = _object_id(user_id)
    async for db in get_db():
        row = await db.users.find_one({"_id": oid})
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
            
        new_status = 0 if row.get("is_active", 1) else 1
        await db.users.update_one({"_id": oid}, {"$set": {"is_active": new_status}})
        
    return {"user_id": user_id, "is_active": bool(new_status)}


@router.get("/votes/analytics")
async def vote_analytics(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Detailed vote analytics for admin dashboard."""
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    async for db in get_db():
        # Vote heatmap origins
        origin_pipeline = [
            {"$match": {"created_at": {"$gte": start_date}, "is_flagged": 0}},
            {"$group": {"_id": "$current_stop", "origin_votes": {"$sum": 1}}},
            {"$sort": {"origin_votes": -1}},
            {"$limit": 50},
            {"$project": {"current_stop": "$_id", "origin_votes": 1, "_id": 0}}
        ]
        heatmap_origins = await db.votes.aggregate(origin_pipeline).to_list(None)

        # Vote heatmap destinations
        dest_pipeline = [
            {"$match": {"created_at": {"$gte": start_date}, "is_flagged": 0}},
            {"$group": {"_id": "$destination", "dest_votes": {"$sum": 1}}},
            {"$sort": {"dest_votes": -1}},
            {"$limit": 50},
            {"$project": {"destination": "$_id", "dest_votes": 1, "_id": 0}}
        ]
        heatmap_destinations = await db.votes.aggregate(dest_pipeline).to_list(None)

        # Votes by time preference
        time_pref_pipeline = [
            {"$match": {"created_at": {"$gte": start_date}}},
            {"$group": {"_id": "$time_preference", "count": {"$sum": 1}}},
            {"$project": {"time_preference": "$_id", "count": 1, "_id": 0}}
        ]
        by_time_pref = await db.votes.aggregate(time_pref_pipeline).to_list(None)

        # Votes by day of week
        dow_pipeline = [
            {"$match": {"created_at": {"$gte": start_date}}},
            {"$group": {"_id": "$day_of_week", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
            {"$project": {"day_of_week": "$_id", "count": 1, "_id": 0}}
        ]
        by_dow = await db.votes.aggregate(dow_pipeline).to_list(None)

    return {
        "heatmap_origins": heatmap_origins,
        "heatmap_destinations": heatmap_destinations,
        "by_time_preference": by_time_pref,
        "by_day_of_week": by_dow,
        "period_days": days,
    }


@router.get("/fraud/alerts")
async def fraud_alerts(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Get flagged votes for fraud review."""
    async for db in get_db():
        # Join votes with users using $lookup
        fraud_pipeline = [
            {"$match": {"is_flagged": 1}},
            {"$sort": {"created_at": -1}},
            {"$limit": limit},
            # user_id in votes is likely stored as string now (converted ObjectId)
            # if it's string, we can convert to ObjectId
            {"$lookup": {
                "from": "users",
                "let": {"user_id_obj": {"$toObjectId": "$user_id"}},
                "pipeline": [{"$match": {"$expr": {"$eq": ["$_id", "$$user_id_obj"]}}}],
                "as": "user"
            }},
            {"$unwind": {"path": "$user", "preserveNullAndEmptyArrays": True}},
            {"$project": {
                "id": {"$toString": "$_id"},
                "user_id": 1,
                "name": "$user.name",
                "email": "$user.email",
                "reliability": "$user.reliability",
                "current_stop": 1,
                "destination": 1,
                "ip_address": 1,
                "created_at": 1,
                "_id": 0
            }}
        ]
        rows = await db.votes.aggregate(fraud_pipeline).to_list(None)

        # Suspicious users
        sus_users_cursor = db.users.find({"reliability": {"$lt": 0.7}}).sort("reliability", 1).limit(10)
        sus_users = []
        async for u in sus_users_cursor:
            sus_users.append({
                "id": str(u["_id"]),
                "name": u.get("name"),
                "email": u.get("email"),
                "reliability": u.get("reliability")
            })

    return {"flagged_votes": rows, "suspicious_users": sus_users}