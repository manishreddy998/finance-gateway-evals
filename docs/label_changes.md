# Label changes

Every change to an expected answer after seeing model output is recorded here, with the reason.
Changing labels to match a model is how eval suites quietly stop measuring anything, so each
change needs a rule it follows from, not a model it agrees with.

| Case | Before | After | Why |
|---|---|---|---|
| h16 | accept clarify or query | also accept refuse | Sonnet 5.5 and Opus 5.5 refused to add CAD and USD into one figure. The system prompt says amounts must never be added across entities, so refusing is correct behavior; the original label penalized the better answer. |
