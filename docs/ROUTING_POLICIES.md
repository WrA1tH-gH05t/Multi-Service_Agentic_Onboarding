# System Routing and Intent Detection Policies

## Document Control
- **Version:** 1.0
- **Date:** 2024-01-01
- **Purpose:** Define how the system routes user requests to the correct service and detects user intent.

---

## 1. Routing Policy

### 1.1 Core Principle
**Getting the service right matters.** Sending someone to the wrong service is a failure, not a small mistake.

### 1.2 Three-Way Distinction Policy
The system must always maintain a clear distinction between:
1. **Available service** — Service is live and can process applications
2. **Coming soon service** — Service exists in catalogue but is not ready
3. **Unknown service** — Service is not in catalogue at all

**This distinction must never be confused.**

### 1.3 Routing Algorithm
The system uses fixed keyword matching (not LLM reasoning) for routing because:
- Routing errors are explicitly called out as failures in the spec
- LLM reasoning is non-deterministic and can change between runs
- Fixed matching is auditable and testable

**Routing Steps:**
1. Check if input mentions a "coming soon" service → Return COMING_SOON status
2. Check for exact keyword match → Return AVAILABLE status if found
3. Check for fuzzy matching (any keyword in input) → Return AVAILABLE status if match found
4. No match → Return NOT_FOUND status

### 1.4 Keyword Index
The following keywords are indexed for routing:
- Service IDs (e.g., `basic_registration`, `premium_crossborder`, `mobility_rental`)
- Service names (e.g., "Basic Registration", "Premium / Cross Border", "Mobility / Rental")
- Required document types (e.g., `national_id`, `passport`, `driving_license`)
- Service category terms (e.g., "registration", "cross border", "rental", "bank", "insurance")

---

## 2. Intent Detection Policy

### 2.1 Question vs. Application Intent
**Telling apart someone asking a question from someone ready to apply matters just as much.**

- Pushing someone into uploading documents when they were only asking is wrong
- Stalling someone who is clearly ready to apply is equally wrong

### 2.2 Intent Detection Rules

**Question Intent Indicators:**
- "What is..."
- "How long..."
- "How does..."
- "Do I need..."
- "Can I use..."
- "Tell me about..."
- "What happens..."

**Application Intent Indicators:**
- "I want to apply..."
- "Let's start..."
- "I'd like to sign up..."
- "I'm ready to..."
- "Help me apply..."
- Direct document upload with no prior questions

### 2.3 Intent Detection Examples

| User Input | Detected Intent | System Action |
|------------|----------------|---------------|
| "What is Basic Registration?" | Question | Provide FAQ answer |
| "How long does Premium/Cross Border take?" | Question | Provide processing time |
| "I want to apply for Basic Registration" | Application | Begin application process |
| "Let's start Premium/Cross Border" | Application | Begin application process |
| "What documents do I need for Mobility/Rental?" | Question | Provide document requirements |
| "Here's my National ID card" (with upload) | Application | Process document upload |

---

## 3. Service Classification Policy

### 3.1 Available Services
These services are live and can process applications:

| Service ID | Name | Status | Processing Time |
|------------|------|--------|-----------------|
| `basic_registration` | Basic Registration | Available | 1-2 business days |
| `premium_crossborder` | Premium / Cross Border | Available | 3-5 business days |
| `mobility_rental` | Mobility / Rental | Available | Same day (if document valid) |

### 3.2 Coming Soon Services
These services exist in the catalogue but are not ready:

| Service ID | Name | Status |
|------------|------|--------|
| `bank_account` | Bank Account Opening | Coming Soon |
| `insurance` | Insurance Registration | Coming Soon |
| `sim_registration` | SIM Card Registration | Coming Soon |
| `loan_application` | Loan Application | Coming Soon |
| `utility_connection` | Utility Connection | Coming Soon |
| `tenancy_agreement` | Tenancy Agreement | Coming Soon |
| `professional_license` | Professional License | Coming Soon |
| `vehicle_registration` | Vehicle Registration | Coming Soon |
| `health_insurance` | Health Insurance Card | Coming Soon |

### 3.3 Not Found
Any service not in the above lists is considered "not found."

---

## 4. Service-Specific Routing Rules

### 4.1 Basic Registration Routing
**Trigger Keywords:** `basic`, `registration`, `national_id`, `id card`

**Routing Logic:**
1. Check if user mentions "basic registration" or "national ID"
2. If yes, route to `basic_registration` service
3. If user has passport instead of national ID, suggest they may not be ready for this service

**Sample Flow:**
```
User: "I want to register with my national ID"
System: "Great! Basic Registration requires a National ID card. Please upload your National ID card."

User: "I only have a passport"
System: "Basic Registration requires a National ID card. If you only have a passport, you may want to ask about our Premium/Cross Border service, which requires both a National ID card and Passport."
```

### 4.2 Premium / Cross Border Routing
**Trigger Keywords:** `premium`, `cross border`, `passport`, `international`

