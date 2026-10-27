"""
Audit trail routes — queryable log of every significant system event.

Role in Project:
    Provides HTTP endpoints to read the structured audit log that is written throughout
    the onboarding pipeline. Every document upload, extraction attempt, validation pass/fail,
    and chat message is appended to the `audit_events` PostgreSQL table by
    `services.database.DatabaseService.log_event`. These endpoints expose that data for
    admin dashboards, debugging, and compliance traceability.

Cross-File Interconnections:
    - `services.database.DatabaseService.get_audit_trail` — the single data-retrieval
      method that all three endpoints here delegate to. It queries the `audit_events` table
      with optional user_id, application_id, and event_type filters.
    - Written to (not read) by:
        * `app.routes.documents` — logs upload and extraction events.
        * `app.routes.collection` — logs document submission and validation events.
        * `app.routes.chat_message` — logs chat turns and injection blocks.
        * `agents.validation_agent` — logs validation decisions.
    - `app.main.app_state` — retrieves the `DatabaseService` instance at request time.
"""

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
    """Get audit logs with optional filtering — alias for /audit/trail.

    Delegates to `DatabaseService.get_audit_trail`. Returns an empty list when
    the database is not yet available (degraded mode).

    Args:
        user_id: Filter to events belonging to this user.
        application_id: Filter to events belonging to this application.
        event_type: Filter to a specific event kind (e.g. 'document_upload', 'validation_passed').
        limit: Maximum number of records to return (1–500).

    Returns:
        `{"data": {"logs": [...], "total": N}}`
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
    """Get the full audit trail for an application or user (primary endpoint).

    Phase 3: Every stage of every application — from service selection through document
    upload, extraction, validation, and final decision — is logged and queryable here.
    Supports admin oversight and SLA compliance auditing.

    Interconnections:
        - `services.database.DatabaseService.get_audit_trail` — queries `audit_events` table.

    Args:
        user_id: Scope to a specific user's events.
        application_id: Scope to a single application's lifecycle.
        event_type: Narrow to a specific event category.
        limit: Cap on returned records.

    Returns:
        `{"data": {"audit_trail": [...], "total": N}}`
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
    """Get recent audit events aggregated by event type for monitoring dashboards.

    Fetches up to `limit` recent events and computes a per-event-type count summary.
    Returns both the most recent 20 events (for a live feed) and the full count breakdown
    (for trend charts tracking extraction accuracy, routing accuracy, human-review rates).

    Phase 3: Track routing accuracy, extraction accuracy, human review rates.

    Interconnections:
        - `services.database.DatabaseService.get_audit_trail` — raw event fetch.

    Returns:
        `{"data": {"events": [...20 recent...], "counts": {event_type: N}, "total": N}}`
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
