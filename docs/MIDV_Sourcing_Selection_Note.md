# MIDV Document Sourcing & Selection Note

## Dataset Source
- **MIDV-500**: https://github.com/fcakyon/midv500
- **FTP Mirror**: ftp://smartengines.com/midv-500/
- **License**: MIDV-500 is released under a custom research license. The dataset is designed for computer vision research and contains fictional identity documents only. All names, dates, and document numbers are fictional.

## Document Types Selected

### 1. National ID Cards
- **Folder**: `national_id`
- **Why chosen**: Required for Basic Registration service. Represents the most common identity document type. The dataset provides multiple countries (US, UK, EU, etc.) with varying layouts, enabling extraction model generalization.
- **Capture conditions represented**: table (top-down), handheld (angled), cluttered background, partial occlusion.

### 2. Passports
- **Folder**: `passport`
- **Why chosen**: Required for Premium/Cross Border service alongside National ID. Passports have a different layout structure (MRZ zone, photo page, multi-page format) which tests the system's flexibility in handling diverse document types.
- **Capture conditions represented**: table, handheld, glare, shadow.

### 3. Driving Licenses
- **Folder**: `driving_license`
- **Why chosen**: Required for Mobility/Rental service. Driving licenses vary significantly in layout by country and type (plastic card, paper), providing a distinct document schema from ID cards and passports.
- **Capture conditions represented**: table, handheld, folded, worn.

## Matched Pair Construction
For the Premium service, ~50 identity pairs were created by:
1. Extracting printed fields (name, DOB, document number, expiry, issuing authority) from one National ID sample.
2. Copying these values into a corresponding Passport sample (or vice versa).
3. Labeling each pair as `true_match` or `labeled_mismatch`.
4. Deliberately breaking 10+ pairs with field disagreements (e.g., different name on passport vs ID).

## Recommendation for Further Research
For even more realistic testing, consider:
- MIDV-2020 (larger, more recent dataset)
- Adding passports from different regions (EU, Asia, Africa)
- Including expired documents for validation testing
