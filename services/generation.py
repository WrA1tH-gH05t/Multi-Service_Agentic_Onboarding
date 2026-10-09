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

    # Comprehensive ID field schema — covers passports, national IDs, driver's licenses, visas, residence permits
    ID_FIELD_SCHEMA = {
        "document_type": "Type: national_id, passport, drivers_license, visa, residence_permit, other",
        "issuing_country": "Full country name (not code)",
        "surname": "Last name / family name",
        "given_name": "First name / given name",
        "full_name": "Complete name as printed on document",
        "nationality": "Country of citizenship",
        "date_of_birth": "Date of birth (preserve original format from document)",
        "place_of_birth": "City, region, or country of birth",
        "sex": "M/F or other gender marker",
        "date_of_issue": "Date document was issued",
        "date_of_expiry": "Date document expires",
        "authority": "Issuing authority or government department",
        "personal_id_number": "Unique personal identification number",
        "document_number": "Main document number",
        "mrz": "Machine Readable Zone (2 lines at bottom of passport/ID)",
        "address": "Residential address (if shown on ID)",
        "signature": "yes/no — whether a signature is visible",
        "photo": "yes/no — whether a photo is visible",
        "page_number": "Page number or side (front/back) of the document",
    }

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
            import fitz  # PyMuPDF
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
            import fitz  # PyMuPDF
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
        """Format base64 image for Ollama chat API."""
        return {
            "type": "image_url",
            "image_url": f"data:image/png;base64,{b64}"
        }

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
            return await self._extract_fields_from_image(
                image_bytes, extraction_schema or self.ID_FIELD_SCHEMA
            )

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
                    "num_ctx": 4096,
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
        self, image_bytes: bytes, schema: Dict[str, str]
    ) -> str:
        """Send image to vision model for structured field extraction.

        Returns a JSON string of extracted fields.
        """
        b64_image, is_pdf, total_pages = self._file_to_base64_png(image_bytes)

        # Build field extraction prompt
        field_list = "\n".join(
            f"  - {field}: {desc}" for field, desc in schema.items()
        )
        system_msg = (
            "You are a document data extraction assistant. "
            "Extract data from the uploaded document image and return ONLY a valid JSON object. "
            f"Use these fields:\n{field_list}\n"
            "Rules:\n"
            "- Return ONLY the JSON object, no other text\n"
            "- If a field cannot be read, use null\n"
            "- For dates, preserve the original format from the document\n"
            "- Do NOT add any markdown code fences or explanation\n"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all fields from this document. Return JSON."},
                    self._base64_to_data_url(b64_image),
                ],
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
                        "num_predict": 1024,
                        "num_ctx": 4096,
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

    async def extract_id_fields_from_image(
        self, image_bytes: bytes, is_pdf: bool = False, page_hint: str = ""
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

        Returns:
            JSON string with extracted ID fields
        """
        # Auto-detect PDF and extract pages
        b64_image, detected_pdf, total_pages = self._file_to_base64_png(image_bytes)
        is_pdf = detected_pdf or is_pdf

        # For PDFs, extract all pages and send them together for cross-page context
        if is_pdf and total_pages > 1:
            all_pages = self._pdf_to_all_pages_png(image_bytes)
            if all_pages:
                return await self._extract_id_from_pdf_pages(all_pages)
            # Fall back to single-page extraction

        # Build the ID-specific system prompt
        system_msg = (
            "You are an expert document analyst specializing in government-issued identity documents.\n"
            "Your task is to extract ALL relevant fields from the provided document image.\n\n"
            "=== CONTEXT ===\n"
            "The document may be:\n"
            "- A scanned page from a PDF (multi-page documents will be sent page by page)\n"
            "- A government-issued ID (national ID card, passport, driver's license, visa, residence permit)\n"
            "- Scanned at various quality levels (clear, blurred, skewed, rotated, noisy)\n"
            "- In any language (most common: English, local language, or both)\n\n"
            "=== CRITICAL INSTRUCTIONS ===\n"
            "1. FIRST identify the document type and issuing country\n"
            "2. Scan the ENTIRE document — front AND back, top to bottom\n"
            "3. Pay special attention to:\n"
            "   - Labels in local language (e.g., 'mbiemri/surname', 'data e lindjes') — extract the VALUE next to the label\n"
            "   - Multi-line fields (e.g., name split across 'surname' and 'given name' lines)\n"
            "   - MRZ (Machine Readable Zone) at the bottom — usually 2 lines of alphanumeric text\n"
            "   - Photo areas and any biometric data\n"
            "4. Extract EXACTLY what you see — do not infer or guess missing information\n"
            "5. If a field is not present or not legible, return an empty string\n"
            "6. For dates, preserve the original format from the document (e.g., DD-MM-YYYY)\n\n"
            "=== FIELDS TO EXTRACT ===\n"
            "Scan for and extract these fields (use the EXACT label shown on the document as fallback):\n"
            "- document_type: e.g., 'national_id', 'passport', 'drivers_license', 'visa', 'residence_permit'\n"
            "- issuing_country: Country that issued the document (full name)\n"
            "- surname / family_name: Last name\n"
            "- given_name / forename: First name\n"
            "- full_name: Complete name as it appears on the document\n"
            "- nationality: Country of citizenship\n"
            "- date_of_birth / dob: Date of birth (preserve original format)\n"
            "- place_of_birth: City, region, or country of birth\n"
            "- sex / gender: M, F, or other\n"
            "- date_of_issue / issued: When the document was issued\n"
            "- date_of_expiry / expires: When the document expires\n"
            "- authority: Issuing authority or government department\n"
            "- personal_id_number / id_number / nr: Unique personal ID number\n"
            "- document_number / card_no: The document's main number\n"
            "- mrz: Machine Readable Zone text (the 2 lines at the bottom, if present)\n"
            "- address: Residential address (if shown on the ID)\n"
            "- signature: Notes whether a signature is present (yes/no)\n"
            "- photo: Notes whether a photo is present (yes/no)\n"
            "- page_number: Which page or side this is (front/back/1/2/etc.)\n\n"
            "=== COMMON ID LABELS ACROSS LANGUAGES ===\n"
            "Look for these patterns (non-exhaustive):\n"
            "English: surname, given name, nationality, date of birth, sex, expiry\n"
            "Albanian: mbiemri, emri, shtetësia, data e lindjes, gjinia, data e skadimit\n"
            "Turkish: soyadı, adı, uyruk, doğum tarihi, cinsiyet, geçerlilik\n"
            "Arabic: اسم العائلة, الاسم, الجنسية, تاريخ الميلاد, الجنس, انتهاء الصلاحية\n"
            "French: nom, prénom, nationalité, date de naissance, sexe, date d'expiration\n"
            "German: Nachname, Vorname, Staatsangehörigkeit, Geburtsdatum, Geschlecht, Ablaufdatum\n\n"
            "=== PDF SCANNING NOTES ===\n"
            "If the image appears to be a page from a multi-page PDF:\n"
            "- Note if it seems to be page 1, 2, 3, etc. of the document\n"
            "- If the document spans multiple pages, extract what's visible on THIS page\n"
            "- Look for page numbers or headers/footers\n"
            "- Note if the document appears incomplete (e.g., cut off at edges)\n"
            + (f"\nPage hint: {page_hint}" if page_hint else "")
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all fields from this government-issued ID document. Return JSON."},
                    self._base64_to_data_url(b64_image),
                ],
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
                        "num_predict": 1024,
                        "num_ctx": 4096,
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

    async def _extract_id_from_pdf_pages(self, pages: List[tuple]) -> str:
        """Extract ID fields from a multi-page PDF by analyzing all pages together.

        Args:
            pages: List of (base64_image, page_number) tuples

        Returns:
            JSON string with merged extracted fields from all pages
        """
        # First pass: extract fields from each page independently
        page_results = []
        for b64_page, page_num in pages:
            system_msg = (
                "You are an expert document analyst specializing in government-issued identity documents.\n"
                "This is page {page_num} of a multi-page document.\n\n"
                "Extract ALL fields visible on THIS page. Note which side (front/back) this appears to be.\n\n"
                "FIELDS TO EXTRACT:\n"
                "- document_type: national_id, passport, drivers_license, visa, residence_permit\n"
                "- issuing_country: Full country name\n"
                "- surname: Last name\n"
                "- given_name: First name\n"
                "- full_name: Complete name\n"
                "- nationality: Country of citizenship\n"
                "- date_of_birth: Date of birth\n"
                "- place_of_birth: City/region/country\n"
                "- sex: M/F/other\n"
                "- date_of_issue: Issue date\n"
                "- date_of_expiry: Expiry date\n"
                "- authority: Issuing authority\n"
                "- personal_id_number: Unique personal ID\n"
                "- document_number: Main document number\n"
                "- mrz: Machine Readable Zone text (if present)\n"
                "- address: Address (if shown)\n"
                "- signature: yes/no\n"
                "- photo: yes/no\n"
                "- page_number: Current page number\n"
                "- side: front or back (guess from content)\n\n"
                "Return ONLY valid JSON — no markdown, no explanation.\n"
                "Use this structure:\n"
                "{{\n"
                '  "page_number": 1,\n'
                '  "side": "front|back|unknown",\n'
                '  "fields": {{}}\n'
                "}}\n\n"
                "RULES:\n"
                "- Extract EXACTLY what you see — do not infer missing data\n"
                "- Use empty string for fields not visible on this page\n"
                "- For dates, preserve the original format"
            ).format(page_num=page_num)

            messages = [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Extract fields from page {page_num} of this ID document."},
                        self._base64_to_data_url(b64_page),
                    ],
                },
            ]

            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 1024,
                        "num_ctx": 4096,
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

        result = {
            "document_type": merged_fields.get("document_type", "unknown"),
            "issuing_country": merged_fields.get("issuing_country", ""),
            "total_pages": len(pages),
            "front_page": front_side,
            "back_page": back_side,
            "fields": front_fields,
            "_note": "All fields merged from available pages. Some fields may only appear on the back side."
        }

        return json.dumps(result)

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
                "content": [
                    {"type": "text", "text": f"Validate this document. It should be one of: {allowed}. Return JSON."},
                    self._base64_to_data_url(b64_image),
                ],
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
                        "num_ctx": 4096,
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
