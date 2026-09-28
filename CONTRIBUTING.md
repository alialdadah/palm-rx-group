# Contributing

How work gets done in this repo. The goal: every change is small, tested, reviewed and traceable.

## Workflow

1. **Open an issue** describing the change.
2. **Create a branch** from `main`:
   - `feature/<issue#>-short-name` — new models, scripts, features (`feature/12-store-b-staging`)
   - `fix/<issue#>-short-name` — bug fixes
   - `docs/<issue#>-short-name` — documentation only
   - `chore/<issue#>-short-name` — config, tooling, dependencies
3. **Commit** with short, imperative messages: `Add Store B staging models`, not `added stuff`.
4. **Open a pull request** using the PR template, with `Closes #<issue#>` in the description.
5. **Merge** only when CI passes. Squash-merge to keep `main` history clean.

No direct pushes to `main`.

## dbt conventions

### Layers

| Layer | Prefix | Reads from | Purpose |
|---|---|---|---|
| Staging | `stg_<store>__<entity>` | `source()` only | Rename, cast, standardize units. One model per raw table. No joins. |
| Intermediate | `int_<entity>__<verb>` | Staging, other intermediate | Unions, mapping, matching, flattening. |
| Marts | `dim_`, `fct_`, `mart_` | Intermediate, staging | Business-ready tables for reporting. |

- `source()` is only ever used in staging.
- Marts never read directly from raw data.

### The store contract

Every store's staging models must output the **same standard columns** (names, types, order) defined in `staging/_template/`. The intermediate union models enforce this with dbt model contracts. If a store can't provide a column, output it as `null` — never drop it.

### Naming and units

- `snake_case` for everything.
- Keys end in `_id`, dates in `_date`, timestamps in `_at`, money in `_amount`, booleans start with `is_` or `has_`.
- Money is always **CAD dollars** as `number(12,2)` — convert cents in staging (`cents_to_dollars`).
- Quantities are always **units**, not packs — convert in staging (`packs_to_units`).
- Drugs are identified by **DIN**. Local item codes are mapped, and unmapped codes are flagged, never dropped.

### SQL style

- CTEs over subqueries: import CTEs at the top, logic in the middle, a final `select` at the bottom.
- No `select *` in marts.
- Formatting is enforced by `sqlfluff` — run it before opening a PR.

## Testing

- Every model has a primary key tested with `unique` and `not_null`.
- Foreign keys have `relationships` tests (e.g. every fill's DIN exists in `dim_drug`).
- New business logic (PDC, unit conversion, price joins) gets a dbt unit test.
- Before opening a PR, run:

  ```bash
  dbt build --select state:modified+
  ```

## Data and secrets

- **Never commit real patient data.** All patient data in this repo is synthetic.
- **Never commit credentials.** Snowflake connection details live in `profiles.yml` or `.env`, both git-ignored.
- Generated and downloaded data files are not committed — they're reproducible from the scripts.

## Adding a new store

Follow the onboarding runbook in `docs/`. Adding a store should be a single PR.
