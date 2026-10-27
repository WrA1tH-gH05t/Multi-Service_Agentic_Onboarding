"""
Generation Service — Vision-language model (Qwen2.5-VL 3B).

Replaces the old text-only qwen3:0.6b with a multimodal model that:
1. Accepts image inputs (document photos / PDF page images)
2. Extracts structured fields (name, DOB, document_number, etc.) as JSON
3. Also handles text-only chat when no image is provided

Config: ollama.model in config.yaml (default: qwen2.5vl:3b)
Endpoint: http://host:port/api/chat (OpenAI-compatible chat format)
Image format: base64-encoded PNG/JPEG in messages array
"""

import base64
import io
import json
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


class GenerationService:
    """Vision-language generation service using Qwen2.5-VL 3B via Ollama.

    Dual mode:
    - Image mode: sends image(s) + text prompt → returns structured JSON extraction
    - Text mode: sends text-only prompt → returns natural language response
    """

    # National ID specific field schema
    NATIONAL_ID_SCHEMA = {
        "full_name": "Full name as printed on the document",
        "national_id_number": "Unique national ID number",
        "date_of_birth": "Date of birth (DD/MM/YYYY format)",
        "nationality": "Country of citizenship",
        "issue_date": "Date the document was issued",
        "expiry_date": "Date the document expires",
        "gender": "M / F",
        "card_number": "Card number if different from national_id_number",
        "occupation": "Occupation or profession if shown",
        "issue_place": "City or place where the document was issued",
    }

    # Passport specific field schema
    PASSPORT_SCHEMA = {
        "surname": "Last name / family name",
        "given_name": "First name / given name(s)",
        "passport_number": "Passport document number",
        "date_of_birth": "Date of birth (DD/MM/YYYY format)",
        "nationality": "Country of citizenship",
        "sex": "M / F",
        "date_of_issue": "Date the passport was issued",
        "date_of_expiry": "Date the passport expires",
    }

    # Driving License specific field schema (Front & Back)
    DRIVING_LICENSE_SCHEMA = {
        "name": "Full name as printed on driving license",
        "license_no": "License number (e.g. 5154695, 5058836)",
        "nationality": "Nationality / Country (e.g. India)",
        "date_of_birth": "Date of birth (DD/MM/YYYY)",
        "issue_date": "Issue date (DD/MM/YYYY)",
        "expiry_date": "Expiry date (DD/MM/YYYY)",
        "licensing_authority": "Licensing authority code/name (e.g. EDC20007, edi151633)",
        "place_of_issue": "Place / Emirate / State of issue (e.g. Dubai)",
        "traffic_code_no": "Traffic code number on the back page (e.g. 17165557, 16913591)",
        "gear_type": "Vehicle transmission type specified on the back page ('Automatic Gear' or 'Manual Gear')",
        "glasses_requirement": "Spectacles/glasses restriction status from back page logo ('glasses logo' if eyeglasses icon is present, 'no glasses logo' if empty/absent)",
    }

    def _get_schema_for_doc_type(self, doc_type: str) -> Dict[str, str]:
        """Return field schema based on document type."""
        dt = doc_type.lower() if doc_type else ""
        if "passport" in dt:
            return self.PASSPORT_SCHEMA
        elif "driving" in dt or "license" in dt or "licence" in dt or "dl" in dt:
            return self.DRIVING_LICENSE_SCHEMA
        elif "national_id" in dt or "id_card" in dt or "eid" in dt:
            return self.NATIONAL_ID_SCHEMA
        else:
            return self.NATIONAL_ID_SCHEMA  # fallback

    def __init__(self, config: dict):
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 11434)
        self.model = config.get("model", "qwen2.5vl:3b")
        self.base_url = f"http://{self.host}:{self.port}/api/chat"
        self.check_url = f"http://{self.host}:{self.port}/api/tags"
        self.timeout = config.get("timeout_seconds", 300)
        self.max_retries = config.get("max_retries", 3)
        # Use short connect timeout (5s) so missing Ollama fails fast;
        # long read timeout (config timeout) for actual model inference.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=self.timeout, write=self.timeout, pool=5.0)
        )

    # ------------------------------------------------------------------ #
    #  Connection health                                                   #
    # ------------------------------------------------------------------ #

    async def check_connection(self) -> str:
        """Check if Ollama is reachable and has the vision model loaded."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(self.check_url)
                response.raise_for_status()
                models = response.json().get("models", [])
                for m in models:
                    if self.model in m.get("name", ""):
                        return "healthy"
                return "model_not_found"
        except Exception:
            return "unhealthy"

    # ------------------------------------------------------------------ #
    #  Image helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _file_to_base64_png(file_bytes: bytes, page: int = 0) -> str:
        """Convert uploaded file bytes to base64-encoded PNG string.

        Handles both image files (JPEG, PNG, TIFF) and PDFs.
        
        For images: converts to RGB PNG, resizes if needed.
        For PDFs with page=0: extracts first page.
        For PDFs with page>0: extracts that page (0-indexed).
        
        Returns a tuple of (base64_string, is_pdf, total_pages).
        """
        # Try opening as image first
        try:
            img = Image.open(io.BytesIO(file_bytes))
            # Convert to RGB (PIL can't handle CMYK directly)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            # Resize if extremely large (Qwen2.5-VL handles up to 1280x1280 well)
            max_dim = 1280
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = Image.resize(new_size, Image.LANCZOS)
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode("utf-8"), False, 1
        except Exception:
            pass

        # Try as PDF — extract specified page via PyMuPDF
        try:
            import pymupdf as fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(doc)
            if page < 0 or page >= total_pages:
                page = 0
            doc_page = doc[page]
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom = ~300 DPI
            pix = doc_page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            doc.close()
            return base64.b64encode(img_bytes).decode("utf-8"), True, total_pages
        except ImportError:
            logger.warning("PyMuPDF not available; PDF upload will fail. Install: pip install PyMuPDF")
            raise ValueError("PDF upload requires PyMuPDF. Install with: pip install PyMuPDF")
        except Exception as e:
            raise ValueError(f"Failed to extract image from file: {e}")

    @staticmethod
    def _pdf_to_all_pages_png(file_bytes: bytes) -> List[tuple]:
        """Extract ALL pages from a PDF as base64-encoded PNG images.
        
        Returns a list of (base64_string, page_number_1indexed) tuples.
        Empty list if file is not a PDF or PyMuPDF not available.
        """
        try:
            import pymupdf as fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = []
            for i in range(len(doc)):
                page = doc[i]
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom = ~300 DPI
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                pages.append((b64, i + 1))  # 1-indexed page numbers
            doc.close()
            return pages
        except ImportError:
            logger.warning("PyMuPDF not available for multi-page extraction")
            return []
        except Exception as e:
            logger.warning(f"Failed to extract all PDF pages: {e}")
            return []

    @staticmethod
    def _base64_to_data_url(b64: str) -> dict:
        """Format base64 image for qwen2.5vl:3b native images parameter."""
        return b64

    async def _call_ollama_with_images(self, b64_images: list, messages: list) -> Optional[dict]:
        """Call qwen2.5vl:3b using native 'images' parameter in messages.
        
        Args:
            b64_images: List of base64-encoded image strings
            messages: List of message dicts (content will be updated with images)
            
        Returns:
            Parsed JSON dict or None
        """
        # Build payload with images parameter
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 4096,
                "num_ctx": 8192,
            }
        }
        
        # For qwen2.5vl:3b, attach images to the user message
        for msg in reversed(payload["messages"]):
            if msg.get("role") == "user" and "content" in msg:
                msg["images"] = b64_images
                break
        
        retries = 0
        while retries < self.max_retries:
            try:
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if "message" in result and "content" in result["message"]:
                    raw = result["message"]["content"]
                    cleaned = self._strip_thinking(raw).strip()
                    parsed = self._extract_json(cleaned)
                    if parsed:
                        return parsed
                
                logger.warning(f"Model didn't return valid JSON on attempt {retries+1}")
                retries += 1
            except httpx.TimeoutException:
                logger.warning("Request timed out, retrying...")
                retries += 1
            except Exception as e:
                logger.warning(f"Error: {e}, retrying...")
                retries += 1
        
        return None

    # ------------------------------------------------------------------ #
    #  Core generation                                                     #
    # ------------------------------------------------------------------ #

    async def generate_response(
        self,
        prompt: str,
        context: str = "",
        system: str = "",
        query: str = "",
        image_bytes: Optional[bytes] = None,
        extraction_schema: Optional[Dict[str, str]] = None,
        document_type: str = "",
    ) -> str:
        """Generate a response — either from an image (field extraction) or text.

        Args:
            prompt: Main user query.
            context: Optional context/knowledge to base answer on.
            system: Optional system instruction.
            query: Deprecated alias for prompt.
            image_bytes: Document image bytes (PDF or image). If provided,
                         the model performs field extraction instead of chat.
            extraction_schema: Dict of field_name → description for JSON extraction.
                               Defaults to standard ID fields if None.
        """
        actual_prompt = prompt or query

        if image_bytes:
            if extraction_schema and isinstance(extraction_schema, dict):
                schema = extraction_schema
            else:
                schema = self.NATIONAL_ID_SCHEMA
            return await self._extract_fields_from_image(image_bytes, schema, document_type=document_type or "")

        # Text-only chat mode (same as before, but via vision model)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        if context:
            messages.append({
                "role": "user",
                "content": f"Context:\n{context}"
            })

        messages.append({"role": "user", "content": actual_prompt})

        return await self._chat(messages)

    async def _chat(self, messages: List[dict]) -> str:
        """Text-only chat via the vision model's /api/chat endpoint."""
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512,
                    "num_ctx": 8192,
                }
            }
            response = await self._client.post(self.base_url, json=payload)
            response.raise_for_status()
            result = response.json()

            if "message" in result and "content" in result["message"]:
                content = result["message"]["content"]
                return self._strip_thinking(content)
            return "I'm sorry, I couldn't generate a response. Please try again."
        except httpx.TimeoutException:
            return "I'm sorry, the request is taking too long. Please try again with a shorter message."
        except httpx.ConnectError:
            return "I'm not able to connect to the AI model right now. Please check if the model service is running."
        except Exception as e:
            return f"I'm sorry, I encountered an error: {str(e)[:200]}"

    async def _extract_fields_from_image(
        self, image_bytes: bytes, schema: Dict[str, str], document_type: str = ""
    ) -> str:
        """Send image to vision model for structured field extraction.

        For multi-page scanned documents, extracts all pages and merges results.
        
        Returns a JSON string of extracted fields.
        """
        b64_image, is_pdf, total_pages = self._file_to_base64_png(image_bytes)

        # For multi-page scanned PDFs, extract all pages and merge
        if is_pdf and total_pages > 1:
            all_pages = self._pdf_to_all_pages_png(image_bytes)
            if all_pages:
                return await self._extract_multi_page_fields(all_pages, schema, document_type)

        # Build field extraction prompt
        field_list = "\n".join(
            f'  "{field}": "{desc}"' for field, desc in schema.items()
        )
        
        doc_hint = ""
        if document_type:
            doc_hint = f"\n\nThis is a {document_type} document. Extract ALL fields listed below."
        
        system_msg = (
            "You are a document data extraction engine. Extract key-value information from the document image and return ONLY valid JSON.\n\n"
            "JSON SCHEMA TO USE:\n"
            f"{{\n{field_list}\n}}\n\n"
            f"{doc_hint}"
            "\nCRITICAL RULES:\n"
            "1. Return ONLY a JSON object - no markdown, no code fences, no explanation, no preamble\n"
            "2. Extract ALL fields in the schema - every single one, even if some are empty\n"
            "3. If a field cannot be read, use empty string \"\" (not null)\n"
            "4. For dates, preserve the exact format from the document (DD/MM/YYYY, DD-MM-YYYY, etc.)\n"
            "5. Copy values verbatim - do not translate or reformat\n"
            "6. Look for labels like: Name, ID No, DOB, Nationality, Gender, Expiry, Issue Date\n"
            "7. For passports: extract given_name and surname separately\n"
            "8. For national IDs: extract full_name, and if visible also card_number, occupation, issue_place\n"
            "9. The model will receive this as an image - look carefully at all text regions\n"
            "10. Output must be parseable JSON - use double quotes for all string values\n"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": "Extract all key-value information from this document image. Return JSON matching the schema above.",
                "images": [b64_image],
            },
        ]

        retries = 0
        while retries < self.max_retries:
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.0,  # Zero temp for deterministic extraction
                        "num_predict": 4096,
                        "num_ctx": 8192,
                    }
                }
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "message" in result and "content" in result["message"]:
                    raw = result["message"]["content"]
                    cleaned = self._strip_thinking(raw).strip()
                    # Try to extract JSON from response (handle markdown fences)
                    parsed = self._extract_json(cleaned)
                    if parsed:
                        # Validate all schema fields are present
                        missing = [k for k in schema if k not in parsed]
                        if missing:
                            logger.warning(f"Missing fields in response: {missing}. Retrying...")
                            retries += 1
                            continue
                        return json.dumps(parsed)

                logger.warning(f"Vision model didn't return valid JSON on attempt {retries+1}")
                retries += 1
            except httpx.TimeoutException:
                logger.warning("Vision extraction timed out, retrying...")
                retries += 1
            except httpx.ConnectError:
                raise
            except Exception as e:
                logger.warning(f"Vision extraction error: {e}, retrying...")
                retries += 1

        # All retries failed — return partial JSON with error
        return json.dumps({"_error": "Failed to extract fields from document after multiple attempts"})

    async def _extract_multi_page_fields(
        self, pages: List[tuple], schema: Dict[str, str], document_type: str = ""
    ) -> str:
        """Extract fields from a multi-page scanned document by analyzing all pages together.
        
        For each page, extract all visible fields. Then merge results, taking non-empty values
        from any page. Returns merged JSON with all schema fields.
        
        Args:
            pages: List of (base64_image, page_number_1indexed) tuples
            schema: Field schema dict
            document_type: Type hint for prompt customization
            
        Returns:
            JSON string with merged extracted fields
        """
        # Build field extraction prompt for each page
        field_list = "\n".join(
            f'  "{field}": "{desc}"' for field, desc in schema.items()
        )
        
        doc_hint = f"This is a {document_type} document" if document_type else "This is an ID document"
        
        results = {}
        
        for b64_page, page_num in pages:
            logger.info(f"Extracting fields from page {page_num}")
            
            system_msg = (
                "You are a document data extraction engine. Analyze THIS PAGE ONLY and extract ALL fields visible on this page. Return ONLY valid JSON.\n\n"
                f"DOCUMENT TYPE: {doc_hint}\n\n"
                "JSON SCHEMA TO USE:\n"
                f"{{\n{field_list}\n}}\n\n"
                "CRITICAL RULES:\n"
                "1. Return ONLY a JSON object - no markdown, no code fences, no explanation\n"
                "2. Extract ALL fields visible on THIS PAGE\n"
                "3. For fields NOT visible on this page, use empty string \"\"\n"
                "4. Include page_number in output: {\"page_number\": N, ...}\n"
                "5. Look for ALL labels carefully - small text, fine print, secondary fields\n"
                "6. For national IDs: check for card_number, occupation, issue_place (often on back side)\n"
                "7. For passports: check MRZ (Machine Readable Zone) at bottom for additional data\n"
                "8. For driving licenses: On front, extract name, license_no, nationality, issue_date, expiry_date, licensing_authority, date_of_birth. On back, extract traffic_code_no, gear_type ('Automatic Gear' or 'Manual Gear' under Permitted Vehicles), and glasses_requirement ('glasses logo' if an eyeglasses/spectacles icon is present in the restrictions box, or 'no glasses logo' if the box has no eyeglasses icon).\n"
                "9. Copy values verbatim - preserve exact format\n"
                "10. Output must be parseable JSON - use double quotes\n"
            )

            messages = [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": "Extract all fields from this page. Return JSON with schema above.",
                    "images": [b64_page],
                },
            ]

            retries = 0
            while retries < self.max_retries:
                try:
                    payload = {
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "num_predict": 4096,
                            "num_ctx": 8192,
                        }
                    }
                    response = await self._client.post(self.base_url, json=payload)
                    response.raise_for_status()
                    result = response.json()

                    if "message" in result and "content" in result["message"]:
                        raw = result["message"]["content"]
                        cleaned = self._strip_thinking(raw).strip()
                        parsed = self._extract_json(cleaned)
                        if parsed:
                            results[page_num] = parsed
                            logger.info(f"Page {page_num} extraction successful: {len([k for k in parsed if k not in ['page_number', '_page_number']])} fields extracted")
                            break
                except Exception as e:
                    logger.warning(f"Page {page_num} extraction error: {e}")
                    retries += 1

            if retries >= self.max_retries:
                logger.warning(f"Failed to extract from page {page_num} after {self.max_retries} retries")

        # Merge results from all pages
        if not results:
            return json.dumps({"_error": "Failed to extract fields from any page"})

        # Merge strategy: take non-empty values from any page
        merged = {}
        for page_num, page_data in results.items():
            for key, value in page_data.items():
                if key in ("page_number", "_page_number", "side", "_side"):
                    continue
                if key not in merged:
                    merged[key] = value
                elif merged[key] == "" and value != "":
                    # If current value is empty but this page has it, use it
                    merged[key] = value

        # Ensure all schema fields are present
        final = {}
        for field in schema:
            final[field] = merged.get(field, "")
        
        # Add metadata
        final["_total_pages"] = len(pages)
        final["_note"] = "Merged from {} page(s)".format(len(results))

        return json.dumps(final)

    async def extract_id_fields_from_image(
        self, image_bytes: bytes, is_pdf: bool = False, page_hint: str = "",
        document_type: str = ""
    ) -> str:
        """Extract fields from a government-issued ID document image or PDF.

        Optimized for:
        - Scanned PDFs (multi-page: front/back sides, multiple pages)
        - Government IDs (national IDs, passports, driver's licenses, visas, residence permits)
        - Multi-language documents (labels in local language + English)
        - MRZ (Machine Readable Zone) at bottom of passports/national IDs

        Args:
            image_bytes: Raw file bytes (image or PDF)
            is_pdf: Whether the file is a PDF (auto-detected if False)
            page_hint: Optional hint about which page/side this is ("front", "back", "page 1", etc.)
            document_type: "passport" or "national_id" to select the right schema

        Returns:
            JSON string with extracted ID fields
        """
        # Auto-detect PDF and extract pages
        b64_image, detected_pdf, total_pages = self._file_to_base64_png(image_bytes)
        is_pdf = detected_pdf or is_pdf

        # Determine schema based on document type hint or filename
        dt = document_type.lower() if document_type else ""
        schema = self._get_schema_for_doc_type(dt)

        # For PDFs, extract all pages and send them together for cross-page context
        if is_pdf and total_pages > 1:
            all_pages = self._pdf_to_all_pages_png(image_bytes)
            if all_pages:
                return await self._extract_multi_page_fields(all_pages, schema, dt)
            # Fall back to single-page extraction

        # Build the ID-specific system prompt with schema fields
        field_list = "\n".join(
            f"  - {field}: {desc}" for field, desc in schema.items()
        )
        
        system_msg = (
            "You are a document data extraction engine. Extract key-value information from the document image and return ONLY valid JSON.\n\n"
            "JSON SCHEMA TO USE:\n"
            f"{{\n{field_list}\n}}\n\n"
            f"This is a {document_type or 'auto-detect'} document. Extract ALL fields listed below.\n\n"
            "CRITICAL RULES:\n"
            "1. Return ONLY a JSON object - no markdown, no code fences, no explanation, no preamble\n"
            "2. Extract ALL fields in the schema - every single one, even if some are empty\n"
            "3. If a field cannot be read, use empty string \"\" (not null)\n"
            "4. For dates, preserve the exact format from the document (DD/MM/YYYY, DD-MM-YYYY, etc.)\n"
            "5. Copy values verbatim - do not translate or reformat\n"
            "6. For passports: extract given_name and surname separately\n"
            "7. For national IDs: extract full_name, and if visible also card_number, occupation, issue_place\n"
            "8. For driving licenses: extract name, license_no, nationality, issue_date, expiry_date, licensing_authority, date_of_birth, traffic_code_no, gear_type ('Automatic Gear' or 'Manual Gear'), and glasses_requirement ('glasses logo' or 'no glasses logo')\n"
            "9. Look for labels like: Name, License No, Traffic Code No, Permitted Vehicles, Gear, Restrictions, DOB, Nationality, Gender, Expiry, Issue Date\n"
            "10. The model will receive this as an image - look carefully at all text regions\n"
            "11. Output must be parseable JSON - use double quotes for all string values\n"
            + (f"\n\nPage hint: {page_hint}" if page_hint else "")
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": "Extract all fields from this government-issued ID document. Return JSON.",
                "images": [b64_image],
            },
        ]

        retries = 0
        while retries < self.max_retries:
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temp for accurate extraction
                        "num_predict": 4096,
                        "num_ctx": 8192,
                    }
                }
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "message" in result and "content" in result["message"]:
                    raw = result["message"]["content"]
                    cleaned = self._strip_thinking(raw).strip()
                    parsed = self._extract_json(cleaned)
                    if parsed:
                        return json.dumps(parsed)

                logger.warning(f"ID extraction didn't return valid JSON on attempt {retries+1}")
                retries += 1
            except httpx.TimeoutException:
                logger.warning("ID extraction timed out, retrying...")
                retries += 1
            except httpx.ConnectError:
                raise
            except Exception as e:
                logger.warning(f"ID extraction error: {e}, retrying...")
                retries += 1

        return json.dumps({"_error": "Failed to extract fields from ID document after multiple attempts"})

    async def _extract_id_from_pdf_pages(self, pages: List[tuple], schema: Dict[str, str] = None) -> str:
        """Extract ID fields from a multi-page PDF by analyzing all pages together.

        Args:
            pages: List of (base64_image, page_number) tuples
            schema: Field schema dict (defaults to NATIONAL_ID_SCHEMA)

        Returns:
            JSON string with merged extracted fields from all pages
        """
        if schema is None:
            schema = self.NATIONAL_ID_SCHEMA
        
        # First pass: extract fields from each page independently
        page_results = []
        field_list = "\n".join(
            f"  - {field}: {desc}" for field, desc in schema.items()
        )
        for b64_page, page_num in pages:
            system_msg = (
                "You are an expert document data extraction assistant.\n"
                f"This is page {page_num} of a multi-page document.\n\n"
                "Extract ALL fields visible on THIS page. Note which side (front/back) this appears to be.\n\n"
                f"FIELDS TO EXTRACT:\n{field_list}\n\n"
                "Return ONLY valid JSON — no markdown, no explanation.\n"
                "Use this structure:\n"
                "{{\n"
                '  "page_number": 1,\n'
                '  "side": "front|back|unknown",\n'
                '  "fields": {{}}\n'
                "}}\n\n"
                "RULES:\n"
                "- Extract EXACTLY what you see — do not infer missing data\n"
                "- Use empty string or null for fields not visible on this page\n"
                "- For dates, preserve the original format"
            )

            messages = [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": f"Extract fields from page {page_num} of this ID document.",
                    "images": [b64_page],
                },
            ]

            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 4096,
                        "num_ctx": 8192,
                    }
                }
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "message" in result and "content" in result["message"]:
                    raw = result["message"]["content"]
                    cleaned = self._strip_thinking(raw).strip()
                    parsed = self._extract_json(cleaned)
                    if parsed:
                        page_results.append(parsed)
                        continue

                logger.warning(f"Page {page_num} extraction returned non-JSON, skipping")
            except Exception as e:
                logger.warning(f"Page {page_num} extraction error: {e}")

        # Merge results from all pages
        if not page_results:
            return json.dumps({"_error": "Failed to extract fields from any page of the PDF"})

        # Merge strategy: take non-empty values from the first page, fill in missing from others
        merged_fields = {}
        for page_result in page_results:
            fields = page_result.get("fields", page_result)
            for key, value in fields.items():
                if key == "fields":
                    # Nested structure — merge inner fields
                    if isinstance(value, dict):
                        for k, v in value.items():
                            if k not in merged_fields or (merged_fields.get(k) == "" and v != ""):
                                merged_fields[k] = v
                elif key not in merged_fields or (merged_fields.get(key) == "" and value != ""):
                    merged_fields[key] = value

        # Identify front/back sides
        front_side = None
        back_side = None
        for pr in page_results:
            side = pr.get("side", pr.get("fields", {}).get("side"))
            pn = pr.get("page_number", "")
            if side == "front":
                front_side = pn
            elif side == "back":
                back_side = pn

        # Build final result
        front_fields = {}
        back_fields = {}
        for field, value in merged_fields.items():
            if field == "page_number":
                continue
            if field == "side":
                continue
            if field == "fields":
                continue
            # Heuristic: if we know front/back from page results, separate them
            # Otherwise put everything in a flat structure
            front_fields[field] = value

        # Clean up: only keep fields that are in the schema
        clean_fields = {}
        for field, value in front_fields.items():
            if field in schema and value:
                clean_fields[field] = value
        
        # Add metadata
        clean_fields["_total_pages"] = len(pages)
        clean_fields["_front_page"] = front_side
        clean_fields["_back_page"] = back_side
        clean_fields["_note"] = "All fields merged from available pages."

        return json.dumps(clean_fields)

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract a JSON object from text, handling markdown code fences."""
        # Strip code fences if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        # Try direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try finding JSON object in text
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove <think>...</think> tags from response."""
        if not text:
            return ""
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'<\\/think>', '', text)
        return text.strip()

    
    async def validate_document(
        self,
        image_bytes: bytes,
        required_types: List[str],
    ) -> dict:
        """Use the VL model to validate whether the uploaded document is the correct type.

        Args:
            image_bytes: Raw file bytes (image or PDF page)
            required_types: List of acceptable document types, e.g. ["national_id", "passport", "driving_license"]

        Returns:
            dict with keys:
              - is_valid: bool
              - detected_type: str (e.g. "passport", "national_id", "invoice", "contract", "other")
              - is_scanned: bool (True if it looks like a clean scan, False if screenshot/converted)
              - confidence: float (0-1)
              - reason: str (explanation)
        """
        b64_image, is_pdf, total_pages = self._file_to_base64_png(image_bytes)

        allowed = ", ".join(required_types) if required_types else "government-issued ID (passport, national ID, or driving license)"
        system_msg = (
            "You are a document validation assistant. You MUST analyze this image and return ONLY a valid JSON object. Do NOT include any other text.\n\n"
            "Analyze the document and return this exact JSON structure:\n"
            "{\n"
            '  "document_type": "passport|national_id|driving_license|visa|residence_permit|invoice|receipt|contract|utility_bill|bank_statement|pay_slip|employment_letter|medical_report|property_deed|insurance_certificate|qualifications|reference_letter|other",\n'
            '  "is_scanned": true|false,\n'
            '  "confidence": 0.0\n'
            '  "reason": "Brief explanation of what this document is and why you classified it this way"\n'
            "}\n\n"
            "RULES:\n"
            "- DOCUMENT TYPE: Identify what this document actually IS. Look for headings, logos, form fields, labels like 'PASSPORT', 'NATIONAL ID', 'DRIVING LICENSE', 'INVOICE', 'CONTRACT', etc.\n"
            "- IS_SCANNED: Return true if this looks like a photograph or scan of a physical document (clean edges, paper texture, realistic lighting). Return false if it looks like a digital file converted to an image (screenshots, Word/PDF exports, digital signatures, sharp vector graphics, uniform backgrounds).\n"
            "- Be strict: if the user uploaded an invoice, receipt, contract, bank statement, or any non-ID document, detect it correctly.\n"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": f"Validate this document. It should be one of: {allowed}. Return JSON.",
                "images": [b64_image],
            },
        ]

        retries = 0
        while retries < self.max_retries:
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 512,
                        "num_ctx": 8192,
                    }
                }
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if "message" in result and "content" in result["message"]:
                    raw = result["message"]["content"]
                    cleaned = self._strip_thinking(raw).strip()
                    parsed = self._extract_json(cleaned)
                    if parsed:
                        return parsed

                logger.warning(f"Document validation didn't return valid JSON on attempt {retries+1}")
                retries += 1
            except httpx.TimeoutException:
                logger.warning("Document validation timed out, retrying...")
                retries += 1
            except httpx.ConnectError:
                raise
            except Exception as e:
                logger.warning(f"Document validation error: {e}, retrying...")
                retries += 1

        return {
            "is_valid": False,
            "detected_type": "unknown",
            "is_scanned": False,
            "confidence": 0.0,
            "reason": "Failed to validate document after multiple attempts"
        }


    async def generate_streaming(self, prompt: str, context: str = "", system: str = "") -> AsyncGenerator[str, None]:
        """Generate a streaming response (text-only mode)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        if context:
            messages.append({
                "role": "user",
                "content": f"Context:\n{context}\n\nBased on this context, answer the following question."
            })

        messages.append({"role": "user", "content": prompt})

        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512
                }
            }
            async with self._client.stream("POST", self.base_url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if 'message' in data and 'content' in data['message']:
                                content = data['message']['content']
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.TimeoutException:
            yield "The request is taking too long. Please try again with a shorter message."
        except httpx.ConnectError:
            yield "I'm not able to connect to the AI model right now. Please check if the model service is running."
        except Exception as e:
            yield f"I'm sorry, I encountered an error: {str(e)[:200]}"

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
