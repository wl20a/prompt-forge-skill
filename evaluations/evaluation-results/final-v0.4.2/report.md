# A/B report: prompt-forge-v042-final

Run root: `/home/gongyuhan/Documents/Codex/2026-10-24/prompt-forge-skill/work/ab-harness/results-v042-fair/20261025T033547Z-03e90e`

| Task | Arm | First pass | Outcome checks | Process checks | Error rate | Seconds | Rebuild | Scope | Constraints |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ambiguous-secure-prompt | direct | no | 3/5 | 0/0 | 40.00% | 15.71 | 0 | 0 | 2 |
| ambiguous-secure-prompt | prompt-forge | yes | 5/5 | 1/1 | 0.00% | 37.08 | 0 | 0 | 0 |
| clear-report-fix | direct | yes | 4/4 | 0/0 | 0.00% | 18.08 | 0 | 0 | 0 |
| clear-report-fix | prompt-forge | yes | 4/4 | 1/1 | 0.00% | 18.23 | 0 | 0 | 0 |

`Rebuild` is the number of failed agent commands before the turn ended;
it is a self-repair proxy, not a count of human correction rounds.
A one-task comparison is a smoke test, not evidence of general improvement.
