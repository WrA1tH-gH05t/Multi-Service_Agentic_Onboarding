"""
Schemas for the Multi-Service Agentic Onboarding system.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    size: int
    status: str

class ExtractionResult(BaseModel):
    file_id: str
    document_type: str
    fields: Dict[str, Any]
    confidence: float
    status: str

class ApplicationCreate(BaseModel):
    service_id: str
    applicant_name: str
    applicant_email: str
    documents: List[str]

class ApplicationResponse(BaseModel):
    application_id: str
    service_id: str
    applicant_name: str
    status: str
    extracted_data: Optional[Dict[str, Any]] = None

class AuthenticationRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str
    user_id: str
    email: str

class UserRegistrationRequest(BaseModel):
    username: str
    password: str
    email: str
    name: str = ""

class FAQRequest(BaseModel):
    question: str
    context: Optional[str] = None

class FAQResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    confidence: float

class ValidationRequest(BaseModel):
    application_id: str
    validation_type: str = "document"
    documents: Optional[List[Dict[str, Any]]] = None
    entry_id: Optional[str] = None

class ValidationResult(BaseModel):
    application_id: str
    passed: bool
    checks: List[Dict[str, Any]]
    recommendations: List[str]

class ServiceCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    required_documents: List[str]
    status: str  # "available" or "coming_soon"
    fields: Dict[str, str]

class ServiceCatalogResponse(BaseModel):
    services: List[ServiceCatalogItem]
    coming_soon: List[ServiceCatalogItem]

class ChatMessage(BaseModel):
    query: str
    context_limit: int = 5
    token: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    sources: List[Dict[str, Any]]
    confidence: float
    intent: Optional[str] = None
    matched_service: Optional[str] = None

class DocumentMatch(BaseModel):
    document_id: str
    match_confidence: float
    matched_fields: List[str]
    mismatches: List[str]

class GoldenDatasetValidationRequest(BaseModel):
    """Request body for validating an extraction against the golden dataset."""
    entry_id: str
    fields: Dict[str, str]

class GoldenDatasetSearchRequest(BaseModel):
    """Request body for searching the golden dataset."""
    query: str
    limit: int = Field(default=10, ge=1, le=50)
