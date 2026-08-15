# COA Mapping Review UI (v1)

An internal Streamlit screen for the human-approval step CLAUDE.md requires before a
chart-of-accounts mapping merges into `dbt_project/seeds/seed_coa_mapping.csv`. This tool **is**
that approval step — a reviewer sees proposed mappings, edits or rejects them, and confirms — it
does not weaken or bypass the "never auto-applied" governance rule.

## Workflow

1. Run the `coa-mapper` subagent in chat as today, and ask it to emit its proposal table as CSV
   (`local_account_code, local_account_name, proposed_group_standard_account_code, confidence,
   rationale`).
2. `dbt build` at least once, so `dim_entity`/`dim_account_group_standard` exist in the warehouse
   for the dropdowns.
3. Run this app (`.venv/bin/streamlit run tools/coa_mapping_review/app.py`, or via the
   `coa-mapping-review` entry in `.claude/launch.json`, port 8502).
4. Paste or upload the proposal CSV, pick the entity, review each row, mark each **Approve** or
   **Reject**, enter your name, and click Confirm.
5. Confirmed rows are appended (never rewritten/reordered) to `seed_coa_mapping.csv`. Review the
   change with `git diff`, then `git add`/`commit`/`push` yourself — this tool does not touch git.
6. Run `dbt build` to pick up the new mapping.

## What this tool is not

- **Not authentication.** The "Approved by" field is pre-filled from `git config user.name` (or
  `COA_REVIEWER_NAME`) purely to reduce typos in the audit trail — anyone with access to this tool
  can type any name. Run it only on a trusted machine or internal network. Real access control
  (e.g. tying approval into `seed_user_entity_access.csv` roles, or a real login) is a named
  future iteration, not built here.
- **Not a live call to `coa-mapper`.** v1 is decoupled from the subagent's matching logic on
  purpose — it only reviews a proposal you already generated in chat and pasted/uploaded. Wiring
  the UI to call the matcher directly is a future iteration.
- **Not a second review layer on top of a PR.** Confirming here replaces the "human hand-edits the
  CSV in a PR" step; it doesn't add a second reviewer beyond the person who confirms. A `git diff`
  still exists for whoever pushes to inspect, but there's no separate approver enforced by this
  tool.
- **Not a full mapping lifecycle.** v1 only adds new rows. Deactivating or superseding an existing
  mapping (via `effective_to`) isn't supported yet — do that by hand, same as today.

## Validation

Before Confirm is enabled, every `Approve`-decision row must pass:
- No duplicate `(entity_id, local_account_code, effective_from)` against the existing seed file or
  another row in the same batch — mirrors the `dbt_utils.unique_combination_of_columns` test on
  `coa_mapping` (`dbt_project/models/silver/properties.yml`).
- `group_standard_account_code` must be a real code from `dim_account_group_standard`.
- No missing required fields.

This is a client-side mirror for fast feedback, not a replacement for `dbt test`, which still runs
for real after `dbt build`.