**Routing Logic:**
1. Check if user mentions "premium", "cross border", or "passport"
2. If yes, route to `premium_crossborder` service
3. Confirm user understands TWO documents are required

**Sample Flow:**
```
User: "I need to do cross border verification"
System: "Premium/Cross Border service requires TWO documents: a National ID card AND a Passport. Would you like to start the application?"

User: "Yes, let's start"
System: "Great! First, please upload your National ID card."
```

### 4.3 Mobility / Rental Routing
**Trigger Keywords:** `mobility`, `rental`, `driving licence`, `vehicle`

**Routing Logic:**
1. Check if user mentions "mobility", "rental", "driving licence", or "vehicle"
2. If yes, route to `mobility_rental` service
3. Confirm user has a valid driving licence

**Sample Flow:**
```
User: "I need to register for vehicle rental"
System: "Mobility/Rental service requires a valid driving licence. Please upload your driving licence to begin."

User: "I have my National ID card instead"
System: "Mobility/Rental specifically requires a driving licence, not a National ID card. Please upload your driving licence."
```

---

## 5. Coming Soon Service Routing Policy

### 5.1 Handling Coming Soon Requests
When a user asks about a coming soon service:
1. Recognize the service is not available yet
2. State clearly that the service is not available
3. Do NOT pretend the service does not exist
4. Do NOT try to process the application
5. Provide a brief description of what the service will involve

### 5.2 Coming Soon Service Responses

**Bank Account Opening:**
```
User: "I want to open a bank account"
System: "Bank Account Opening is a coming soon service. It will require a passport and a utility bill, with processing taking 2-3 business days. Please check back when it becomes available."
```

**SIM Card Registration:**
```
User: "I need to register a SIM card"
System: "SIM Card Registration is a coming soon service. It will require only a National ID card and be processed same day. Please check back when it becomes available."
```

**Loan Application:**
```
User: "I want to apply for a loan"
System: "Loan Application is a coming soon service. It will require a National ID card, pay slip, and bank statement, with processing taking 5-7 business days. Please check back when it becomes available."
```

### 5.3 Coming Soon Service Keywords
The following keywords are indexed for coming soon services:
- `bank`, `account`, `banking` → Bank Account Opening
- `insurance` → Insurance Registration, Health Insurance Card
- `sim`, `mobile`, `phone` → SIM Card Registration
- `loan`, `lending`, `credit` → Loan Application
- `utility`, `electricity`, `water`, `gas` → Utility Connection
- `tenancy`, `rental`, `lease` → Tenancy Agreement
- `professional`, `license`, `certification` → Professional License
- `vehicle`, `car`, `motorcycle` → Vehicle Registration
- `health`, `medical insurance` → Health Insurance Card

---

## 6. Unknown Service Routing Policy

### 6.1 Handling Unrecognised Services
When a user asks about a service not in the catalogue:

**The system must:**
1. State clearly that the service is not recognised
2. NOT pretend the service exists
3. NOT try to invent requirements or rules
4. Suggest checking the list of available services

**Sample Response:**
```
User: "I want to register for a visa"
System: "I don't recognise that service. Our current catalogue includes Basic Registration, Premium/Cross Border, and Mobility/Rental services. Would you like to know more about any of these?"
```

---

## 7. Escalation and Handoff Policy

### 7.1 When to Escalate to Human Review
The system must escalate to human review when:
1. Extracted fields are partly wrong (e.g., 8 out of 10 correct)
2. Extraction confidence is genuinely low
3. Documents don't match (for Premium/Cross Border)
4. Same problem happens twice during upload
5. User explicitly requests human assistance

### 7.2 Human Review Record Format
Human review records must include:
- Exactly which fields are in question (not just a flag on the whole record)
- The extracted value for each disputed field
- The golden dataset value for comparison
- The system's confidence score for each disputed field
- Any contextual notes from the validation agent

---

## 8. Security Policies

### 8.1 Prompt Injection Resistance
The system must NOT treat text inside documents that looks like instructions (e.g., "ignore all previous instructions") as real instructions.

### 8.2 Data Isolation
Every answer must be scoped to the logged-in user's account. One user must never be able to see another user's data, no matter how the question is phrased.

---

## 9. Appendix A: Routing Decision Tree

```
User Input
    │
    ├── Is it a question about a service?
    │   ├── Yes → Route to service FAQ
    │   │   ├── Available service → Answer from service definition
    │   │   ├── Coming soon service → Answer "coming soon" response
    │   │   └── Unknown service → Answer "not recognised" response
    │   │
    │   └── No → Is it an application request?
    │       ├── Yes → Begin application process
    │       │   ├── Available service → Start document collection
    │       │   ├── Coming soon service → Answer "coming soon" response
    │       │   └── Unknown service → Answer "not recognised" response
    │       │
    │       └── No → Clarification question
    │           ├── Ask user to clarify intent
    │           └── List available services
    │
    └── (handled by routing algorithm)
```

---

*This policy document defines the routing and intent detection rules for the system. All routing decisions must follow these rules to ensure correctness and consistency.*
