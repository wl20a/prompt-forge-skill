# Executable A/B Harness

Use [scripts/ab_eval.py](../scripts/ab_eval.py) when the user asks whether
Prompt Forge, a prompt revision, or a skill version improves real task outcomes.
The harness runs each arm in a separate fixture copy, captures Codex JSONL, runs
predeclared checks, and writes a report.

## Manifest

```json
{
  "name": "prompt-forge-pilot",
  "arms": [
    {"id": "direct", "kind": "direct"},
    {"id": "prompt-forge", "kind": "skill", "skill": "auto"}
  ],
  "tasks": [
    {
      "id": "clear-report-fix",
      "fixture": "./fixtures/report-fix",
      "images": ["./references/hover-state.png"],
      "request": "Fix the report ordering bug, run the checks, and do not edit README.md or tests.",
      "timeout_seconds": 240,
      "checks": [
        {
          "name": "tests",
          "type": "command",
          "command": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
        },
        {
          "name": "protected-files",
          "type": "forbidden_paths",
          "paths": ["README.md", "tests"]
        },
        {
          "name": "scope",
          "type": "allowed_paths",
          "paths": ["reporting"]
        }
      ]
    }
  ]
}
```

`skill: "auto"` resolves to this skill's `SKILL.md`. An arm may point to another
absolute or relative skill file to compare versions.

`images` is an optional string array of reference images attached to every arm
for that task with Codex's `--image` flag. Paths resolve relative to the manifest.

## Checks

- `command`: `command` string array, pass on exit code zero.
- `forbidden_paths`: no changed path may match the listed file or directory prefixes.
- `allowed_paths`: every changed path must match a listed prefix.
- `unchanged_paths`: alias behavior of `forbidden_paths`.
- `required_changed`: every listed path must be added or modified.
- `max_changed_files`: at most `value` files may change.
- `final_contains`: final message must match `pattern`.
- `final_not_contains`: final message must not match `pattern`.
- `ledger_min_records`: the arm's isolated Prompt Forge ledger must contain at
  least `value` records.
- `ledger_max_records`: the arm's isolated Prompt Forge ledger must contain at
  most `value` records.

Checks are declared before execution. Do not reinterpret a failed check after
seeing the output.

Each check defaults to `category: "outcome"`. Use `category: "diagnostic"` for a
process requirement that should not inflate or depress first-pass usability.
Use `applies_to_arms: ["arm-id"]` when a requirement belongs to only one arm.
Outcome checks alone decide `first_pass_ok`; diagnostics decide `process_ok`.

## Run

```bash
python3 scripts/ab_eval.py run \
  --manifest ab/manifest.json \
  --out ab/results
```

Use `--dry-run` first to validate paths and inspect the plan. The output directory
must not already exist, which prevents accidental overwrites. Each run creates:

- `results.json` and `results.csv`;
- `report.md`;
- the exact prompt, final message, JSONL events, stderr, workspace, and check
  results for every arm;
- an isolated per-arm ledger so evaluation prompts do not pollute personal
  preferences. It lives under the arm workspace's `.prompt-forge/`, outside the
  user's real ledger and excluded from workspace-diff checks.

Use `--task TASK_ID` one or more times to run a focused subset without rewriting
the manifest. Keep the full suite for a decision; the filter is for debugging.

If parsing logic changes after a run, rebuild metrics and reports from preserved
events without rerunning the model:

```bash
python3 scripts/ab_eval.py recompute --run-root ab/results/RUN_ID
```

## Metrics

- `first_pass_ok`: all checks pass in the first completed run.
- `check_error_rate`: failed checks divided by total checks.
- `rework_rounds`: failed agent commands before the turn ended. This is a
  self-repair proxy, not a human correction count.
- `scope_incidents`: failed path-scope checks.
- `constraint_incidents`: failed final-message constraint checks.
- `elapsed_seconds`, input tokens, cached input tokens, and output tokens.

Use at least three representative tasks before making a superiority claim.
Report per-task regressions, not only an aggregate. A task with a safety or
authority incident vetoes a candidate win regardless of speed.
