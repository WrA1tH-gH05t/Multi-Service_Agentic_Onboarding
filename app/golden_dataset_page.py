"""
Golden dataset page for Streamlit — displays stats, lets you browse/search/validate
entries from the golden dataset. Uses cached API calls so the page never hangs.

Module Purpose & Role in the Project:
-------------------------------------
This module provides a standalone interactive Streamlit dashboard allowing operators,
compliance officers, and developers to explore, search, compare, and validate ground-truth
identity documents maintained by the `GoldenDatasetService`. It interacts directly with the
FastAPI backend endpoints exposed under `/api/v1/golden-dataset/*` (implemented in `app/routes/golden.py`).

Interconnections with Other Files:
-----------------------------------
- Consumes REST API endpoints from `app/routes/golden.py`:
  * `GET /api/v1/golden-dataset/summary`: Statistical breakdown of benchmark data.
  * `GET /api/v1/golden-dataset/entries`: Paginated and filtered ground truth documents.
  * `GET /api/v1/golden-dataset/search`: Keyword search over dataset fields and metadata.
  * `GET /api/v1/golden-dataset/field-names`: Unique field names across all golden records.
  * `GET /api/v1/golden-dataset/field-examples`: Representative values for a given field.
  * `POST /api/v1/golden-dataset/validate`: Compares arbitrary extraction outputs against ground truth.
  * `POST /api/v1/golden-dataset/compare`: Side-by-side diff between two golden dataset entries.
- Directly mirrors capabilities from `services.golden_dataset.GoldenDatasetService`.
"""

import streamlit as st
import requests

API_BASE = "http://localhost:8000/api/v1"

GOLDEN_PATH = "/golden-dataset"


def _get(path, timeout=15):
    """
    Execute an HTTP GET request to the backend API.

    Detailed Behavior:
    - Makes a GET request to `{API_BASE}{path}` with a configurable timeout.
    - If status code is 200, returns (True, response_json).
    - If non-200 or an exception occurs, returns (False, error_payload).

    Parameters:
        path (str): Relative URL path appended to `API_BASE` (e.g. '/golden-dataset/summary').
        timeout (int): Request timeout in seconds (defaults to 15s).

    Returns:
        tuple[bool, dict]: (success_flag, json_body_or_error_dict).

    Interconnections:
        - Calls endpoints in `app/routes/golden.py`.
    """
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        if r.status_code == 200:
            return True, r.json()
        return False, r.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def _post(path, json_body, timeout=15):
    """
    Execute an HTTP POST request to the backend API with a JSON payload.

    Detailed Behavior:
    - Sends an HTTP POST request to `{API_BASE}{path}` containing `json_body`.
    - Returns (True, response_json) on HTTP 200, or (False, error_dict) on failure.

    Parameters:
        path (str): Relative URL path appended to `API_BASE`.
        json_body (dict): Dictionary serialized as JSON request body.
        timeout (int): Request timeout in seconds (defaults to 15s).

    Returns:
        tuple[bool, dict]: (success_flag, json_body_or_error_dict).

    Interconnections:
        - Dispatches validation and comparison requests to `app/routes/golden.py`.
    """
    try:
        r = requests.post(f"{API_BASE}{path}", json=json_body, timeout=timeout)
        if r.status_code == 200:
            return True, r.json()
        return False, r.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def render_summary():
    """
    Render high-level dataset metrics and breakdowns in the Streamlit UI.

    Detailed Behavior:
    - Fetches statistical summary via `GET /golden-dataset/summary`.
    - Renders total entry count and distinct country count using `st.metric`.
    - Outlines distributions of document types (e.g., national_id, passport) and
      capture conditions (e.g., table, handheld, cluttered, partial).

    Interconnections:
        - Calls `app/routes/golden.py:get_golden_dataset_summary`.
    """
    st.subheader("📊 Dataset Summary")
    ok, body = _get(f"{GOLDEN_PATH}/summary")
    if not ok or "error" in body:
        st.error(f"Could not load summary: {body.get('error')}")
        return
    summary = body["data"]
    st.metric("Total entries", summary.get("total_entries", 0))
    st.metric("Countries", len(summary.get("countries", [])))
    st.write("### Document types")
    for dt, cnt in summary.get("document_types", {}).items():
        st.write(f"- **{dt}**: {cnt}")
    st.write("### Capture conditions")
    for cc, cnt in summary.get("capture_conditions", {}).items():
        st.write(f"- **{cc}**: {cnt}")


