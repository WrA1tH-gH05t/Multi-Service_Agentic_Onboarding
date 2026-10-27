# Document 2: Catalog-Driven Routing Approach & Full-Catalog Scalability

**Project:** Moro Hub Multi-Service Document Intake & Verification System  
**Version:** 2.1 (Dynamic Catalog & Service-Agnostic Wizard)  
**Author:** AI Engineering & Architecture Team  
**Scope:** Routing Architecture, Dynamic Service Scaling, Zero-Hardcoding Principles

---

## Executive Summary

Enterprise document onboarding systems frequently collapse into unmaintainable codebases when route handlers and frontend views contain hardcoded procedural logic for specific services (e.g., `if (service == "mobility") { extract_driver_license(); }`). 

The Moro Hub system adopts a **Declarative Catalog-Driven Routing Architecture**. The onboarding wizard, document requirements evaluator, schema selector, and validation workflows are completely generic. All service constraints, required credentials, alternatives, and routing rules are defined as data specifications in the Service Catalog. 

This design allows the platform to scale from 3 initial services to 15+ catalog services without modifying backend route logic or frontend UI components.

---

## 1. Architectural Principles of Catalog-Driven Routing

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Central Service Catalog Engine                     │
│  (Definitions: ID, Name, Category, Required Docs, SLA, Validation Rules)│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Introspected At Runtime
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌───────────────────┐       ┌───────────────────┐       ┌───────────────────┐
│ Wizard Session    │       │ Document Slot     │       │ Field Normalizer  │
│ Orchestrator      │       │ Evaluator         │       │ & Extractor       │
│ - Reads required  │       │ - Evaluates slot  │       │ - Maps schema by  │
│   credential list │       │   completion &    │       │   document kind,  │
│ - Sets state flow │       │   alternatives    │       │   not service ID  │
└───────────────────┘       └───────────────────┘       └───────────────────┘
```

1. **Decoupling Services from Documents:** Services do not dictate bespoke endpoints. Instead, services specify a set of required **Document Kinds** (e.g., `national_id`, `passport`, `driving_license`, `utility_bill`).
2. **Document Kind Polymorphism:** Document extraction schemas and security checks attach to the **Document Kind**, not the service. A `driving_license` uploaded for `mobility_rental` or for a future `fleet_management` service invokes the exact same extraction and validation pipeline.
3. **Stateless Declarative Configuration:** Adding a new service involves registering a schema dictionary or YAML specification. Zero new API endpoints, zero new database migrations, and zero frontend conditional branches are needed.

---

## 2. Dynamic Routing Implementation

### 2.1 The Unified Wizard Pipeline
The application exposes a single, service-agnostic REST lifecycle under `/api/v1/wizard/*`:

* `POST /wizard/create?service_id={id}`: Initializes onboarding session by querying the catalog for the target service metadata.
* `POST /wizard/{session_id}/name`: Binds applicant identity for downstream cross-document matching.
* `POST /wizard/{session_id}/upload?doc_type={type}`: Receives and processes any document kind specified by the service.
* `GET /wizard/{session_id}/review`: Dynamically renders all extracted fields across all received documents.
* `POST /wizard/{session_id}/confirm`: Commits applicant review verification.
* `POST /wizard/{session_id}/submit`: Atomically persists the completed application and transitions status.

### 2.2 Dynamic Requirement Resolution (`_required_docs`)
In [app/routes/wizard.py](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/app/routes/wizard.py), the wizard dynamically interrogates the catalog:

```python
def _required_docs(state, service_id: str) -> List[str]:
    """Retrieve required document types dynamically from the service catalog."""
    catalog = state.get("catalog")
    if catalog:
        for attr in ("get_service", "get"):
            fn = getattr(catalog, attr, None)
            if callable(fn):
                try:
                    svc = fn(service_id)
                    docs = svc.get("documents_required") if isinstance(svc, dict) else getattr(svc, "documents_required", None)
                    if docs:
                        return [_norm_doc(d) for d in docs]
                except Exception:
                    pass
    return _FALLBACK_REQUIRED.get(service_id, ["national_id"])
```

### 2.3 Polymorphic Classification via Document Kind (`_kind`)
Instead of checking which service initiated the request, the extraction and validation systems inspect the uploaded document type using the classification helper:

```python
def _kind(doc_type: str) -> str:
    d = doc_type.lower()
    if "passport" in d:
        return "passport"
    if "national" in d or "eid" in d or "emirates" in d:
        return "national_id"
    if "licen" in d or "driving" in d:
        return "driving_license"
    if "utility" in d or "bill" in d or "dewa" in d:
        return "utility_bill"
    return "other"
```

This single helper decouples business service routing from structural document extraction:
* If `_kind(doc_type) == "driving_license"`, the system automatically selects `DRIVING_LICENSE_SCHEMA` (11 fields including gear type and glasses logo) regardless of whether the service is vehicle rental, chauffeur services, or logistics onboarding.
* If `_kind(doc_type) == "passport"`, it selects `PASSPORT_SCHEMA`.
* If `_kind(doc_type) == "national_id"`, it selects `NATIONAL_ID_SCHEMA`.

---

## 3. Scaling to the Full Service Catalog

The Moro Hub catalog contains current active services and planned future expansions:

| Service ID | Service Name | Status | Required Credentials | Processing SLA |
|---|---|---|---|---|
| `basic_registration` | Basic Registration | Available | National ID (1 document) | 1–2 business days |
| `premium_crossborder`| Cross Border Verification | Available | National ID + Passport (2 documents) | 3–5 business days |
| `mobility_rental` | Mobility / Vehicle Rental | Available | Driving License (1 document) | Same day / Instant |
| `bank_account` | Bank Account Opening | Coming Soon | Passport + Utility Bill | 2–3 business days |
| `insurance` | Insurance Onboarding | Coming Soon | National ID + Medical Form | 3–5 business days |
| `sim_registration` | SIM Card Registration | Coming Soon | National ID | Instant |
| `tenancy_agreement` | Tenancy Registration | Coming Soon | National ID + Tenancy Contract | 1–2 business days |
| `utility_connection`| Utility Connection | Coming Soon | National ID + Title Deed/Tenancy | 1 business day |

### Walkthrough: Adding "Commercial Fleet Onboarding" in 3 Steps
To deploy an entirely new enterprise service (`commercial_fleet` requiring `trade_license` and `driving_license`):

1. **Step 1: Register in Service Catalog (`services/catalog.py`)**
   ```python
   Service(
       id="commercial_fleet",
       name="Commercial Fleet Driver Onboarding",
       description="Corporate driver credentialing and validation",
       status="available",
       documents_required=["trade_license", "driving_license"],
       processing_time="Same day"
   )
   ```
2. **Step 2: Define Document Kind Schema & Mandatory Constraints**
   * If `trade_license` is new, declare `TRADE_LICENSE_SCHEMA` in `services/generation.py` and its mandatory field labels in `_MANDATORY["trade_license"]`.
   * `driving_license` is already defined with all 11 fields, so it requires zero additional configuration.
3. **Step 3: Deploy**
   * The backend dynamically surfaces the new service in `/api/v1/services`.
   * The frontend sidebar and catalog views render the service card with its icon, required document pills, and SLA badge automatically.
   * Clicking "Ask about this" or starting an application triggers the generic wizard, which prompts for Document 1 (`trade_license`), runs extraction, prompts for Document 2 (`driving_license`), validates both, and submits.

**Zero lines of code in route handlers or UI components were altered.**

---

## 4. Frontend Dynamic Rendering Architecture

The frontend (`app/static/index.html`) mirrors this catalog-driven design:

1. **Dynamic Step Bar:** `StepIndicator` calculates its total steps dynamically by mapping `wizardRequiredDocs()`:
   ```javascript
   const uploadStepKeys = docs.map(docToStepKey);
   const allSteps = ['name', ...uploadStepKeys, 'review'];
   ```
2. **Dynamic Review Grid:** `WizardReview` iterates over the returned `document_checks` array. Field labels are normalized through an automated title-casing and alias resolver, guaranteeing that 5 fields, 11 fields, or 25 fields render in a clean responsive grid with individual masking and inline editing.
3. **Document-Agnostic State Updates:** When a document is accepted, the frontend updates its slot array:
   ```javascript
   const nextDoc = wizardRequiredDocs().find(d => !docs.some(u => u.docType === d));
   ```
   If a next required document exists, it guides the applicant to the next slot; when all catalog-specified documents are present, it seamlessly advances to the review screen.
