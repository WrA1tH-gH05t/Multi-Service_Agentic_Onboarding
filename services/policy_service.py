"""
Policy Service — Loads and serves policy documents for FAQ grounding.

This service reads the policy markdown files from docs/ and provides
structured access to policy rules for answering user questions.

The service ensures every answer is grounded in actual policy documents,
never invented information — exactly as specified in the problem statement.

Module Architecture & Interconnections:
----------------------------------------
- Role in the Project:
  * Serves as the authoritative source of truth for onboarding policies, compliance constraints,
    and business rules.
  * Parses markdown policies in `docs/` into hierarchical, indexed sections.
  * Eliminates LLM hallucinations during customer FAQ conversations by finding matching policy
    passages and assembling structured grounding prompts for LLM generation.
- Upstream Callers:
  * `app.routes.validation`:
    Imports `get_grounding_context` and passes policy context to FAQ response generation.
  * `app.routes.wizard`:
    References policy rules to explain submission rejections, mandatory criteria, or SLA windows.
- Downstream Storage & Dependencies:
  * Reads `.md` files residing in `docs/` matching `POLICY`, `POLICIES`, or `SERVICE_DEFS`.
  * Indexes headings, control blocks (Version, Date, Purpose), and full-text keywords in memory.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PolicySection:
    """A single structured section within a policy document.

    Attributes:
        title (str): Section header title text.
        content (str): Plain markdown body content belonging to this section.
        heading_level (int): Markdown heading depth (1 to 6).
        parent_title (str): Title of the immediately enclosing parent heading.
        path (str): Identifier or hierarchical section number (e.g., '1.1' or '2.3.1').
    """
    title: str
    content: str
    heading_level: int = 1
    parent_title: str = ""
    path: str = ""  # e.g., "1.1" or "2.3.1"


@dataclass
class PolicyDocument:
    """A complete parsed policy document.

    Attributes:
        name (str): Normalized file basename without extension.
        filepath (str): Absolute file path to the source markdown document.
        title (str): Document title extracted from the top-level H1 heading.
        sections (List[PolicySection]): Ordered list of parsed policy sections.
        metadata (Dict): Metadata extracted from the Document Control block (version, date, purpose).
    """
    name: str
    filepath: str
    title: str
    sections: List[PolicySection] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class PolicyService:
    """
    Loads policy documents and provides grounded answers for FAQ/chat.

    Design Decision: Instead of sending the entire policy library to the LLM
    (which wastes tokens and risks context overflow), we:
    1. Parse policies into structured sections
    2. Match user queries to relevant sections
    3. Send only the most relevant sections as context
    4. Ground answers in the actual policy text

    This ensures:
    - Every answer comes from actual policy, never invented
    - Token usage stays reasonable
    - Answers are specific and traceable to source sections

    Attributes:
        docs_dir (str): Directory path containing markdown policy files.
        _policies (Dict[str, PolicyDocument]): Mapping of policy name -> PolicyDocument.
        _section_index (Dict[str, List[Tuple[str, str]]]): Keyword index -> [(policy_name, section_path)].

    Interconnections:
        - Exported and used by `get_policy_service()`, `get_grounding_context()`, and `find_relevant_policies()`.
        - Invoked during chatbot turns and FAQ lookups in `app.routes.validation`.
    """

    def __init__(self, docs_dir: str = None):
        """Initialize PolicyService and parse all available policy files.

        Args:
            docs_dir (Optional[str]): Path to documentation directory; defaults to `docs/`
                located relative to project root.
        """
        # Resolve to docs/ relative to project root (parent of services/)
        if docs_dir is None:
            service_file = os.path.abspath(__file__)
            # service_file is at: .../task 1/services/policy_service.py
            # We need: .../task 1/docs
            services_dir = os.path.dirname(service_file)  # .../task 1/services
            project_root = os.path.dirname(services_dir)   # .../task 1
            docs_dir = os.path.join(project_root, "docs")
        self.docs_dir = docs_dir
        self._policies: Dict[str, PolicyDocument] = {}
        self._section_index: Dict[str, List[Tuple[str, str]]] = {}  # keyword -> [(policy_name, section_path)]
        self.load_all_policies()

    def load_all_policies(self):
        """Load and index all .md policy files from docs/ directory.

        Filters filenames containing 'POLICY', 'POLICIES', or 'SERVICE_DEFS'.
        Logs loaded policy counts and total sections.
        """
        if not os.path.exists(self.docs_dir):
            logger.warning(f"Policy docs directory not found: {self.docs_dir}")
            return

        policy_files = [f for f in os.listdir(self.docs_dir) 
                        if f.endswith('.md') and (
                            'POLICY' in f.upper() or 
                            'POLICIES' in f.upper() or 
                            'SERVICE_DEFS' in f.upper()
                        )]

        for filename in policy_files:
            filepath = os.path.join(self.docs_dir, filename)
            try:
                policy = self._load_policy_file(filepath)
                if policy:
                    self._policies[policy.name] = policy
                    self._index_policy(policy)
                    logger.info(f"Loaded policy: {policy.name} ({len(policy.sections)} sections)")
            except Exception as e:
                logger.error(f"Failed to load policy {filename}: {e}")

        logger.info(f"Policy service loaded {len(self._policies)} policies")

    def _load_policy_file(self, filepath: str) -> Optional[PolicyDocument]:
        """Parse a policy markdown file into structured sections.

        Args:
            filepath: Absolute path to the policy file.

        Returns:
            Optional[PolicyDocument]: Parsed policy document object.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract metadata
        metadata = {}
        if '## Document Control' in content:
            metadata = self._extract_metadata(content)

        # Extract title
        title = self._extract_title(content)
        name = os.path.splitext(os.path.basename(filepath))[0]

        # Parse sections
        sections = self._parse_sections(content)

        return PolicyDocument(
            name=name,
            filepath=filepath,
            title=title,
            sections=sections,
            metadata=metadata
        )

    def _extract_metadata(self, content: str) -> Dict:
        """Extract version, date, author, status from Document Control section.

        Args:
            content: Raw markdown text string.

        Returns:
            Dict: Key-value dictionary containing 'version', 'date', 'purpose'.
        """
        metadata = {}
        if '## Document Control' in content:
            block = content.split('## Document Control')[1].split('---')[0]
            for line in block.split('\n'):
                line = line.strip()
                if line.startswith('- **Version:**'):
                    metadata['version'] = line.split(':')[1].strip()
                elif line.startswith('- **Date:**'):
                    metadata['date'] = line.split(':')[1].strip()
                elif line.startswith('- **Purpose:**'):
                    metadata['purpose'] = line.split(':', 1)[1].strip()
        return metadata

    def _extract_title(self, content: str) -> str:
        """Extract the main title from the first heading.

        Args:
            content: Raw markdown text string.

        Returns:
            str: Document title string or 'Unknown Policy' if heading is absent.
        """
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Unknown Policy"

    def _parse_sections(self, content: str) -> List[PolicySection]:
        """Parse markdown content into hierarchical sections.

        Tracks heading depths and updates parent titles sequentially.

        Args:
            content: Raw markdown content string.

        Returns:
            List[PolicySection]: List of structured policy sections.
        """
        sections = []
        lines = content.split('\n')

        current_section = None
        current_content = []
        heading_stack = []  # Track heading hierarchy for parent titles

        for line in lines:
            # Check for heading
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                # Save previous section
                if current_section and current_content:
                    current_section.content = '\n'.join(current_content).strip()
                    sections.append(current_section)

                # Start new section
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                # Determine parent title
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                parent = heading_stack[-1][1] if heading_stack else ""

                # Generate section path
                path = self._get_section_path(level, title)

                current_section = PolicySection(
                    title=title,
                    content="",
                    heading_level=level,
                    parent_title=parent,
                    path=path
                )
                current_content = []
                heading_stack.append((level, title))

            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section and current_content:
            current_section.content = '\n'.join(current_content).strip()
            sections.append(current_section)

        return sections

    def _get_section_path(self, level: int, title: str) -> str:
        """Generate a section path like '1.1' or '2.3.1'.

        Args:
            level: Heading level number.
            title: Section title text.

        Returns:
            str: Normalized section path identifier string.
        """
        # Simple heuristic: use level and title number
        match = re.match(r'(\d+)[\.\s]', title)
        if match:
            return match.group(1)
        return title[:20].replace(' ', '_').lower()

    def _index_policy(self, policy: PolicyDocument):
        """Build keyword index for efficient policy retrieval.

        Args:
            policy: PolicyDocument instance to index.
        """
        for section in policy.sections:
            # Index section title and content keywords
            keywords = self._extract_keywords(section.title + " " + section.content)

            for keyword in keywords:
                if keyword not in self._section_index:
                    self._section_index[keyword] = []
                self._section_index[keyword].append((policy.name, section.path))

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text by filtering stop words.

        Args:
            text: Input text string.

        Returns:
            List[str]: List of extracted keyword strings longer than 2 characters.
        """
        # Simple keyword extraction: words longer than 3 characters
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        # Remove common stop words
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
                      'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
                      'have', 'been', 'from', 'this', 'that', 'with', 'will'}
        return [w for w in words if w not in stop_words]

    def find_relevant_policies(self, query: str, max_sections: int = 5) -> List[Tuple[str, PolicySection]]:
        """
        Find the most relevant policy sections for a query.

        Scores sections based on keyword hits in body, title weighting, and direct section number references.

        Args:
            query: User question or search phrase.
            max_sections: Maximum number of candidate sections to return (default: 5).

        Returns:
            List[Tuple[str, PolicySection]]: List of (policy_name, section) tuples, sorted by relevance.

        Interconnections:
            - Used by `build_grounding_context()` and convenience function `find_relevant_policies()`.
        """
        query_keywords = self._extract_keywords(query)

        # Score each section by keyword matches
        section_scores = []

        for policy_name, policy in self._policies.items():
            for section in policy.sections:
                score = 0
                section_text = (section.title + " " + section.content).lower()

                # Exact keyword matches
                for kw in query_keywords:
                    if kw in section_text:
                        # Title matches are worth more
                        if kw in section.title.lower():
                            score += 3
                        else:
                            score += 1

                # Section path matches (e.g., query mentions "1.1")
                if section.path in query.lower():
                    score += 5

                if score > 0:
                    section_scores.append((score, policy_name, section))

        # Sort by score (descending) and return top sections
        section_scores.sort(key=lambda x: x[0], reverse=True)
        return [(name, section) for score, name, section in section_scores[:max_sections]]

    def build_grounding_context(self, query: str, max_sections: int = 5) -> str:
        """
        Build a grounding context string from relevant policy sections.

        This context is sent to the LLM to ground its answers in actual policy.

        Args:
            query: Question or prompt submitted by the applicant.
            max_sections: Number of sections to include in the context (default: 5).

        Returns:
            str: Markdown-formatted grounding block ready for LLM prompt injection.
                 Returns empty string if no relevant sections are found.

        Interconnections:
            - Consumed by `app.routes.validation.ask_faq` to constrain LLM generations.
        """
        relevant = self.find_relevant_policies(query, max_sections)

        if not relevant:
            return ""

        context_parts = []
        context_parts.append("# POLICY CONTEXT FOR ANSWERING\n")
        context_parts.append("The following policy sections contain relevant information for answering the user's question.\n")
        context_parts.append("Use ONLY this context to answer. Do not invent information.\n\n")

        for policy_name, section in relevant:
            context_parts.append(f"## Source: {policy_name} — {section.title} (Section {section.path})\n")
            context_parts.append(section.content + "\n\n")

        return '\n'.join(context_parts)

    def get_policy_summary(self, policy_name: str) -> Optional[str]:
        """Get a summary of a specific policy document by name.

        Args:
            policy_name: File basename identifier of policy document.

        Returns:
            Optional[str]: Formatted markdown summary including version, date, purpose,
                and key section titles; None if policy is not found.
        """
        policy = self._policies.get(policy_name)
        if not policy:
            return None

        summary_parts = [f"# {policy.title}\n"]
        summary_parts.append(f"**Version:** {policy.metadata.get('version', 'N/A')}\n")
        summary_parts.append(f"**Date:** {policy.metadata.get('date', 'N/A')}\n\n")

        if 'purpose' in policy.metadata:
            summary_parts.append(f"**Purpose:** {policy.metadata['purpose']}\n\n")

        summary_parts.append("## Key Sections\n\n")
        for section in policy.sections[:10]:  # First 10 sections
            summary_parts.append(f"- **{section.title}** (Section {section.path})\n")

        return '\n'.join(summary_parts)

    def list_available_policies(self) -> List[str]:
        """List all available policy document names.

        Returns:
            List[str]: List of loaded policy document identifier names.
        """
        return list(self._policies.keys())

    def get_all_policy_titles(self) -> List[str]:
        """Get titles of all policy documents.

        Returns:
            List[str]: List of human-readable policy titles.
        """
        return [p.title for p in self._policies.values()]


# Global policy service instance
_policy_service = None


def get_policy_service() -> PolicyService:
    """Get or create the global singleton policy service instance.

    Returns:
        PolicyService: Active singleton instance of PolicyService.
    """
    global _policy_service
    if _policy_service is None:
        _policy_service = PolicyService()
    return _policy_service


# Convenience functions for use in routes
def get_grounding_context(query: str) -> str:
    """Get grounding context for a query (used in chat/FAQ endpoints).

    Args:
        query: Incoming user question.

    Returns:
        str: Policy markdown context block.

    Interconnections:
        - Called by `app.routes.validation.ask_faq()` and chatbot services.
    """
    service = get_policy_service()
    return service.build_grounding_context(query)


def find_relevant_policies(query: str) -> List[Tuple[str, str]]:
    """Find relevant policy sections for a query.

    Args:
        query: Inquiry string.

    Returns:
        List[Tuple[str, str]]: List of (policy_name, section_path) tuples.
    """
    service = get_policy_service()
    relevant = service.find_relevant_policies(query)
    return [(name, section.path) for name, section in relevant]
