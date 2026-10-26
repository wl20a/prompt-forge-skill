# Prompt Forge Ledger

The ledger records semantic changes and explicit user decisions. It is not a
conversation archive and must not contain raw prompts, secrets, or personal data.

The default path is
`${CODEX_HOME:-$HOME/.codex}/prompt-forge/ledger.jsonl`. Override it with
`PROMPT_FORGE_LEDGER`.

## Record a Change

```bash
python3 scripts/ledger.py record \
  --task-id TASK \
  --category constraint \
  --action clarify \
  --summary "State the output schema explicitly" \
  --strength-before none \
  --strength-after must \
  --provenance user \
  --decision pending \
  --scope coding \
  --preference-key output-contract \
  --preference-value explicit-schema
```

Use one record for each semantic change, not each cosmetic edit. For a list of
changes, make one call:

```bash
python3 scripts/ledger.py record-many \
  --json '[{"task_id":"TASK","category":"constraint","action":"clarify",
  "summary":"State the output schema explicitly","strength_before":"none",
  "strength_after":"should","provenance":"user","decision":"pending",
  "scope":"coding","preference_key":"output-contract",
  "preference_value":"explicit-schema"}]'
```

The command prints the record IDs and writes the file with user-only
permissions. If one batch write fails, report it once and continue the task.

Use `provenance=user` only for an explicit user requirement. Use `repo:PATH` for
a repository rule, `inferred` for a model-added default, `safety` for a required
risk control, and `preference` for a prior scoped preference. An inferred test or
verification suggestion is not a `MUST`.

## Resolve a Decision

```bash
python3 scripts/ledger.py resolve --id RECORD_ID --decision accepted \
  --evidence "User said: use this version"
```

Resolve only from an explicit acceptance, rejection, correction, edit, or
selection. A clean test result proves the artifact worked; it does not prove that
the user accepted the prompt wording.

## Use Preferences

```bash
python3 scripts/ledger.py profile --scope coding --format markdown
```

The compiled profile separates:

- `single-observation`: one accepted task;
- `tentative`: at least two distinct tasks;
- `stable`: at least three distinct tasks and more acceptance than rejection;
- `explicit`: the user stated a standing rule.
- `should-avoid`: a value rejected in at least three distinct tasks.
- conflicts: multiple stable values for one key, which must not be auto-applied.

Apply suggestions as `SHOULD` or `MAY`. Promote one to `MUST` only on an explicit
standing instruction. Read matching scope only; do not expose unrelated records.
`suggest` remains available for raw diagnostic listings, but `profile` is the
source for behavior.

Inspect or audit recent entries with:

```bash
python3 scripts/ledger.py list --scope coding --limit 20
```
