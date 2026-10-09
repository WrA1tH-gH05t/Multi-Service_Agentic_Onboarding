"""API route modules for the Multi-Service Agentic Onboarding system."""

from fastapi import APIRouter

from .auth import router as auth_router
from .services import router as services_router
from .documents import router as documents_router
from .applications import router as applications_router
from .chat import router as chat_router
from .chat_message import router as chat_message_router
from .collection import router as collection_router
from .wizard import router as wizard_router
from .validation import router as validation_router
from .golden import router as golden_router
from .health import router as health_router
from .audit import router as audit_router

# Root API router (mounted at /api/v1 in main.py)
router = APIRouter()

# Register all sub-routers
router.include_router(auth_router)
router.include_router(services_router)
router.include_router(documents_router)
router.include_router(applications_router)
router.include_router(chat_router)
router.include_router(chat_message_router)
router.include_router(collection_router)
router.include_router(wizard_router)
router.include_router(validation_router)
router.include_router(golden_router)
router.include_router(health_router)
router.include_router(audit_router)
