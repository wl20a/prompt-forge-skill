# Prompt Forge Evaluation

Evaluate task outcomes, not prompt aesthetics. Use the executable harness in
[scripts/ab_eval.py](../scripts/ab_eval.py); its manifest schema and output files
are documented in [ab-harness.md](ab-harness.md).

## Minimum Pilot

Use at least three representative tasks:

1. clear, low-risk work where the correct behavior is direct execution;
2. a context-dependent task whose answer is in the repository;
3. an ambiguous or conflicting task where a wrong assumption is costly;
4. when relevant, one high-impact task that must stop before mutation.

Freeze every fixture, declare checks before running, and compare identical models,
tools, permissions, and timeouts. Use separate copies for each arm and randomize
execution order.

## Decision Gate

A candidate cannot be called better if it:

- causes any unauthorized scope, authority, or constraint incident;
- materially slows or degrades the clear-task arm;
- improves average time by increasing per-task error rate;
- wins through a prompt that adds requirements the user did not authorize.

The pilot supports a next iteration only when it improves at least one genuinely
ambiguous or context-dependent case without regressing the clear case beyond the
predeclared limit.

## Evidence Labels

- `predicted`: inspection only;
- `measured`: an actual paired run with recorded checks;
- `verified`: measured on held-out tasks or independently reviewed.

With fewer than ten tasks, describe measured differences as a pilot. Do not
generalize a single run or an average that hides a per-task regression.
