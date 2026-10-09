"""Audit trail routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Query


router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/audit/logs")
async def get_audit_logs(
    user_id: Optional[str] = Query(None),
    application_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get audit logs for troubleshooting and traceability.
    
    Alias for /audit/trail - returns recent audit events.
    """
    from app.main import app_state
    db = app_state.get("database")
    if not db:
        return {"data": {"logs": [], "total": 0}}
    try:
        logs = db.get_audit_trail(
            user_id=user_id,
            application_id=application_id,
            event_type=event_type,
            limit=limit,
        )
        return {"data": {"logs": logs, "total": len(logs)}}
    except Exception as e:
        logger.error(f"Failed to get audit logs: {e}")
        return {"error": str(e)}


@router.get("/audit/trail")
async def get_audit_trail(
    user_id: Optional[str] = Query(None),
    application_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get audit trail for troubleshooting and traceability.
    
    Phase 3: Every stage of every application is logged and queryable.
    """
    from app.main import app_state
    db = app_state.get("database")
    if not db:
        return {"data": {"audit_trail": [], "total": 0}}
    try:
        trail = db.get_audit_trail(
            user_id=user_id,
            application_id=application_id,
            event_type=event_type,
            limit=limit,
        )
        return {"data": {"audit_trail": trail, "total": len(trail)}}
    except Exception as e:
        logger.error(f"Failed to get audit trail: {e}")
        return {"error": str(e)}


@router.get("/audit/events")
async def get_audit_events(
    user_id: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get recent audit events for monitoring.
    
    Phase 3: Track routing accuracy, extraction accuracy, human review rates.
    """
    from app.main import app_state
    db = app_state.get("database")
    if not db:
        return {"data": {"events": [], "total": 0}}
    try:
        # Group events by type for trend tracking
        events = db.get_audit_trail(user_id=user_id, limit=limit)
        event_counts = {}
        for event in events:
            et = event["event_type"]
            event_counts[et] = event_counts.get(et, 0) + 1
        return {
            "data": {
                "events": events[:20],  # Recent events
                "counts": event_counts,  # Aggregated counts
                "total": len(events),
            }
        }
    except Exception as e:
        logger.error(f"Failed to get audit events: {e}")
        return {"error": str(e)}
