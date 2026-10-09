"""
Services package — exports all service classes.

Changes:
- Removed SearchService (no more DB/vector search — vision model handles extraction directly)
- GenerationService now uses Qwen2.5-VL 3B vision model (image+text input)
- EmbeddingService removed (vision model embeds internally)
- Added StorageService (MinIO S3-compatible object storage)
"""

from services.ocr import OCRService
from services.generation import GenerationService
from services.storage import StorageService

# SearchService removed — no vector DB dependency
SearchService = None

from services.validation import FileValidator
from services.service_catalog import ServiceCatalogService
from services.golden_dataset import GoldenDatasetService
from services.auth import AuthService
from services.policy_service import PolicyService, get_policy_service, get_grounding_context, find_relevant_policies

__all__ = [
    "OCRService",
    "GenerationService",
    "StorageService",
    "FileValidator",
    "AuthService",
    "ServiceCatalogService",
    "GoldenDatasetService",
    "PolicyService",
    "get_policy_service",
    "get_grounding_context",
    "find_relevant_policies",
]
