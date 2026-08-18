"""
Quick script to populate the database with some dummy Bengaluru commuter data.
This lets us test the UI without having to manually click through the app 100 times.
Run it via: python -m app.db.seed
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.auth.auth import hash_password
from app.db.database import get_db, init_db

# ── Popular Bengaluru corridors (realistic commuter patterns) ──
CORRIDORS = [
    ("Silk Board", "Marathahalli"),
    ("Silk Board", "Electronic City"),
    ("Majestic", "Electronic City"),
    ("Majestic", "Whitefield"),
    ("Majestic", "Banashankari"),
    ("Marathahalli", "Majestic"),
    ("Electronic City", "Silk Board"),
    ("Whitefield", "Majestic"),
    ("Banashankari", "Majestic"),
    ("Yeshwanthpur", "Electronic City"),
    ("Hebbal", "Silk Board"),
    ("KR Puram", "Majestic"),
    ("Jayanagara", "Majestic"),
    ("BTM Layout", "Whitefield"),
    ("Koramangala", "Majestic"),
    ("HSR Layout", "Marathahalli"),
    ("Yelahanka", "Majestic"),
    ("Rajajinagara", "Silk Board"),
    ("Vijayanagara", "Electronic City"),
    ("Indiranagara", "Whitefield"),
    ("Basavanagudi", "Electronic City"),
    ("JP Nagara", "Silk Board"),
    ("Peenya", "Majestic"),
    ("Nagarbhavi", "Majestic"),
    ("Kengeri", "Majestic"),
]

TIME_PREFS = ["morning_peak", "afternoon", "evening_peak", "night", "any"]
TIME_WEIGHTS = [35, 15, 35, 5, 10]  # Peak hours dominate

FIRST_NAMES = [
    "Arun", "Bharath", "Chitra", "Deepa", "Ganesh", "Harini", "Kavya", "Lakshmi",
    "Mohan", "Nandini", "Priya", "Rajesh", "Sanjay", "Tanvi", "Usha", "Venkat",
    "Ananya", "Divya", "Karthik", "Meera", "Pooja", "Ravi", "Sneha", "Varun",
    "Aditya", "Bhavya", "Chaitra", "Darshan", "Eshwar", "Fathima",
]

LAST_NAMES = [
    "Kumar", "Sharma", "Reddy", "Gowda", "Rao", "Shetty", "Murthy", "Naik",
    "Patil", "Hegde", "Nair", "Joshi", "Gupta", "Singh", "Acharya", "Bhat",
]

LANGS = ["en", "kn", "hi", "te"]
LANG_WEIGHTS = [40, 35, 15, 10]  # Bengaluru demographics


async def seed() -> None:
    """Wipe or populate the DB with initial demo data."""
    await init_db()
    print("[DB] Database initialized.")

    async for db in get_db():
        # let's grab the total number of users first to see if we already ran this script
        existing_count = await db.users.count_documents({})
        if existing_count > 10:
            print(f"[WARN] Looks like the DB already has {existing_count} users. Bailing out so we don't duplicate stuff.")
            return

        # ── Create admin & depot users manually if they don't exist ──
        if not await db.users.find_one({"email": "admin@bmtc.ai"}):
            await db.users.insert_one({
                "email": "admin@bmtc.ai",
                "name": "Admin",
                "password_hash": hash_password("admin123"),
                "role": "admin",
                "preferred_lang": "en",
                "reliability": 1.0,
                "is_active": 1,
                "created_at": datetime.now(timezone.utc)
            })

        if not await db.users.find_one({"email": "depot@bmtc.ai"}):
            await db.users.insert_one({
                "email": "depot@bmtc.ai",
                "name": "Depot Manager",
                "password_hash": hash_password("depot123"),
                "role": "depot_manager",
                "preferred_lang": "en",
                "reliability": 1.0,
                "is_active": 1,
                "created_at": datetime.now(timezone.utc)
            })

        # ── generate a bunch of fake commuters ──
        commuters = []
        new_users = []
        for i in range(50):
            fname = random.choice(FIRST_NAMES)
            lname = random.choice(LAST_NAMES)
            name = f"{fname} {lname}"
            email = f"{fname.lower()}.{lname.lower()}{i}@example.com"
            lang = random.choices(LANGS, weights=LANG_WEIGHTS, k=1)[0]
            pw_hash = hash_password("demo123")

            new_users.append({
                "email": email,
                "name": name,
                "password_hash": pw_hash,
                "role": "commuter",
                "preferred_lang": lang,
                "reliability": round(random.uniform(0.7, 1.0), 2),
                "is_active": 1,
                "created_at": datetime.now(timezone.utc)
            })

        if new_users:
            insertion_result = await db.users.insert_many(new_users)
            commuters = [str(id) for id in insertion_result.inserted_ids]

        print(f"[SEED] Created {len(commuters)} commuter accounts.")

        # ── now let's fake some votes (around 600) ──
        total_votes = 0
        right_now = datetime.now(timezone.utc)
        vote_records = []

        for _ in range(600):
            user_id = random.choice(commuters) if commuters else None
            if not user_id: continue

            corridor = random.choices(CORRIDORS, weights=[
                20, 18, 16, 14, 12, 10, 9, 8, 7, 6,
                6, 5, 5, 5, 5, 4, 4, 4, 3, 3,
                3, 3, 2, 2, 2
            ], k=1)[0]

            time_pref = random.choices(TIME_PREFS, weights=TIME_WEIGHTS, k=1)[0]
            # scatter the votes across the past month
            days_ago = random.randint(0, 29)
            hours_ago = random.randint(0, 23)
            vote_time = right_now - timedelta(days=days_ago, hours=hours_ago)
            day_of_week = vote_time.weekday()

            # maybe flag a few votes randomly so the admin dashboard has something to show (about 5%)
            is_flagged = 1 if random.random() < 0.05 else 0

            vote_records.append({
                "user_id": user_id,
                "current_stop": corridor[0],
                "destination": corridor[1],
                "time_preference": time_pref,
                "day_of_week": day_of_week,
                "created_at": vote_time,
                "ip_address": f"192.168.1.{random.randint(1, 254)}",
                "is_flagged": is_flagged
            })
            total_votes += 1

        if vote_records:
            await db.votes.insert_many(vote_records)
        print(f"[SEED] Created {total_votes} votes.")

        # ── mock some prediction logs ──
        total_preds = 0
        bus_numbers = ["500-D", "500-C", "356", "201-R", "335-E", "KBS-7", "G-4", "V-500"]
        pred_docs = []

        for _ in range(100):
            user_id = random.choice(commuters) if commuters else None
            if not user_id: continue

            corridor = random.choice(CORRIDORS)
            bus = random.choice(bus_numbers)
            confidence = round(random.uniform(0.55, 0.95), 2)
            was_helpful = random.choices([1, 0, None], weights=[60, 20, 20], k=1)[0]
            response_ms = random.randint(30, 200)
            days_ago = random.randint(0, 29)
            pred_time = right_now - timedelta(days=days_ago, hours=random.randint(0, 23))

            pred_docs.append({
                "user_id": user_id,
                "current_stop": corridor[0],
                "destination": corridor[1],
                "predicted_bus": bus,
                "confidence": confidence,
                "was_helpful": was_helpful,
                "response_ms": response_ms,
                "created_at": pred_time
            })
            total_preds += 1

        if pred_docs:
            await db.predictions.insert_many(pred_docs)
        print(f"[SEED] Created {total_preds} prediction records.")

        # ── Create some notifications ──
        notif_messages = [
            ("Route Update", "Bus 500-D now runs every 10 minutes during peak hours.", "update"),
            ("New Feature", "You can now vote for your preferred bus route!", "info"),
            ("Service Alert", "Route 335-E temporarily diverted via Outer Ring Road.", "alert"),
            ("Welcome!", "Welcome to DBARS. Start by voting for your route.", "info"),
        ]
        notif_docs = []
        for uid in commuters[:20]:
            title, body, cat = random.choice(notif_messages)
            notif_docs.append({
                "user_id": uid,
                "title": title,
                "body": body,
                "category": cat,
                "is_read": 0,
                # `now` was never defined in this function -- the timestamp
                # built at the top of the vote block is called `right_now`.
                # Seeding raised NameError here and died after the votes and
                # predictions were already written, so a run looked partly
                # successful and never produced any notifications.
                "created_at": right_now
            })
        if notif_docs:
            await db.notifications.insert_many(notif_docs)

        print(f"[SEED] Created notifications for {min(20, len(commuters))} users.")

    print("\n[DONE] Demo data seeding complete!")
    print("   Default accounts:")
    print("   Admin:    admin@bmtc.ai / admin123")
    print("   Depot:    depot@bmtc.ai / depot123")
    print("   Commuter: (any seeded email) / demo123")


if __name__ == "__main__":
    asyncio.run(seed())