def render_browse():
    """
    Render interactive filter controls and list ground-truth entries.

    Detailed Behavior:
    - Provides UI dropdowns and input boxes for filtering by document type,
      capture condition, country code, and max display limit.
    - Queries `GET /golden-dataset/entries` with formatted query parameters.
    - Expands each matching document entry displaying golden field values, source notes,
      and validation rules.

    Interconnections:
        - Calls `app/routes/golden.py:get_golden_dataset_entries`.
    """
    st.subheader("🔍 Browse Entries")
    col1, col2, col3 = st.columns(3)
    with col1:
        doc_type = st.selectbox(
            "Document type",
            options=["all"] + ["national_id", "passport", "driving_license"],
            index=0,
        )
    with col2:
        condition = st.selectbox(
            "Capture condition",
            options=["all"] + ["table", "handheld", "cluttered", "partial"],
            index=0,
        )
    with col3:
        country = st.text_input("Country code (optional)", value="").strip()

    limit = st.slider("Show up to", 5, 200, 50)

    params = []
    if doc_type != "all":
        params.append(f"doc_type={doc_type}")
    if condition != "all":
        params.append(f"condition={condition}")
    if country:
        params.append(f"country={country}")
    params.append(f"limit={limit}")

    path = f"{GOLDEN_PATH}/entries?{'&'.join(params)}"
    ok, body = _get(path)

    if not ok or "error" in body:
        st.error(f"Could not load entries: {body.get('error')}")
        return

    entries = body["data"]["entries"]
    if not entries:
        st.info("No entries match the selected filters.")
        return

    for entry in entries:
        with st.expander(f"📄 {entry['id']} — {entry['document_type']} ({entry['capture_condition']})", expanded=False):
            st.json(entry["golden_fields"])
            if entry.get("source_note"):
                st.caption(entry["source_note"])
            if entry.get("validation_rules"):
                st.caption(f"Rules: {entry['validation_rules']}")


def render_search():
    """
    Render keyword search UI querying golden dataset entries.

    Detailed Behavior:
    - Allows free-form textual queries (e.g. 'passport table name') with slider for result limit.
    - Calls `GET /golden-dataset/search?query=...&limit=...`.
    - Renders matching records ordered by relevance score with detailed field views.

    Interconnections:
        - Calls `app/routes/golden.py:search_golden_dataset`.
    """
    st.subheader("🔎 Search")
    query = st.text_input("Search terms", placeholder="e.g. passport table name")
    limit = st.slider("Results", 1, 50, 10)

    if query:
        path = f"{GOLDEN_PATH}/search?query={query}&limit={limit}"
        ok, body = _get(path)

        if not ok or "error" in body:
            st.error(f"Search failed: {body.get('error')}")
            return

        results = body["data"].get("results", [])
        if not results:
            st.info("No results found.")
            return

        for r in results:
            with st.expander(
                f"📄 {r['id']} ({r['document_type']}) — score {r['relevance_score']}",
                expanded=False,
            ):
                st.json(r.get("golden_fields", {}))
                if r.get("source_note"):
                    st.caption(r["source_note"])


def render_field_names():
    """
    Render an exhaustive list of unique field names extracted across all golden documents.

    Detailed Behavior:
    - Calls `GET /golden-dataset/field-names`.
    - Displays total unique field count and bullets formatted field tags.

    Interconnections:
        - Calls `app/routes/golden.py:get_all_field_names`.
    """
    st.subheader("🏷️ All Fields")
    ok, body = _get(f"{GOLDEN_PATH}/field-names")
    if not ok or "error" in body:
        st.error(f"Could not load field names: {body.get('error')}")
        return

    fields = body["data"]["field_names"]
    st.write(f"{len(fields)} unique fields found:")
    for f in fields:
        st.write(f"- `{f}`")


def render_field_examples():
    """
    Render sample values for a user-selected field across documents.

    Detailed Behavior:
    - Populates a selector using unique field names from `GET /golden-dataset/field-names`.
    - Queries `GET /golden-dataset/field-examples?field_name=...` for the selected field.
    - Displays actual values and document associations from ground-truth data.

    Interconnections:
        - Calls `app/routes/golden.py:get_field_examples`.
    """
    st.subheader("💡 Field Examples")
    ok, body = _get(f"{GOLDEN_PATH}/field-names")
    if not ok or "error" in body:
        st.error(f"Could not load field names: {body.get('error')}")
        return

    fields = body["data"]["field_names"]
    if not fields:
        st.info("No fields available.")
        return

    sel = st.selectbox("Pick a field", fields)
    ok2, body2 = _get(f"{GOLDEN_PATH}/field-examples?field_name={sel}")
    if not ok2 or "error" in body2:
        st.error(f"Could not load examples: {body2.get('error')}")
        return

    for ex in body2["data"]["examples"]:
        st.write(f"- **{ex['entry_id']}** ({ex['document_type']}): `{ex['value']}`")


