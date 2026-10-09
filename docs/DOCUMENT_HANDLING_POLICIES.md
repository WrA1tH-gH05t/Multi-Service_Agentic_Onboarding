# Document Handling and Extraction Policies

## Document Control
- **Version:** 1.0
- **Date:** 2024-01-01
- **Purpose:** Define how the system handles document uploads, extraction, and validation.

---

## 1. Document Acceptance Policy

### 1.1 File Content Verification
The system must verify file content by looking at actual content (magic bytes), NOT file extension or name:
- JPEG files: Start with `FF D8 FF`
- PNG files: Start with `89 50 4E 47`
- PDF files: Start with `%PDF-`
- TIFF files: Start with `49 49 2A 00` or `4D 4D 00 2A`

**Forbidden:** Accepting files based on extension alone. A renamed `.txt` file to `.pdf` must be caught before reaching the extraction pipeline.

### 1.2 Duplicate Upload Prevention
- Uploading the same document twice must NOT create duplicate records
- The system must check for duplicate uploads using content hashing (SHA-256)
- If a duplicate is detected, the system should inform the user and skip processing

### 1.3 Partial Upload Handling
- Partial or interrupted uploads must NOT leave broken, half-saved files on disk
- The system must use atomic writes: write to temporary file, then move to final location
- If an upload is interrupted, the temporary file must be cleaned up

### 1.4 Cross-Service Document Contamination Prevention
- If a customer switches services mid-conversation, documents uploaded for the previous service must NOT attach to the wrong service
- Each service session maintains its own document queue
- When a user switches services, the system must confirm whether to carry over documents or start fresh

---

## 2. Document Type Specific Policies

### 2.1 National ID Card Extraction
**For:** Basic Registration, Premium/Cross Border

**Mandatory Fields:**
- `document_type`: Must be "national_id"
- `issuing_country`: Full country name
- `surname`: Last name
- `given_name`: First name
- `full_name`: Complete name as printed
- `date_of_birth`: Original format from document
- `date_of_expiry`: Must be in the future (not expired)
- `document_number`: Unique document number

**Optional Fields:**
- `nationality`
- `place_of_birth`
- `sex`
- `date_of_issue`
- `authority`
- `address`
- `mrz` (Machine Readable Zone)
- `signature`
- `photo`

**Validation Rules:**
1. Document must not be expired
2. All mandatory fields must be present and non-empty
3. Date format must be consistent with document type
4. Country code must match issuing country

### 2.2 Passport Extraction
**For:** Premium/Cross Border

**Mandatory Fields:**
- `document_type`: Must be "passport"
- `issuing_country`: Full country name
- `surname`: Last name
- `given_name`: First name
- `full_name`: Complete name as printed
- `date_of_birth`: Original format from document
- `date_of_expiry`: Must be in the future (not expired)
- `document_number`: Passport number
- `mrz`: Machine Readable Zone text (2 lines)

**Optional Fields:**
- `nationality`
- `place_of_birth`
- `sex`
- `date_of_issue`
- `authority`
- `address`
- `signature`
- `photo`

**Validation Rules:**
1. Document must not be expired
2. MRZ must be present and valid (check checksum)
3. All mandatory fields must be present and non-empty
4. Country code in MRZ must match issuing country

### 2.3 Driving Licence Extraction
**For:** Mobility/Rental

**Mandatory Fields:**
- `document_type`: Must be "driving_license"
- `issuing_country`: Full country name
- `surname`: Last name
- `given_name`: First name
- `full_name`: Complete name as printed
- `date_of_birth`: Original format from document
- `date_of_expiry`: Must be in the future (not expired)
- `document_number`: Licence number
- `license_class`: Class of licence (e.g., A, B, C)

**Optional Fields:**
- `nationality`
- `place_of_birth`
- `sex`
- `date_of_issue`
- `authority`
- `address`
- `signature`
- `photo`

**Validation Rules:**
1. Document must not be expired
2. All mandatory fields must be present and non-empty
3. Licence class must be appropriate for the rental category
4. Country code must match issuing country

---

## 3. Field Extraction Policy

### 3.1 Extraction Approach
The system uses vision-language models (Qwen2.5-VL 3B) via Ollama for field extraction:
- Images are converted to base64-encoded PNG
- Model extracts structured JSON fields
- Low temperature (0.1) for accurate extraction
- Retry logic with fallback to different extraction approaches

### 3.2 PDF Processing
- PDFs are converted to page images (2x zoom = ~300 DPI)
- Multi-page PDFs are processed page by page
- Results from all pages are merged using a strategy: take non-empty values from the first page, fill in missing from others
- Front/back sides are identified and separated

### 3.3 Extraction Quality Rules
1. **Exact match is required.** Every extracted value must match the golden dataset exactly.
2. **Report results separately by document type and capture condition.** A clean photo and a partly hidden one must not be judged identically.
3. **Low confidence results must be surfaced.** If confidence is genuinely low, ask for a better photo instead of silently saving a guess as fact.
4. **No guessing.** If a field cannot be read, return null or empty string, never a guess.

