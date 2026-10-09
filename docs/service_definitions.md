# Service Definitions

## 1. Basic Registration

**Service ID:** basic_registration  
**Status:** Available  
**Processing Time:** 1-2 business days  
**Documents Required:** National ID card (one document)

### What is this service?
Basic Registration is the simplest onboarding service. It allows a customer to register with the platform using a single National ID card. The process is straightforward and designed for domestic customers who already possess a valid national identity document.

### How does the process work?
1. The customer enters the Basic Registration service through the conversational agent.
2. The agent confirms the service details and explains the requirements.
3. The customer uploads a single National ID card (photo, scanned image, or PDF).
4. The system automatically extracts fields from the document: name, date of birth, document number, expiry date, and issuing country.
5. The system validates the extracted data against internal rules (expiry date in the future, field formats, mandatory fields present).
6. If all checks pass, the application is marked as complete and stored.
7. The customer receives a confirmation message with their application status.
8. If any issues are found, the system either asks for a clearer image, sends the case to human review, or rejects it with specific reasons.

### What happens after submission?
Completed applications are stored in the system with a clear status: complete, incomplete, or requiring human review. The customer can check their application status at any time through the agent.

### Why this is simple
Only one document type is required, so there is no cross-document validation needed. The agent does not need to reconcile conflicting information between documents. This is the entry-level service for new customers.

---

## 2. Premium / Cross Border

**Service ID:** premium_crossborder  
**Status:** Available  
**Processing Time:** 3-5 business days  
**Documents Required:** National ID card + Passport (two documents)

### What is this service?
The Premium/Cross Border service is designed for international verification purposes. It requires two identity documents (a National ID card AND a Passport) and includes cross-document validation to ensure the identity information matches across both documents.

### How does the process work?
1. The customer enters the Premium/Cross Border service through the conversational agent.
2. The agent explains that TWO documents are required: a National ID card and a Passport.
3. The customer uploads the first document (e.g., National ID card).
4. The system extracts fields and confirms receipt.
5. The agent then asks for the second document (e.g., Passport).
6. The customer uploads the second document.
7. The system extracts fields from the Passport.
8. **Cross-validation:** The system compares the name, date of birth, and document number between both documents to ensure they refer to the same person.
9. If all documents are present, readable, and cross-validated, the application is marked as complete.
10. If any discrepancies are found between the two documents, the case is escalated to human review.

### Why two documents?
Cross-border services require additional verification because the customer's identity will be used across international boundaries. Having both a National ID card and a Passport provides a more complete identity picture and reduces fraud risk.

### What if the documents don't match?
If the extracted name, date of birth, or document number differs between the National ID card and the Passport, the system flags this as a mismatch and escalates to human review. The customer is informed that their documents could not be automatically verified and that a human will review their case.

---

## 3. Mobility / Rental

**Service ID:** mobility_rental  
**Status:** Available  
**Processing Time:** Same day (if document valid)  
**Documents Required:** Driving licence (one document)

### What is this service?
The Mobility/Rental service is for customers who need to register for vehicle rental or mobility-related services. Unlike the other services that use National ID cards or passports, this service specifically requires a driving licence, which has a different document structure and layout.

### How does the process work?
1. The customer enters the Mobility/Rental service through the conversational agent.
2. The agent explains that a valid driving licence is required.
3. The customer uploads their driving licence.
4. The system uses the **driving licence extraction logic** (not the National ID card logic) to extract fields: name, date of birth, document number, expiry date, license class, and issue date.
5. The system validates: the licence must not be expired, all mandatory fields must be present, and the licence class must be appropriate for the rental category.
6. If all checks pass, the application is marked complete.
7. If the licence is expired or key fields are missing, the system rejects the application with specific reasons.

### Why a separate extraction logic?
Driving licences have a fundamentally different layout, field structure, and issuing authority format compared to National ID cards and passports. Reusing the ID card extraction logic would lead to poor accuracy. The driving licence service has its own field definitions and validation rules tailored to this specific document type.

---

## Coming Soon Services

### Bank Account Opening
- **Documents:** Passport + Utility bill
- **Processing Time:** 2-3 business days
- **Description:** Open a new bank account. Requires proof of identity and proof of address.

### Insurance Registration
- **Documents:** National ID card + Medical report
- **Processing Time:** 3-5 business days
- **Description:** Register for insurance coverage. Requires proof of identity and relevant medical documents.

### SIM Card Registration
- **Documents:** National ID card
- **Processing Time:** Same day
- **Description:** Register a new SIM card with a mobile carrier. Requires national ID only.

### Loan Application
- **Documents:** National ID card + Pay slip + Bank statement
- **Processing Time:** 5-7 business days
- **Description:** Apply for a personal loan. Requires identity verification and income proof.

### Utility Connection
- **Documents:** National ID card + Property deed
- **Processing Time:** 2-3 business days
- **Description:** Set up electricity, water, or gas service. Requires identity and property documentation.

### Tenancy Agreement
- **Documents:** National ID card + Employment letter
- **Processing Time:** 1-2 business days
- **Description:** Sign a rental tenancy agreement. Requires identity verification and employment proof.

### Professional License
- **Documents:** National ID card + Qualifications + Reference letter
- **Processing Time:** 5-7 business days
- **Description:** Apply for a professional service license. Requires identity, academic qualifications, and professional references.

### Vehicle Registration
- **Documents:** Driving licence + Insurance certificate
- **Processing Time:** 1-2 business days
- **Description:** Register a vehicle. Requires a valid driving licence and proof of insurance.

### Health Insurance Card
- **Documents:** National ID card + Employer certificate
- **Processing Time:** 3-5 business days
- **Description:** Apply for a government health insurance card. Requires identity and employment verification.
