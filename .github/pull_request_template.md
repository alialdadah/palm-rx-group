## What changed

<!-- One or two sentences. What does this PR add or fix? -->

## Why

<!-- The problem this solves or the goal it moves forward. -->

Closes #

## Type of change

- [ ] New models / feature
- [ ] Bug fix
- [ ] New store onboarding
- [ ] Docs only
- [ ] Config / tooling

## How it was tested

<!-- Commands run and results. Paste the dbt build summary line, e.g. "PASS=42 WARN=0 ERROR=0". -->

- [ ] `dbt build --select state:modified+` passes
- [ ] New models have primary key tests (`unique`, `not_null`)
- [ ] New business logic has a unit test
- [ ] Row counts / reconciliation checked where relevant

## Checklist

- [ ] Follows the naming and layer rules in `CONTRIBUTING.md`
- [ ] Staging models match the store contract (same columns, types, order)
- [ ] Docs / model descriptions updated
- [ ] No real data or credentials committed

## Notes for the reviewer

<!-- Anything to look at closely, known limitations, or follow-up issues. -->
