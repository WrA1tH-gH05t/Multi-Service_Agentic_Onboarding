"""Service Catalogue - Phase 1 & 2"""

from enum import Enum
from typing import Dict, List, Optional, Set


class ServiceStatus(str, Enum):
    """Enumeration of service availability statuses in the onboarding platform."""
    AVAILABLE = "available"
    COMING_SOON = "coming_soon"
    NOT_FOUND = "not_found"


class ServiceDefinition:
    """Represents a single service in the catalogue."""

    def __init__(
        self,
        service_id: str,
        name: str,
        description: str,
        required_documents: List[str],
        allowed_alternatives: Optional[Dict[str, List[str]]] = None,
        status: ServiceStatus = ServiceStatus.AVAILABLE,
        processing_time: str = "",
        definition_doc_path: str = "",
    ):
        """Initialize a ServiceDefinition instance."""
        self.service_id = service_id
        self.name = name
        self.description = description
        self.required_documents = required_documents
        self.allowed_alternatives = allowed_alternatives or {}
        self.status = status
        self.processing_time = processing_time
        self.definition_doc_path = definition_doc_path


class ServiceCatalogue:
    """Fixed catalogue for routing requests to the correct service."""

    def __init__(self):
        """Initialize ServiceCatalogue and populate service definitions and keyword indexes."""
        self._services: Dict[str, ServiceDefinition] = {}
        self._keyword_index: Dict[str, str] = {}  # keyword -> service_id
        self._build_catalogue()

    def _build_catalogue(self):
        """Build the complete service catalogue and construct inverted keyword index."""
        # === AVAILABLE SERVICES (Phase 1 + 2) ===

        self._services["basic_registration"] = ServiceDefinition(
            service_id="basic_registration",
            name="Basic Registration",
            description="Simple identity registration for standard services. "
            "Requires one National ID card. Processing takes 1-2 business days.",
            required_documents=["national_id"],
            allowed_alternatives={"national_id": ["driving_license"]},
            status=ServiceStatus.AVAILABLE,
            processing_time="1-2 business days",
            definition_doc_path="docs/basic_registration.pdf",
        )

        self._services["premium_crossborder"] = ServiceDefinition(
            service_id="premium_crossborder",
            name="Premium / Cross Border",
            description="Enhanced cross-border service requiring both National ID card "
            "and Passport. Used for international verification. Processing takes 3-5 business days.",
            required_documents=["national_id", "passport"],
            allowed_alternatives={},
            status=ServiceStatus.AVAILABLE,
            processing_time="3-5 business days",
            definition_doc_path="docs/premium_crossborder.pdf",
        )

        self._services["mobility_rental"] = ServiceDefinition(
            service_id="mobility_rental",
            name="Mobility / Rental",
            description="Vehicle rental and mobility service. Requires a valid "
            "driving licence. Must not reuse ID card extraction logic. Processing takes same day.",
            required_documents=["driving_license"],
            allowed_alternatives={"driving_license": []},
            status=ServiceStatus.AVAILABLE,
            processing_time="Same day (if document valid)",
            definition_doc_path="docs/mobility_rental.pdf",
        )

        # === COMING SOON SERVICES (Phase 2) ===
        self._services["bank_account"] = ServiceDefinition(
            service_id="bank_account",
            name="Bank Account Opening",
            description="Open a new bank account. Requires proof of identity and address. "
            "Coming soon.",
            required_documents=["passport", "utility_bill"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["insurance"] = ServiceDefinition(
            service_id="insurance",
            name="Insurance Registration",
            description="Register for insurance coverage. Requires ID and medical documents. "
            "Coming soon.",
            required_documents=["national_id", "medical_report"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["sim_registration"] = ServiceDefinition(
            service_id="sim_registration",
            name="SIM Card Registration",
            description="Register a new SIM card. Requires national ID only. "
            "Coming soon.",
            required_documents=["national_id"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["loan_application"] = ServiceDefinition(
            service_id="loan_application",
            name="Loan Application",
            description="Apply for a personal loan. Requires ID, income proof, and bank statements. "
            "Coming soon.",
            required_documents=["national_id", "pay_slip", "bank_statement"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["utility_connection"] = ServiceDefinition(
            service_id="utility_connection",
            name="Utility Connection",
            description="Set up electricity/water/gas service. Requires ID and property documents. "
            "Coming soon.",
            required_documents=["national_id", "property_deed"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["tenancy_agreement"] = ServiceDefinition(
            service_id="tenancy_agreement",
            name="Tenancy Agreement",
            description="Sign a rental tenancy agreement. Requires ID and employment proof. "
            "Coming soon.",
            required_documents=["national_id", "employment_letter"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["professional_license"] = ServiceDefinition(
            service_id="professional_license",
            name="Professional License",
            description="Apply for a professional service license. Requires ID, qualifications, "
            "and references. Coming soon.",
            required_documents=["national_id", "qualifications", "reference_letter"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        self._services["vehicle_registration"] = ServiceDefinition(
            service_id="vehicle_registration",
            name="Vehicle Registration",
            description="Register a vehicle. Requires driving licence and insurance proof. "
            "Coming soon.",
            required_documents=["driving_license", "insurance_certificate"],
            status=ServiceStatus.COMING_SOON,
            definition_doc_path="",
        )

        # Build keyword index for routing
        for svc in self._services.values():
            for keyword in [svc.service_id, svc.name.lower()]:
                self._keyword_index[keyword] = svc.service_id
            for doc in svc.required_documents:
                self._keyword_index[doc] = svc.service_id

    def match_service(self, user_input: str) -> tuple[ServiceStatus, Optional[ServiceDefinition]]:
        """Route a user request to the correct service."""
        input_lower = user_input.lower()

        # Check if input mentions a "coming soon" service using word boundary regex
        import re
        for svc_id, svc in self._services.items():
            if svc.status == ServiceStatus.COMING_SOON:
                patterns = [
                    r'\b' + re.escape(svc_id) + r'\b',
                    r'\b' + re.escape(svc_id.replace("_", " ")) + r'\b',
                    r'\b' + re.escape(svc.name.lower()) + r'\b',
                ]
                # Distinct service stem keywords
                if svc_id == "bank_account":
                    patterns.extend([r'\bbank\b', r'\bbank\s+account\b'])
                elif svc_id == "sim_registration":
                    patterns.extend([r'\bsim\b', r'\bsim\s+card\b'])
                elif svc_id == "loan_application":
                    patterns.extend([r'\bloan\b', r'\bmortgage\b'])
                elif svc_id == "utility_connection":
                    patterns.extend([r'\butility\b', r'\belectricity\b', r'\bwater\s+connection\b'])
                elif svc_id == "tenancy_agreement":
                    patterns.extend([r'\btenancy\b', r'\blease\s+agreement\b'])
                elif svc_id == "professional_license":
                    patterns.extend([r'\bprofessional\s+licen[sc]e\b'])
                elif svc_id == "vehicle_registration":
                    patterns.extend([r'\bvehicle\s+registration\b', r'\bcar\s+registration\b'])

                for pat in patterns:
                    if re.search(pat, input_lower):
                        return (ServiceStatus.COMING_SOON, svc)

        # Check exact keyword match
        if input_lower in self._keyword_index:
            svc = self._services[self._keyword_index[input_lower]]
            return (ServiceStatus.AVAILABLE, svc)

        # Check fuzzy matching (any keyword in input)
        for keyword, svc_id in self._keyword_index.items():
            if keyword in input_lower:
                svc = self._services[svc_id]
                if svc.status == ServiceStatus.AVAILABLE:
                    return (ServiceStatus.AVAILABLE, svc)

        # No match found
        return (ServiceStatus.NOT_FOUND, None)

    def get_service(self, service_id: str) -> Optional[ServiceDefinition]:
        """Get a service definition by ID."""
        return self._services.get(service_id)

    def get_all_services(self) -> List[ServiceDefinition]:
        """Get all registered services (both available and coming soon)."""
        return list(self._services.values())

    def get_available_services(self) -> List[ServiceDefinition]:
        """Get only active and available services."""
        return [s for s in self._services.values() if s.status == ServiceStatus.AVAILABLE]

    def answer_faq(self, question: str) -> tuple[str, float]:
        """Answer a FAQ question using keyword matching against service definitions."""
        q = question.lower()

        # Check if question is asking about a specific service
        stop_words = {"a", "an", "the", "for", "in", "to", "of", "and", "or", "is", "it", "i", "we", "you", "my", "your", "apply", "want", "need", "application", "service", "services"}
        for svc in self._services.values():
            keywords = [
                svc.service_id,
                svc.name.lower(),
            ]
            for doc in svc.required_documents:
                keywords.append(doc.lower())

            matches = sum(1 for kw in keywords if kw in q or any(word in q for word in kw.split() if word not in stop_words))

            if matches >= 2:
                answer = (
                    f"**{svc.name}**\n"
                    f"{svc.description}\n\n"
                    f"Required documents: {', '.join(svc.required_documents)}\n"
                    f"Processing time: {svc.processing_time}\n"
                    f"Status: {'Available' if svc.status == ServiceStatus.AVAILABLE else 'Coming Soon'}"
                )
                confidence = min(0.95, 0.5 + matches * 0.15)
                return answer, confidence

        # Generic help fallback
        available = [s for s in self._services.values() if s.status == ServiceStatus.AVAILABLE]
        available_names = ", ".join(s.name for s in available)
        answer = (
            f"I can help you with onboarding applications. Currently available services:\n\n"
            f"{available_names}\n\n"
            f"Which service are you interested in?"
        )
        return answer, 0.4


    def get_non_editable_fields(self, doc_type: str) -> Set[str]:
        """Return field names that are non-editable (biometric / immutable identity fields)."""
        dt = (doc_type or "").lower()
        if "passport" in dt:
            return {"passport_number", "date_of_birth", "nationality", "sex"}
        elif "driving" in dt or "license" in dt or "dl" in dt:
            return {"license_no", "date_of_birth", "traffic_code_no"}
        else:
            return {"national_id_number", "date_of_birth", "gender", "nationality"}


# Alias for backward compatibility
ServiceCatalogService = ServiceCatalogue
