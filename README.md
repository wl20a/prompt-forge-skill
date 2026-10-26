# Prompt Forge

Prompt Forge is a Codex skill for deciding when a request needs a stronger task
contract, when it should be executed directly, and when the agent must stop and
ask. It also includes a local preference ledger and an executable A/B harness.

Current version: **0.4.3**

This is an experimental personal tool. The included evaluations are pilots, not
evidence that Prompt Forge is universally better than direct execution.

## What it does

- Routes clear, low-risk requests to direct execution.
- Grounds ambiguous or high-risk requests in repository and file evidence.
- Separates `MUST`, `SHOULD`, `MAY`, and `MUST NOT` without silently changing
  obligation strength.
- Keeps read, local-write, destructive, and external-action authority separate.
- Records prompt and task-contract changes in a scoped local ledger.
- Compiles explicit accept/reject signals into stable, tentative, avoid, and
  conflict states.
- Runs isolated A/B tasks with the same model, permissions, checks, and optional
  reference images.
- Separates outcome checks from process diagnostics.

## Install

Clone this repository into your Codex user skill directory:

```bash
git clone https://github.com/wl20a/prompt-forge-skill.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/prompt-forge"
```

If your setup reads `~/.agents/skills`, use that directory instead:

```bash
git clone https://github.com/wl20a/prompt-forge-skill.git \
  "$HOME/.agents/skills/prompt-forge"
```

Invoke it explicitly in Codex:

```text
$prompt-forge
```

It is also configured for implicit invocation when a request matches the skill
description.

## Repository layout

```text
SKILL.md              Main skill instructions
agents/openai.yaml    Skill UI metadata and invocation policy
references/           Evaluation, ledger, and A/B harness details
scripts/ledger.py     Local preference ledger
scripts/ab_eval.py    Executable Codex A/B harness
evaluations/          Pilot reports and reproducible evidence
```

## Ledger

Default location:

```text
${CODEX_HOME:-$HOME/.codex}/prompt-forge/ledger.jsonl
```

Override it with `PROMPT_FORGE_LEDGER`.

Useful commands:

```bash
python3 scripts/ledger.py profile --scope coding --format markdown
python3 scripts/ledger.py list --scope coding --limit 20
python3 scripts/ledger.py resolve --id RECORD_ID --decision accepted \
  --evidence "User explicitly accepted this version"
```

Preferences are learned only from explicit acceptance, rejection, edits, or
version selection. Pending records and silence never become preferences.

## A/B harness

```bash
python3 scripts/ab_eval.py run \
  --manifest path/to/manifest.json \
  --out path/to/results
```

Use `--dry-run` before a real run. The harness supports text and reference-image
tasks, isolated per-arm ledgers, predeclared checks, randomized arm order, and
JSON/CSV/Markdown reports.

See [references/ab-harness.md](references/ab-harness.md) for the manifest schema
and supported checks.

## Evaluations

- [General prompt/task A/B](evaluations/prompt-and-task.md)
- [Reference-image frontend hover A/B](evaluations/frontend-hover/report.md)

The frontend visual pilot found a real tradeoff:

- Prompt Forge matched the reference dimensions exactly.
- SSIM improved from `0.7827` to `0.8799`.
- MAE improved from `0.0735` to `0.0227`.
- Runtime increased from `87.72 s` to `271.84 s`.
- Total input tokens increased from `893,849` to `3,906,148`; most of the
  candidate input was cached, so raw token volume and billed input are not the
  same measurement.
- Output tokens increased from `14,788` to `39,569`.

See the evaluation report for methodology, images, and limitations.

## Validation

The skill has been checked with the system `skill-creator` validator. The Python
scripts compile and the harness has been exercised against real Codex runs.

## Scope and limitations

- It does not grant permissions by itself.
- It does not turn silence into preference evidence.
- It does not replace domain-specific skills.
- It does not guarantee that Codex invokes it implicitly.
- Visual fidelity remains dependent on the host model, browser tooling, and
  user-defined acceptance checks.
- Prompt quality should be judged by task outcomes, not prose appearance.
