"""Data transfer and schema definitions for the Multi-Service Agentic Onboarding system."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Response schema returned after uploading a document."""
    file_id: str
    filename: str
    size: int
    status: str


class ExtractionResult(BaseModel):
    """Schema representing structured data extracted from an uploaded document."""
    file_id: str
    document_type: str
    fields: Dict[str, Any]
    confidence: float
    status: str


class ApplicationCreate(BaseModel):
    """Request schema for instantiating a new service onboarding application."""
    service_id: str
    applicant_name: str
    applicant_email: str
    documents: List[str]


class ApplicationResponse(BaseModel):
    """Response schema returning application details and current processing state."""
    application_id: str
    service_id: str
    applicant_name: str
    status: str
    extracted_data: Optional[Dict[str, Any]] = None


class AuthenticationRequest(BaseModel):
    """Request schema for user authentication."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Response schema returning a session authentication token and user profile metadata."""
    token: str
    user_id: str
    email: str


class UserRegistrationRequest(BaseModel):
    """Request schema for creating a new user account."""
    username: str
    password: str
    email: Optional[str] = ""
    name: str = ""
    full_name: Optional[str] = None
    birthday: Optional[str] = None
    gender: Optional[str] = None


class FAQRequest(BaseModel):
    """Request schema for querying the system FAQ / policy assistance."""
    question: str
    context: Optional[str] = None


class FAQResponse(BaseModel):
    """Response schema returning grounded FAQ answers and citations."""
    answer: str
    sources: List[Dict[str, Any]]
    confidence: float


class ValidationRequest(BaseModel):
    """Request schema for standalone or application document validation."""
    application_id: str
    validation_type: str = "document"
    documents: Optional[List[Dict[str, Any]]] = None
    entry_id: Optional[str] = None


class ValidationResult(BaseModel):
    """Response schema summarizing document and cross-document validation checks."""
    application_id: str
    passed: bool
    checks: List[Dict[str, Any]]
    recommendations: List[str]


class ServiceCatalogItem(BaseModel):
    """Schema describing an onboarding service offered in the system catalog."""
    id: str
    name: str
    description: str
    required_documents: List[str]
    status: str  # "available" or "coming_soon"
    fields: Dict[str, str]


class ServiceCatalogResponse(BaseModel):
    """Response schema providing the full directory of onboarding services."""
    services: List[ServiceCatalogItem]
    coming_soon: List[ServiceCatalogItem]


class ChatMessage(BaseModel):
    """Request schema for user interaction with conversational AI agents."""
    query: str
    context_limit: int = 5
    token: Optional[str] = None


class ChatResponse(BaseModel):
    """Response schema returning synthesized assistant reply and conversational intent."""
    response: str
    intent: Optional[str] = None
    matched_service: Optional[str] = None


class DocumentMatch(BaseModel):
    """Schema recording matching outcome between two documents (e.g., Identity vs Passport)."""
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
