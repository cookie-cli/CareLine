# app/routers/nudges.py

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, date
from typing import Literal, Optional
from app.database.firebase import db  # firestore client

router = APIRouter(prefix="/nudges", tags=["nudges"])

TimeBucket = Literal["morning", "afternoon", "night"]
NudgeStatus = Literal["pending", "acknowledged"]

# --------------------------------------------------
# Helper: today string
# --------------------------------------------------
def today_str() -> str:
    return date.today().isoformat()


# --------------------------------------------------
# 1️⃣ Send nudge (child → parent)
# --------------------------------------------------
@router.post("/send")
def send_nudge(
    child_id: str,
    parent_id: str,
    time_bucket: TimeBucket,
    message: Optional[str] = None,
):
    """
    Create a nudge asking if medicine was taken
    """

    nudge_data = {
        "child_id": child_id,
        "parent_id": parent_id,
        "time_bucket": time_bucket,
        "message": message
        or f"Did you take your {time_bucket} medicine?",
        "status": "pending",
        "date": today_str(),
        "created_at": datetime.utcnow().isoformat(),
        "acknowledged_at": None,
    }

    doc_ref = db.collection("nudges").add(nudge_data)

    return {
        "success": True,
        "nudge_id": doc_ref[1].id,
        "nudge": nudge_data,
    }


# --------------------------------------------------
# 2️⃣ Respond to nudge (parent → child)
# --------------------------------------------------
@router.post("/respond")
def respond_to_nudge(
    nudge_id: str,
    response: Literal["taken", "skipped"] = "taken",
):
    """
    Parent acknowledges a nudge
    """

    doc_ref = db.collection("nudges").document(nudge_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Nudge not found")

    update_data = {
        "status": "acknowledged",
        "response": response,
        "acknowledged_at": datetime.utcnow().isoformat(),
    }

    doc_ref.update(update_data)

    return {
        "success": True,
        "nudge_id": nudge_id,
        "update": update_data,
    }


# --------------------------------------------------
# 3️⃣ Get today's status (child dashboard)
# --------------------------------------------------
@router.get("/today-status")
def get_today_status(
    parent_id: str = Query(..., description="Parent user id"),
):
    """
    Returns today's medicine status per time bucket
    """

    today = today_str()

    query = (
        db.collection("nudges")
        .where("parent_id", "==", parent_id)
        .where("date", "==", today)
    )

    docs = query.stream()

    status = {
        "morning": "pending",
        "afternoon": "pending",
        "night": "pending",
    }

    for doc in docs:
        data = doc.to_dict()
        bucket = data.get("time_bucket")

        if data.get("status") == "acknowledged":
            status[bucket] = "taken"

    return {
        "date": today,
        "parent_id": parent_id,
        "status": status,
    }


# --------------------------------------------------
# 4️⃣ One-time cleanup for old nudges
# --------------------------------------------------
@router.delete("/cleanup-old")
def cleanup_old_nudges(
    before_date: str = Query(
        default_factory=today_str,
        description="Delete nudges older than this date (YYYY-MM-DD)",
    ),
    limit: int = Query(500, ge=1, le=1000),
    dry_run: bool = Query(True, description="If true, only preview matches"),
    confirm: str = Query("", description='Use confirm=DELETE to allow deletion'),
):
    """
    Cleanup old nudges by date.
    Safe by default (dry_run=True).
    """

    try:
        date.fromisoformat(before_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid before_date. Use YYYY-MM-DD")

    docs = list(
        db.collection("nudges")
        .where("date", "<", before_date)
        .limit(limit)
        .stream()
    )

    preview = []
    for doc in docs[:20]:
        data = doc.to_dict() or {}
        preview.append(
            {
                "id": doc.id,
                "date": data.get("date"),
                "parent_id": data.get("parent_id"),
                "time_bucket": data.get("time_bucket"),
            }
        )

    if dry_run:
        return {
            "success": True,
            "mode": "dry_run",
            "before_date": before_date,
            "matched_count": len(docs),
            "preview": preview,
        }

    if confirm != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Deletion blocked. Use dry_run=true or pass confirm=DELETE",
        )

    batch = db.batch()
    batch_size = 0
    deleted = 0

    for doc in docs:
        batch.delete(doc.reference)
        batch_size += 1

        if batch_size >= 450:
            batch.commit()
            deleted += batch_size
            batch = db.batch()
            batch_size = 0

    if batch_size > 0:
        batch.commit()
        deleted += batch_size

    return {
        "success": True,
        "mode": "delete",
        "before_date": before_date,
        "deleted_count": deleted,
    }


# --------------------------------------------------
# 5️⃣ Debug / sanity endpoint
# --------------------------------------------------
@router.get("/health")
def nudges_health():
    return {
        "nudges": "ok",
        "date": today_str(),
    }
