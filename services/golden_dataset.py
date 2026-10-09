"""
GoldenDatasetService — loads the MIDV-500 golden dataset and serves
field schemas, validation rules, and sample extractions for the chatbot
to reference when answering document-related queries.
"""

import json
import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GoldenEntry:
    """A single golden dataset entry."""
    id: str
    document_type: str  # national_id, passport, driving_license
    capture_condition: str  # table, handheld, cluttered, partial
    source_note: str = ""
    golden_fields: Dict[str, str] = field(default_factory=dict)
    validation_rules: Dict[str, str] = field(default_factory=dict)
    extraction: Optional[Dict[str, str]] = None  # simulated extraction
    score: Optional[float] = None  # accuracy score against golden


class GoldenDatasetService:
    """Serves the MIDV-500 golden dataset for validation & chatbot grounding."""

    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset: Dict[str, Any] = {}
        self.entries: List[GoldenEntry] = []
        self._index_by_type: Dict[str, List[str]] = {}  # doc_type -> entry_ids
        self._index_by_country: Dict[str, List[str]] = {}  # country code -> entry_ids
        self._index_by_condition: Dict[str, List[str]] = {}  # condition -> entry_ids
        self._search_index: Dict[str, List[str]] = {}  # keyword -> entry_ids

        if dataset_path:
            self.load(dataset_path)

    def load(self, path: str) -> bool:
        """Load golden dataset from JSON file. Auto-detects format."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.dataset = json.load(f)

            # Detect format: legacy "document_samples" vs current "entries"
            if "document_samples" in self.dataset:
                self._parse_legacy_format()
            elif "entries" in self.dataset:
                self._parse_entries_format()
            else:
                logger.error(f"Unknown golden dataset format in {path}")
                return False

            # Build indices
            self._build_indices()
            logger.info(f"GoldenDataset loaded: {len(self.entries)} entries from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load golden dataset from {path}: {e}")
            return False

    def _parse_entries_format(self):
        """Parse the modern 'entries' format from the golden_dataset.json."""
        metadata = self.dataset.get("metadata", {})
        
        for raw in self.dataset.get("entries", []):
            entry = GoldenEntry(
                id=raw["id"],
                document_type=raw.get("document_type", "unknown"),
                capture_condition=raw.get("capture_condition", "unknown"),
                source_note=raw.get("source_note", ""),
                golden_fields=raw.get("golden_fields", {}),
            )
            
            # Try to extract country code from field values
            country = self._extract_country_code(entry.golden_fields)
            if country:
                entry._country_code = country  # type: ignore
            
            # Parse validation rules if present
            if "validation_rules" in raw:
                entry.validation_rules = raw["validation_rules"]
            
            # Parse optional extraction data
            if "extraction" in raw:
                entry.extraction = raw["extraction"]
                entry.score = raw.get("score")
            
            self.entries.append(entry)

    def _parse_legacy_format(self):
        """Parse legacy 'document_samples' format (backward compatible)."""
        from dataclasses import dataclass as _dc
        
        for raw in self.dataset.get("document_samples", []):
            entry = GoldenEntry(
                id=raw.get("doc_id", raw.get("id", "")),
                document_type=raw.get("document_type", "unknown"),
                capture_condition=raw.get("category", "unknown"),
                source_note=raw.get("country", ""),
                golden_fields={},
            )
            # Map legacy fields
            for fname, fdef in raw.get("fields", {}).items():
                entry.golden_fields[fname] = fdef.get("example", "")
            if "validation_rules" in raw:
                entry.validation_rules = raw["validation_rules"]
            self.entries.append(entry)

    def _extract_country_code(self, fields: Dict[str, str]) -> Optional[str]:
        """Try to extract country code from field values."""
        # Common country fields in passports/national IDs
        for key in ["issuing_country", "country", "issuing_authority"]:
            if key in fields:
                return fields[key].strip()[:2].upper()
        return None

    def _build_indices(self):
        """Build lookup indices for fast querying."""
        for entry in self.entries:
            # Document type index
            self._index_by_type.setdefault(entry.document_type, []).append(entry.id)
            
            # Country index
            country = getattr(entry, '_country_code', None)
            if country:
                self._index_by_country.setdefault(country, []).append(entry.id)
            
            # Capture condition index
            self._index_by_condition.setdefault(entry.capture_condition, []).append(entry.id)
            
            # Search index
            searchable = f"{entry.document_type} {entry.capture_condition} {entry.source_note}".lower()
            for word in searchable.split():
                if len(word) > 2:
                    self._search_index.setdefault(word, []).append(entry.id)

    def get_entry_by_id(self, entry_id: str) -> Optional[GoldenEntry]:
        """Get a specific entry by its ID."""
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def get_entries_by_type(self, doc_type: str) -> List[GoldenEntry]:
        """Get all entries for a document type."""
        entry_ids = self._index_by_type.get(doc_type, [])
        return [self.get_entry_by_id(eid) for eid in entry_ids if self.get_entry_by_id(eid)]

    def get_entries_by_condition(self, condition: str) -> List[GoldenEntry]:
        """Get all entries by capture condition."""
        entry_ids = self._index_by_condition.get(condition, [])
        return [self.get_entry_by_id(eid) for eid in entry_ids if self.get_entry_by_id(eid)]

    def get_entries_by_country(self, country: str) -> List[GoldenEntry]:
        """Get all entries by country."""
        entry_ids = self._index_by_country.get(country.upper(), [])
        return [self.get_entry_by_id(eid) for eid in entry_ids if self.get_entry_by_id(eid)]

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search golden dataset by keywords."""
        query_lower = query.lower()
        query_words = query_lower.split()
        
        score_map: Dict[str, int] = {}
        
        # Word-level matching
        for word in query_words:
            for keyword, entry_ids in self._search_index.items():
                if word in keyword or keyword in word:
                    for eid in entry_ids:
                        score_map[eid] = score_map.get(eid, 0) + 1
        
        # Full text matching
        for entry in self.entries:
            text = f"{entry.document_type} {entry.capture_condition} {entry.source_note}".lower()
            if query_lower in text:
                score_map[entry.id] = score_map.get(entry.id, 0) + 2
        
        # Sort by relevance
        sorted_entries = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for entry_id, score in sorted_entries[:limit]:
            entry = self.get_entry_by_id(entry_id)
            if entry:
                results.append({
                    "id": entry.id,
                    "document_type": entry.document_type,
                    "capture_condition": entry.capture_condition,
                    "source_note": entry.source_note,
                    "golden_fields": entry.golden_fields,
                    "relevance_score": score,
                })
        
        return results

    def validate_extraction(self, entry_id: str, extracted_fields: Dict[str, str]) -> Dict[str, Any]:
        """Compare an extraction result against the golden dataset."""
        entry = self.get_entry_by_id(entry_id)
        if not entry:
            return {
                "valid": False,
                "error": f"Entry not found: {entry_id}",
                "golden_entry_id": entry_id
            }
        
        golden = entry.golden_fields
        checks = []
        matched = 0
        total = len(golden)
        
        for field_name, golden_value in golden.items():
            extracted_value = extracted_fields.get(field_name, "")
            
            # Case-insensitive comparison
            match = extracted_value.strip().lower() == golden_value.strip().lower()
            if match:
                matched += 1
            
            checks.append({
                "field": field_name,
                "golden_value": golden_value,
                "extracted_value": extracted_value,
                "match": match
            })
        
        completion_rate = matched / total if total > 0 else 0
        is_valid = completion_rate >= 0.8  # Allow some variance
        
        return {
            "valid": is_valid,
            "completion_rate": round(completion_rate, 2),
            "total_fields": total,
            "matched_fields": matched,
            "entry_id": entry_id,
            "document_type": entry.document_type,
            "checks": checks
        }

    def compare_entries(self, entry1_id: str, entry2_id: str) -> Optional[Dict[str, Any]]:
        """Compare two golden entries for schema differences."""
        e1 = self.get_entry_by_id(entry1_id)
        e2 = self.get_entry_by_id(entry2_id)
        
        if not e1 or not e2:
            return None
        
        fields1 = set(e1.golden_fields.keys())
        fields2 = set(e2.golden_fields.keys())
        
        return {
            "entry1": {
                "id": e1.id,
                "document_type": e1.document_type,
                "fields": list(fields1)
            },
            "entry2": {
                "id": e2.id,
                "document_type": e2.document_type,
                "fields": list(fields2)
            },
            "common_fields": list(fields1 & fields2),
            "only_in_entry1": list(fields1 - fields2),
            "only_in_entry2": list(fields2 - fields1)
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the golden dataset."""
        doc_type_counts = {}
        condition_counts = {}
        for entry in self.entries:
            doc_type_counts[entry.document_type] = doc_type_counts.get(entry.document_type, 0) + 1
            condition_counts[entry.capture_condition] = condition_counts.get(entry.capture_condition, 0) + 1
        
        return {
            "total_entries": len(self.entries),
            "document_types": doc_type_counts,
            "capture_conditions": condition_counts,
            "countries": list(self._index_by_country.keys()),
            "metadata": self.dataset.get("metadata", {}),
            "loaded_at": datetime.now().isoformat(),
            "has_extraction_data": any(e.extraction is not None for e in self.entries)
        }

    def get_all_field_names(self) -> List[str]:
        """Get all unique field names across all entries."""
        all_fields = set()
        for entry in self.entries:
            all_fields.update(entry.golden_fields.keys())
        return sorted(all_fields)

    def get_field_examples(self, field_name: str) -> List[Dict[str, str]]:
        """Get example values for a specific field across all entries."""
        examples = []
        for entry in self.entries:
            if field_name in entry.golden_fields:
                examples.append({
                    "entry_id": entry.id,
                    "document_type": entry.document_type,
                    "value": entry.golden_fields[field_name]
                })
        return examples
