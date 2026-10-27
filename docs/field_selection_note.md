# Field Selection Note

## Decision Rationale: Which Fields to Extract and Why

For each document type, I have decided which fields are mandatory and which are optional. This is not a one-size-fits-all approach — each document type has its own field set tailored to its structure and purpose. The rationale for each field is documented below.

---

## 1. National ID Card

### Mandatory Fields

| Field | Rationale |
|-------|-----------|
| **Name** | Core identity field. Required for all cross-document validation (matching ID to passport, etc.). Without the name, the system cannot confirm that multiple documents belong to the same person. |
| **Date of Birth** | Core identity field. Provides an additional unique identifier for cross-document matching. Also used for age-related service eligibility checks (e.g., rental services require minimum age). |
| **Document Number** | Unique identifier for the document. Essential for deduplication (ensuring the same document is not uploaded twice) and for traceability (each document number is tracked in the system). |
| **Expiry Date** | Critical validation field. An expired ID card should not be accepted. This is checked automatically during validation. |
| **Issuing Country** | Provides context for the document. Used for geographic eligibility checks and for understanding which document format/rules to expect. |

### Optional Fields

| Field | Rationale |
|-------|-----------|
| **Issuing Authority** | Useful for fraud detection (checking if the issuing authority is legitimate) but not essential for basic identity verification. Can be filled by human reviewer if missing. |
| **Address** | Useful for address-verification services but not required for identity confirmation. Many ID cards do not include a full address. |
| **National ID Number** (if different from document number) | Redundant for most purposes. Kept optional because some countries use two different numbers. |
| **Gender** | Not relevant for the three services defined. Could be used for demographic analytics but not for identity verification. |

---

## 2. Passport

### Mandatory Fields

| Field | Rationale |
|-------|-----------|
| **Name** | Core identity field. Must match the name on the National ID card for the premium service. |
| **Date of Birth** | Core identity field. Must match the date of birth on the National ID card. |
| **Document Number (Passport Number)** | Unique identifier. Cross-checked against the National ID card number for identity confirmation. |
| **Expiry Date** | Critical validation field. Passports have strict validity periods. An expired passport should not be accepted. |
| **Issuing Country** | Used to determine passport validity and geographic eligibility. Essential for cross-border services. |
| **Passport Type** (e.g., ordinary, diplomatic, service) | Distinguishes between passport categories. Important for regulatory compliance — some services may only accept ordinary passports. |

### Optional Fields

| Field | Rationale |
|-------|-----------|
| **Place of Birth** | Useful for additional identity confirmation but not essential. Can be used in human review if available. |
| **Issue Date** | Provides context for passport age but not used for validation decisions. |
| **Address** | Rarely printed on passports. Not relied upon for verification. |
| **Sex/Gender** | Not relevant for the defined services. |
| **Authority Signature** | Relevant for fraud detection but requires visual analysis beyond text extraction. |

---

## 3. Driving Licence

### Mandatory Fields

| Field | Rationale |
|-------|-----------|
| **Name** | Core identity field. Must be entered as per the driving license. |
| **License No** | Unique license number. Used for deduplication, lookup, and rental contract generation. |
| **Nationality** | Essential for rental eligibility, international driving permits, and insurance rate calculation. |
| **Date of Birth** | Used for age verification (e.g. minimum 21+ or 25+ for rental). |
| **Issue Date** | Date of issuance to confirm minimum driving experience. |
| **Expiry Date** | Critical validation field. Expired licenses are immediately rejected. |
| **Licensing Authority** | Authority issuing the permit (e.g. EDC20007, edi151633). Required for legal verification. |
| **Traffic Code No** | Back page traffic code number. Essential for traffic fine routing and transport authority records. |
| **Automatic Gear / Manual Gear** | Permitted vehicle transmission type indicated on back page. Critical for matching driver eligibility to rental vehicle fleet. |
| **Glasses Logo / No Glasses Logo** | Back page restriction indicator. The presence of the eyeglasses logo indicates the driver requires vision correction while driving; absence denotes no restriction. |

### Optional Fields

| Field | Rationale |
|-------|-----------|
| **Place of Issue** | City or Emirate of issue (e.g. Dubai). Informational. |
| **License Class / Permitted Vehicles Category** | Vehicle category code if specified alongside transmission. |
| **Address** | Driver's residential address if printed. |
| **Endorsements** | Additional operational notes. |

---

## Summary of Decisions

1. **Cross-document shared fields:** The three mandatory shared fields (name, date of birth, document number) are used for cross-validation in the premium service. These are the fields that MUST agree across all documents submitted for the same application.

2. **Expiry date is always mandatory:** For every document type, the expiry date is mandatory because accepting an expired document would be a critical failure. This is checked automatically, not left to human review.

3. **Document number is always mandatory:** Each document must have a unique number for deduplication and traceability. Without it, the system cannot prove that the same document was not uploaded twice.

4. **License class is mandatory for driving licences but not for other document types:** This is specific to the mobility/rental service because the licence class determines what the holder is legally permitted to drive. For ID cards and passports, there is no equivalent classification field.

5. **Optional fields can be added later:** The optional fields can be extracted and stored without changing the validation logic. They become relevant if additional services are added that require them.
