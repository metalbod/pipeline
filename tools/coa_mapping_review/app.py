"""COA mapping review UI (v1).

This screen IS the human-approval step CLAUDE.md requires for chart-of-accounts mappings before
they merge into dbt_project/seeds/seed_coa_mapping.csv -- it does not bypass that rule. A human
runs the coa-mapper subagent in chat, pastes/uploads its proposal CSV here, edits/reviews it, and
confirms; only rows explicitly marked "Approve" are ever written, and only after passing the same
duplicate-key and foreign-key checks that gate the mapping in dbt. Nothing here auto-triggers a
dbt rebuild or a git commit -- both stay separate, deliberate human steps afterward.
"""

import os
import subprocess
from datetime import date, datetime

import polars as pl
import streamlit as st

from tools.coa_mapping_review import data_access, validation, write_path
from tools.coa_mapping_review.data_access import WarehouseNotBuiltError
from tools.coa_mapping_review.proposal_io import ProposalParseError, parse_proposal_csv

st.set_page_config(page_title="COA Mapping Review", layout="wide")

DECISION_OPTIONS = ["Pending", "Approve", "Reject"]


def _default_reviewer_name() -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("COA_REVIEWER_NAME", "")


st.title("Chart-of-Accounts Mapping Review")
st.warning(
    "This screen is the human-approval step required by CLAUDE.md's COA governance rule, not a "
    "way around it. Nothing is written to `seed_coa_mapping.csv` until you explicitly mark a row "
    "**Approve** and click Confirm below."
)

try:
    entities = data_access.list_entities()
    group_codes_df = data_access.list_group_standard_codes()
except WarehouseNotBuiltError as exc:
    st.error(str(exc))
    st.stop()

if entities.is_empty() or group_codes_df.is_empty():
    st.warning("`dim_entity` or `dim_account_group_standard` is empty -- has `dbt build` been run?")
    st.stop()

valid_codes = set(group_codes_df["group_standard_code"].to_list())

st.subheader("1. Batch details")
col1, col2 = st.columns(2)
with col1:
    entity_options = {
        f"{r['entity_id']} — {r['entity_name']}": r["entity_id"]
        for r in entities.iter_rows(named=True)
    }
    entity_label = st.selectbox("Entity", options=list(entity_options.keys()))
    entity_id = entity_options[entity_label]
with col2:
    default_effective_from = st.date_input("Default effective_from", value=date.today())

with st.expander("Valid group-standard account codes (reference)"):
    st.dataframe(group_codes_df, hide_index=True, width="stretch")

st.subheader("2. Paste or upload the coa-mapper proposal")
st.caption(
    "Ask coa-mapper (in chat) to emit its proposal as CSV with columns: local_account_code, "
    "local_account_name, proposed_group_standard_account_code, confidence, rationale."
)
uploaded = st.file_uploader("Upload proposal CSV", type=["csv"])
pasted = st.text_area("...or paste proposal CSV here", height=150)

raw_csv_text = None
if uploaded is not None:
    raw_csv_text = uploaded.getvalue().decode("utf-8")
elif pasted.strip():
    raw_csv_text = pasted

if not raw_csv_text:
    st.info("Provide a proposal above to begin review.")
    st.stop()

try:
    proposal_df = parse_proposal_csv(raw_csv_text)
except ProposalParseError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("3. Review, edit, and decide")

editor_input = proposal_df.with_columns(
    [
        pl.when(pl.col("proposed_group_standard_account_code").is_in(list(valid_codes)))
        .then(pl.col("proposed_group_standard_account_code"))
        .otherwise(pl.lit(""))
        .alias("group_standard_account_code"),
        pl.lit(default_effective_from.isoformat()).alias("effective_from"),
        pl.lit("Pending").alias("decision"),
    ]
).select(
    [
        "local_account_code",
        "local_account_name",
        "group_standard_account_code",
        "confidence",
        "rationale",
        "effective_from",
        "decision",
    ]
)

edited = st.data_editor(
    editor_input,
    hide_index=True,
    width="stretch",
    column_config={
        "local_account_code": st.column_config.TextColumn("Local code"),
        "local_account_name": st.column_config.TextColumn("Local name"),
        "group_standard_account_code": st.column_config.SelectboxColumn(
            "Group-standard code", options=[""] + sorted(valid_codes), required=False
        ),
        "confidence": st.column_config.TextColumn("Confidence (proposed)", disabled=True),
        "rationale": st.column_config.TextColumn("Rationale (proposed)", disabled=True),
        "effective_from": st.column_config.TextColumn("Effective from (YYYY-MM-DD)"),
        "decision": st.column_config.SelectboxColumn("Decision", options=DECISION_OPTIONS),
    },
    key="coa_mapping_editor",
)

approve_rows = [
    {**row, "entity_id": entity_id}
    for row in edited.filter(pl.col("decision") == "Approve").iter_rows(named=True)
]
pending_count = edited.filter(pl.col("decision") == "Pending").height

if pending_count:
    st.info(f"{pending_count} row(s) are still Pending and will not be written until decided.")

st.subheader("4. Confirm")
approved_by = st.text_input("Approved by", value=_default_reviewer_name())
st.caption(
    "Identifies who approved the mapping in the audit trail -- this is **not authentication**. "
    "Anyone with access to this tool can enter any name. Run only on a trusted machine / "
    "internal network."
)

errors: dict[int, list[str]] = {}
if approve_rows:
    existing_keys = validation.read_existing_keys()
    errors = validation.validate_batch(approve_rows, existing_keys, valid_codes)

if errors:
    st.error("Fix the following before confirming:")
    for idx, messages in errors.items():
        row = approve_rows[idx]
        st.markdown(f"- **{row.get('local_account_code', '?')}**: {'; '.join(messages)}")

confirm_disabled = not approve_rows or bool(errors) or not approved_by.strip()

if st.button("Confirm and write approved mappings", disabled=confirm_disabled):
    rows_to_write = [
        write_path.build_row(row, approved_by.strip(), datetime.now()) for row in approve_rows
    ]
    count = write_path.append_rows(rows_to_write)
    st.success(
        f"Wrote {count} row(s) to dbt_project/seeds/seed_coa_mapping.csv. "
        "Review with `git diff`, then `git add`/`commit`/`push` yourself when ready. "
        "Run `dbt build` to pick up the new mapping."
    )
