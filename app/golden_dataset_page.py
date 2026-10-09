"""
Golden dataset page for Streamlit — displays stats, lets you browse/search/validate
entries from the golden dataset.  Uses cached API calls so the page never hangs.
(No changes from v1 — golden dataset is in-memory, no DB dependency)
"""

import streamlit as st
import requests

API_BASE = "http://localhost:8000/api/v1"

GOLDEN_PATH = "/golden-dataset"


def _get(path, timeout=15):
    """GET from the API, return (ok, json_body)."""
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=timeout)
        if r.status_code == 200:
            return True, r.json()
        return False, r.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def _post(path, json_body, timeout=15):
    """POST to the API, return (ok, json_body)."""
    try:
        r = requests.post(f"{API_BASE}{path}", json=json_body, timeout=timeout)
        if r.status_code == 200:
            return True, r.json()
        return False, r.json()
    except Exception as exc:
        return False, {"error": str(exc)}


def render_summary():
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
