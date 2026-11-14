# Sakila → SQLite Analytics Sync

An ORM-driven data sync that reads the **Sakila** operational database (MySQL 8.0) and loads a
star-schema **analytics database** (SQLite). All reads and writes go through SQLAlchemy ORM
models — the project contains no hand-written SQL for data access.

---

## 1. Language, ORM, and versions

| Component | Version |
|---|---|
| Language | Python 3.13.5 |
| ORM | SQLAlchemy 2.1.8 (declarative, `Mapped` / `mapped_column` style) |
| MySQL driver | PyMySQL 1.2.4 |
| Config | python-dotenv 1.2.4 |
| Tests | pytest 9.2.0 |
| Source DB | MySQL 8.0, official Sakila sample database |
| Target DB | SQLite 3.45.3 (single file, `analytics.db`) |
| Package manager | [uv](https://docs.astral.sh/uv/) (a `requirements.txt` is also provided) |

---

## 2. Setup

### 2.1 Prerequisites

- MySQL 8.0 running locally with the **Sakila** sample database loaded
- Python 3.13+

### 2.2 Install dependencies

With `uv` (recommended — reproduces the exact locked versions):

```bash
uv sync
```

Or with plain `pip`:

```bash
python -m venv .venv
source .venv/bin/activate       
pip install -r requirements.txt
```

>
> ```bash
> UV_PROJECT_ENVIRONMENT=~/.venvs/assignment4 uv sync
> ln -s ~/.venvs/assignment4 .venv
> ```

### 2.3 Configure credentials

All connection settings are read from environment variables. Copy the template and fill in your
own values — **`.env` is git-ignored and must never be committed.**

```bash
cp .env.example .env
```

| Variable | Purpose | Example |
|---|---|---|
| `MYSQL_HOST` | MySQL host | `localhost` |
| `MYSQL_PORT` | MySQL port | `3306` |
| `MYSQL_USER` | MySQL user | `root` |
| `MYSQL_PASSWORD` | MySQL password | *(your password)* |
| `MYSQL_DB` | Source database name | `sakila` |
| `SQLITE_PATH` | Path to the SQLite target file | `analytics.db` |

`src/config.py` builds both engines from these variables and raises a clear error if a required
one is missing. No credential appears anywhere in the source code.

### 2.4 Create the test database

The automated tests mutate source data (they insert an actor, return a rental, move a customer's
address), so they run against a **separate copy** of Sakila named `sakila_test`. Create it once:

```bash
mysql -u root -p -e "CREATE DATABASE sakila_test"
mysqldump -u root -p --set-gtid-purged=OFF --routines --triggers sakila | mysql -u root -p sakila_test
```

> `--set-gtid-purged=OFF` is required on MySQL 8 with GTIDs enabled; without it the import fails
> with `@@GLOBAL.GTID_PURGED cannot be changed`.

---

## 3. Running the commands

```bash
uv run python -m src.cli <command>
```

Every command prints a human-readable message and exits **0 on success, non-zero on failure**.

| Command | What it does |
|---|---|
| `init` | Creates `analytics.db` and all analytics tables from the ORM models, verifies the MySQL connection, and seeds `dim_date` (2005-01-01 … 2006-12-31) and `sync_state` (15 rows, one per source table, all at the Unix epoch). |
| `full-load` | Reads every relevant Sakila table, transforms it, and loads dimensions → bridges → facts inside one transaction. Rerunnable: it clears the fact/bridge/dimension tables first, so it never creates duplicates. Finishes by writing the starting markers into `sync_state`. |
| `incremental` | Reads the markers from `sync_state`, queries only Sakila rows with `last_update >= marker`, upserts them (dimensions → bridges → facts) in one transaction, and advances the markers. |
| `validate [--from YYYY-MM-DD] [--to YYYY-MM-DD]` | Compares counts and totals between MySQL and SQLite, and checks for duplicate natural keys and orphan fact rows. Defaults to the 30 days ending on the **latest payment date in Sakila** (not today's date, because Sakila's data ends in February 2006). |

### Typical first run

```bash
uv run python -m src.cli init
uv run python -m src.cli full-load
uv run python -m src.cli validate
```

### Example output

```
$ uv run python -m src.cli full-load
[INFO] full-load done: 1000 films, 200 actors, 599 customers, 16044 rentals, 16044 payments
[INFO] full-load completed successfully.

$ uv run python -m src.cli validate
[INFO] Validation window: 2006-01-15 .. 2006-02-14
[INFO] Validation passed: rentals=182 payments=182 amount=514.18 (window 2006-01-15..2006-02-14)
[INFO]   store 1: payments=92 amount=243.10
[INFO]   store 2: payments=90 amount=271.08
[INFO] validate completed successfully.

$ uv run python -m src.cli validate --from 2005-01-01 --to 2006-12-31
[INFO] Validation passed: rentals=16044 payments=16044 amount=67406.56 (window 2005-01-01..2006-12-31)
[INFO]   store 1: payments=7923 amount=33679.79
[INFO]   store 2: payments=8121 amount=33726.77
```

On failure the command reports every problem it found and exits 1:

```
[ERROR] VALIDATION FAILED: Store 1 payment count mismatch: source=7923 target=7922
[ERROR] VALIDATION FAILED: Store 2 payment amount mismatch: source=33726.77 target=33732.76
[ERROR] validate failed: 4 validation check(s) failed
```

---

## 4. Running the tests

```bash
uv run pytest tests/test_sync.py -v
```

```
tests/test_sync.py::test_init_creates_all_tables PASSED                  [ 20%]
tests/test_sync.py::test_full_load_copies_all_data PASSED                [ 40%]
tests/test_sync.py::test_incremental_new_data PASSED                     [ 60%]
tests/test_sync.py::test_incremental_updates PASSED                      [ 80%]
tests/test_sync.py::test_validate_pass_and_catch_mismatch PASSED         [100%]
============================== 5 passed in 14.65s ==============================
```

| Test | What it asserts |
|---|---|
| `test_init_creates_all_tables` | All 11 analytics tables exist; `dim_date` is populated; `sync_state` has exactly 15 rows. |
| `test_full_load_copies_all_data` | Row counts in `dim_film`, `dim_actor`, `fact_rental`, `fact_payment` each equal their Sakila source table. |
| `test_incremental_new_data` | A newly inserted actor appears in `dim_actor` after `incremental`. |
| `test_incremental_updates` | (a) Returning a rental fills in `date_key_returned` and `rental_duration_days`. (b) Moving a customer's address to a new city updates `dim_customer.city`, even though `customer.last_update` never changed. |
| `test_validate_pass_and_catch_mismatch` | `validate` passes on consistent data and raises when a fact row is deleted. |

**Test isolation.** A session-scoped `autouse` fixture points `MYSQL_DB` at `sakila_test` and
`SQLITE_PATH` at a throwaway temp file that is deleted afterwards. Tests 3 and 4 record an undo
action for every source row they touch and replay it during teardown, so `sakila_test` is
byte-for-byte identical before and after a run, and the real `sakila` database is never opened.

**Test evidence.** Captured screenshots and logs of all five tests running, together with the
output of each CLI command (`init`, `full-load`, `incremental`, `validate`) and the source
citations, are in **[`Testing_Result.docx`](Testing_Result.docx)** at the repository root.

---

## 5. Analytics schema (ER diagram)

```
                            ┌──────────────┐
                            │   dim_date   │
                            │  date_key PK │
                            └──────┬───────┘
          date_key_rented ┌────────┼────────┐ date_key_paid
          date_key_returned│        │        │
                           │        │        │
┌──────────────┐    ┌──────▼────────▼──┐    ┌▼─────────────────┐    ┌──────────────┐
│   dim_film   │◄───┤   fact_rental    │    │   fact_payment   ├───►│  dim_store   │
│  film_key PK │    │ fact_rental_key  │    │ fact_payment_key │    │ store_key PK │
│  film_id  UQ │    │ rental_id     UQ │    │ payment_id    UQ │    │ store_id  UQ │
│  title       │    │ date_key_rented  │    │ date_key_paid    │    │ city         │
│  rating      │    │ date_key_returned│    │ customer_key  FK │    │ country      │
│  length      │    │ film_key      FK │    │ store_key     FK │    └──────▲───────┘
│  language    │    │ store_key     FK ├───►│ staff_id         │           │
│  release_year│    │ customer_key  FK │    │ amount           │           │
│  last_update │    │ staff_id         │    └────────┬─────────┘           │
└───▲──────▲───┘    │rental_duration_days│           │                     │
    │      │        └─────────┬──────────┘           │                     │
    │      │                  │                      │                     │
    │      │                  └──────────┬───────────┘                     │
    │      │                             ▼                                 │
    │      │                   ┌──────────────────┐                        │
    │      │                   │   dim_customer   │                        │
    │      │                   │  customer_key PK │                        │
    │      │                   │  customer_id  UQ │                        │
    │      │                   │  first_name      │                        │
    │      │                   │  last_name       │                        │
    │      │                   │  active          │                        │
    │      │                   │  city / country  │                        │
    │      │                   └──────────────────┘                        │
    │      │                                                               │
    │      └───────────────────────┐                     ┌─────────────────┘
    │                              │                     │
┌───┴──────────────┐   ┌───────────▼──────────┐          │
│ bridge_film_actor│   │ bridge_film_category │          │
│  film_key     PK │   │  film_key         PK │          │
│  actor_key    PK │   │  category_key     PK │          │
└───────┬──────────┘   └───────────┬──────────┘          │
        │                          │                     │
┌───────▼──────┐          ┌────────▼───────┐    ┌────────┴────────┐
│  dim_actor   │          │  dim_category  │    │   sync_state    │
│ actor_key PK │          │ category_key PK│    │ table_name   PK │
│ actor_id  UQ │          │ category_id UQ │    │ last_update     │
│ first_name   │          │ name           │    └─────────────────┘
│ last_name    │          │ last_update    │
│ last_update  │          └────────────────┘
└──────────────┘
```

**Key conventions**

- `*_id` = **natural key**, the original Sakila identifier (e.g. `film_id = 141`).
- `*_key` = **surrogate key**, an auto-increment integer assigned by SQLite.
- Dimensions are **Type 1**: a change in the source overwrites the existing row; no history is kept.
- `date_key` is `YYYYMMDD` as an integer (`2005-07-06` → `20050706`).
- `day_of_week` uses ISO numbering (Monday = 1 … Sunday = 7); `is_weekend` is 1 for Saturday and Sunday.
- An unreturned rental has `date_key_returned = NULL` and `rental_duration_days = NULL`.
- Sakila's `payment` table has no store column. Each payment is attributed to the store holding the
  rented copy (`payment → rental → inventory → store`); payments with no rental fall back to the
  store of the staff member who took the payment.
- `sync_state` holds one row per source table with the most recent `last_update` processed.

---

## 6. Indexes and why each one exists

All indexes are declared on the ORM models in `src/models_target.py` (via `mapped_column(unique=…,
index=…)`) and created by `TargetBase.metadata.create_all()` — no raw DDL.

### 6.1 Unique indexes on natural keys

Every upsert begins with a lookup by natural key:

```python
obj = session.scalar(select(model).where(natural_key_col == natural_key_val))
```

Without an index this is a full table scan on every row processed; an incremental run performs
thousands of such lookups. The `UNIQUE` property additionally guarantees a rerun can never create a
second row for the same source record.

| Index | Table | Column | Purpose |
|---|---|---|---|
| `ix_dim_film_film_id` | `dim_film` | `film_id` | Upsert lookup; enforces one row per Sakila film |
| `ix_dim_actor_actor_id` | `dim_actor` | `actor_id` | Upsert lookup; enforces one row per actor |
| `ix_dim_category_category_id` | `dim_category` | `category_id` | Upsert lookup; enforces one row per category |
| `ix_dim_store_store_id` | `dim_store` | `store_id` | Upsert lookup; enforces one row per store |
| `ix_dim_customer_customer_id` | `dim_customer` | `customer_id` | Upsert lookup; enforces one row per customer |
| `ix_fact_rental_rental_id` | `fact_rental` | `rental_id` | Upsert lookup; prevents duplicate rentals on rerun |
| `ix_fact_payment_payment_id` | `fact_payment` | `payment_id` | Upsert lookup; prevents duplicate payments on rerun |

### 6.2 Indexes on fact-table date keys

Date-ranged aggregation is the most common analytics query, and `validate` itself filters on these
columns on every run.

| Index | Table | Column | Purpose |
|---|---|---|---|
| `ix_fact_rental_date_key_rented` | `fact_rental` | `date_key_rented` | Range scans for "rentals between X and Y" |
| `ix_fact_rental_date_key_returned` | `fact_rental` | `date_key_returned` | Return-date analysis; also isolates the `NULL` (not-yet-returned) rows |
| `ix_fact_payment_date_key_paid` | `fact_payment` | `date_key_paid` | Revenue by day/month/quarter; used by `validate`'s windowed totals |

### 6.3 Indexes on fact-table dimension keys

These support the joins from facts back to dimensions in every star-schema query.

| Index | Table | Column | Purpose |
|---|---|---|---|
| `ix_fact_rental_film_key` | `fact_rental` | `film_key` | Join to `dim_film`; "rentals per film" |
| `ix_fact_rental_store_key` | `fact_rental` | `store_key` | Join to `dim_store`; store performance |
| `ix_fact_rental_customer_key` | `fact_rental` | `customer_key` | Join to `dim_customer`; per-customer behaviour |
| `ix_fact_payment_customer_key` | `fact_payment` | `customer_key` | Join to `dim_customer`; revenue per customer |
| `ix_fact_payment_store_key` | `fact_payment` | `store_key` | Join to `dim_store`; **used by `validate`'s per-store totals** |

Primary keys (`dim_date.date_key`, every `*_key`, `sync_state.table_name`) are indexed
automatically by SQLite and are not listed above.

---

## 7. How the sync works

### 7.1 Full load (`full_load`)

1. Read all 15 source tables in one MySQL session and build in-memory lookup dictionaries
   (`language`, `city`, `country`, `address`, `inventory`, `staff`) to avoid N+1 queries.
2. In a **single SQLite transaction**: clear the fact, bridge, and dimension tables (`dim_date` and
   `sync_state` are preserved), then write **dimensions → flush → bridges → facts** in that order.
   The `flush()` is what assigns the surrogate `*_key` values, which the bridges and facts need.
3. Record the maximum `last_update` per source table into `sync_state`.

Clearing-and-reloading is what makes `full-load` rerunnable without duplicates.

### 7.2 Incremental (`incremental`)

1. Read the markers from `sync_state`.
2. For each source table, select rows with **`last_update >= marker`**. `>=` (rather than `>`)
   guarantees that a row edited in the same second as the marker is never skipped — MySQL
   `TIMESTAMP` has only one-second resolution. The cost is that boundary rows are re-read on every
   run, which is harmless because every write is an upsert.
3. **Propagate related-table changes.** A denormalised dimension can go stale without its own row
   changing, so the job explicitly pulls in the affected rows:

   | Source table that changed | Rows that must be refreshed | Why |
   |---|---|---|
   | `address`, `city`, `country` | `dim_customer`, `dim_store` | They store `city` / `country` denormalised |
   | `language` | `dim_film` | `dim_film` stores the language *name* |
   | `inventory` | `fact_rental` | `inventory` carries `film_id` and `store_id` |
   | `staff` | `fact_payment` (rows with no rental) | Those payments take the staff member's store |

4. In a **single SQLite transaction**, upsert **dimensions → bridges → facts**, extending `dim_date`
   first if a new date appears.
5. Advance each marker to `max(latest last_update in this batch, previous marker)`, so a marker can
   never move backwards. Markers are advanced only from rows that genuinely changed, not from rows
   pulled in by propagation.

### 7.3 Validation (`validate`)

14 checks in four groups:

| Group | Checks | Scope |
|---|---|---|
| Totals, source vs target | rental count, payment count, payment amount (±$0.01) | Date window |
| Per-store totals | payment count and amount per store (±$0.01) | Date window |
| Duplicate natural keys | `fact_rental`, `fact_payment`, `dim_film`, `dim_customer` | Whole table |
| Orphan facts | 5 fact→dimension key checks | Whole table |

Per-store checking matters because a **global total is blind to mis-attribution**: moving one
payment from store 1 to store 2 leaves the overall sum unchanged. Store attribution is the most
error-prone transformation in this pipeline, so it is checked separately. The source side resolves
a payment's store with exactly the same rule the ETL uses, so the two sides are always comparable.

All failures are collected and reported together rather than aborting on the first one.


## 8. Project layout

```
assignment4/
├── README.md
├── Testing_Result.docx           # test evidence: screenshots, logs, command output, citations
├── pyproject.toml / uv.lock      # dependency definition (uv)
├── requirements.txt              # same dependencies for pip
├── .env.example                  # credential template (no real secrets)
├── .gitignore
├── src/
│   ├── config.py                 # env vars → two engines, two session factories
│   ├── models_source.py          # ORM models for 15 Sakila tables
│   ├── models_target.py          # ORM models for the 11 analytics tables + indexes
│   ├── sync.py                   # init / full_load / incremental / validate
│   └── cli.py                    # argparse entry point, logging, exit codes
└── tests/
    └── test_sync.py              # the five automated tests
```

Two separate ORM sessions are used throughout: `SourceSession` (bound to MySQL, read-only) and
`TargetSession` (bound to SQLite). They are never mixed.