def render_validation():
    """
    Render validation sandbox comparing user/model extractions against ground truth.

    Detailed Behavior:
    - Loads ground-truth entries via `GET /golden-dataset/entries?limit=50`.
    - When an entry is selected, renders disabled ground-truth text inputs alongside editable
      inputs representing extracted model predictions.
    - On 'Validate' button click, submits a payload to `POST /golden-dataset/validate`.
    - Renders completion rate metric, overall validity badge, and per-field comparison checks.

    Interconnections:
        - Calls `app/routes/golden.py:validate_extraction`.
    """
    st.subheader("✅ Validate Extraction")
    st.caption("Enter extracted fields and compare against the golden dataset.")

    ok, body = _get(f"{GOLDEN_PATH}/entries?limit=50")
    if not ok or "error" in body:
        st.error(f"Could not load entries: {body.get('error')}")
        return

    entries = body["data"]["entries"]
    if not entries:
        st.info("No entries available for validation.")
        return

    entry_options = {e["id"]: e for e in entries}
    chosen_id = st.selectbox("Select golden entry", list(entry_options.keys()))

    if chosen_id:
        golden = entry_options[chosen_id]["golden_fields"]
        st.subheader("Golden values (ground truth)")
        for k, v in golden.items():
            st.text_input(k, value=v, disabled=True, key=f"gt_{k}")

        st.subheader("Enter your extraction")
        extracted = {}
        for k in golden:
            extracted[k] = st.text_input(k, key=f"ext_{k}")

        if st.button("Validate", type="primary"):
            ok3, body3 = _post(
                f"{GOLDEN_PATH}/validate",
                {"entry_id": chosen_id, "fields": extracted},
            )
            if not ok3 or "error" in body3:
                st.error(f"Validation failed: {body3.get('error')}")
                return

            result = body3["data"]
            st.metric("Completion rate", f"{result.get('completion_rate', 0) * 100:.0f}%")
            st.metric("Valid", "✅ Yes" if result.get("valid") else "❌ No")

            for chk in result.get("checks", []):
                icon = "✅" if chk["match"] else "❌"
                st.write(f"{icon} **{chk['field']}**: `{chk['golden_value']}` → `{chk['extracted_value']}`")


def render_compare():
    """
    Render a side-by-side comparison between two arbitrary golden dataset entries.

    Detailed Behavior:
    - Provides dropdowns for choosing two distinct document IDs.
    - Posts comparison query to `POST /golden-dataset/compare?entry1_id=...&entry2_id=...`.
    - Renders structured JSON diff highlighting matched, conflicting, or unique fields.

    Interconnections:
        - Calls `app/routes/golden.py:compare_golden_entries`.
    """
    st.subheader("⚖️ Compare Entries")

    ok, body = _get(f"{GOLDEN_PATH}/entries?limit=50")
    if not ok or "error" in body:
        st.error(f"Could not load entries: {body.get('error')}")
        return

    entries = body["data"]["entries"]
    ids = [e["id"] for e in entries]

    col1, col2 = st.columns(2)
    with col1:
        e1 = st.selectbox("Entry 1", ids)
    with col2:
        e2 = st.selectbox("Entry 2", ids)

    if e1 and e2 and e1 != e2:
        params = f"entry1_id={e1}&entry2_id={e2}"
        ok2, body2 = _post(f"{GOLDEN_PATH}/compare?{params}", {})
        if not ok2 or "error" in body2:
            st.error(f"Compare failed: {body2.get('error')}")
            return

        comp = body2["data"]
        st.json(comp)


def render_golden_dataset_page():
    """
    Main entrypoint function for rendering the Golden Dataset dashboard in Streamlit.

    Detailed Behavior:
    - Configures page header and organizes exploration capabilities into six tabs:
      1. 'Summary': High-level statistics.
      2. 'Browse': Filterable document catalog.
      3. 'Search': Relevance-based search.
      4. 'Fields': Field dictionary and samples.
      5. 'Validate': Extraction evaluation sandbox.
      6. 'Compare': Two-entry diff viewer.

    Interconnections:
        - Invoked by the primary Streamlit app runner to render the dataset interface.
    """
    st.markdown('<h2 style="color:#e4e6eb">🏆 Golden Dataset</h2>', unsafe_allow_html=True)
    st.caption("Browse, search, validate, and compare golden document extractions.")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Summary", "Browse", "Search", "Fields", "Validate", "Compare",
    ])

    with tab1:
        render_summary()

    with tab2:
        render_browse()

    with tab3:
        render_search()

    with tab4:
        render_field_names()
        st.markdown("---")
        render_field_examples()

    with tab5:
        render_validation()

    with tab6:
        render_compare()