### 3.4 Extraction Error Handling
| Error Type | System Response |
|------------|----------------|
| Wrong document type | Tell customer exactly what is needed |
| Right type but unclear image | Ask for a clearer photo, specify what would make it clearer |
| Same problem happens twice | Stop asking and hand case to validation agent |
| Extraction fails after retries | Hand case to human review |

---

## 4. Cross-Document Validation Policy

### 4.1 Premium/Cross Border Validation
For services requiring multiple documents (Premium/Cross Border), the system must validate that shared fields agree across documents:

**Fields to Compare:**
- `surname` (last name)
- `given_name` (first name)
- `date_of_birth`

**Validation Rules:**
1. Names must match exactly (case-insensitive comparison)
2. Date of birth must match exactly (after format normalization)
3. If any field disagrees, flag as mismatch and escalate to human review
4. All shared fields must agree for automatic approval

### 4.2 Validation Process
1. Extract fields from all documents
2. Compare shared fields across documents
3. If all agree → mark as valid
4. If any disagree → flag mismatch and escalate to human review
5. Report specific field(s) that disagree

---

## 5. Human Review Policy

### 5.1 Escalation Threshold
The system follows this escalation logic:

| Scenario | Action |
|----------|--------|
| All fields correct | Auto-accept |
| Some fields wrong (8/10) | Escalate to human review |
| All fields wrong or missing | Auto-reject |
| Extraction confidence genuinely low | Escalate to human review |
| Cross-document mismatch | Escalate to human review |

### 5.2 Human Review Record Format
Human review records must include:
- Exactly which fields are in question (not just a flag on the whole record)
- The extracted value for each disputed field
- The golden dataset value for comparison
- The system's confidence score for each disputed field
- Any contextual notes from the validation agent

### 5.3 Worst Case Monitoring
The system tracks **auto-accepted records with undetected errors** separately from all other metrics. This is the worst-case scenario — a record accepted without any error detection — and must be counted and reported on its own, never blended into a single accuracy number.

---

## 6. Capture Condition Policies

### 6.1 Capture Conditions in MIDV-500 Dataset
The system must handle the following capture conditions:
- **Table:** Top-down, flat surface (highest quality)
- **Handheld:** Angled, perspective distortion
- **Cluttered:** Busy background
- **Partial occlusion:** Part of document out of frame
- **Glare and shadow:** Lighting artifacts

### 6.2 Quality Assessment
The system must assess document quality and report results separately by capture condition:
- High quality (table): Expect >95% field extraction accuracy
- Medium quality (handheld): Expect 85-95% accuracy
- Low quality (cluttered, partial): Expect 70-85% accuracy
- Very low quality (glare, shadow): Expect <70% accuracy, escalate to human review

---

## 7. Security Policies

### 7.1 Prompt Injection Resistance
The system must NOT treat text inside documents that looks like instructions (e.g., "ignore all previous instructions") as real instructions.

### 7.2 Data Isolation
Every extraction result must be scoped to the logged-in user's account. One user must never be able to access another user's extracted data.

---

## 8. Appendix A: Field Extraction Prompt Examples

### 8.1 National ID Card Prompt
```
You are an expert document analyst specializing in government-issued identity documents.
Extract ALL relevant fields from the provided National ID card image.

FIELDS TO EXTRACT:
- document_type: national_id
- issuing_country: Full country name
- surname: Last name
- given_name: First name
- full_name: Complete name
- date_of_birth: Date of birth (preserve original format)
- date_of_expiry: Expiry date
- document_number: Main document number
- mrz: Machine Readable Zone (if present)

RULES:
- Extract EXACTLY what you see — do not infer missing data
- Use empty string for fields not visible
- For dates, preserve the original format
- Return ONLY valid JSON — no markdown, no explanation
```

### 8.2 Passport Prompt
```
You are an expert document analyst specializing in government-issued identity documents.
Extract ALL relevant fields from the provided Passport image.

FIELDS TO EXTRACT:
- document_type: passport
- issuing_country: Full country name
- surname: Last name
- given_name: First name
- full_name: Complete name
- date_of_birth: Date of birth
- date_of_expiry: Expiry date
- document_number: Passport number
- mrz: Machine Readable Zone (2 lines)

RULES:
- Extract EXACTLY what you see — do not infer missing data
- MRZ must be present and valid
- Use empty string for fields not visible
- Return ONLY valid JSON — no markdown, no explanation
```

### 8.3 Driving Licence Prompt
```
You are an expert document analyst specializing in government-issued identity documents.
Extract ALL relevant fields from the provided Driving Licence image.

FIELDS TO EXTRACT:
- document_type: driving_license
- issuing_country: Full country name
- surname: Last name
- given_name: First name
- full_name: Complete name
- date_of_birth: Date of birth
- date_of_expiry: Expiry date
- document_number: Licence number
- license_class: Class of licence

RULES:
- Extract EXACTLY what you see — do not infer missing data
- Licence class must be present and valid
- Use empty string for fields not visible
- Return ONLY valid JSON — no markdown, no explanation
```

---

*This policy document defines the document handling and extraction rules for the system. All document processing must follow these rules to ensure accuracy and consistency.*
