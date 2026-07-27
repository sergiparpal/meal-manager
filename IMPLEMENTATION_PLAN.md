# Implementation Plan — Adopting Tier 1–3 Improvements from the `KoryakovDmitry/meal-manager` Fork

**Status:** ready for implementation
**Target repo:** this repository (`sergiparpal/meal-manager`, branch `main`)
**Audience:** an autonomous coding agent (Claude Code) with no prior context on this conversation
**Human involvement:** exactly one question block at Stage 0. Everything after that runs unattended.

---

## 0. Context you need before touching anything

### 0.1 What this repository is

A meal-planning / fridge-inventory manager packaged as a Hermes plugin. Python 3.12+, **stdlib only, no external dependencies**. All state is JSON files under `data/`. Tools are auto-discovered: every non-underscore module under `src/handlers/` exporting `NAME`, `SCHEMA`, `HANDLER` is registered automatically by `src/handlers/__init__.py:iter_tools()`.

**Read `AGENTS.md` and `CLAUDE.md` before writing code.** They are authoritative on style, locking, persistence, and domain rules. This plan assumes and does not repeat them. Where this plan and those files disagree, stop and flag it rather than guessing.

### 0.2 Where these changes come from

A fork of this repo (`KoryakovDmitry/meal-manager`) diverged at commit `48ab3e4` (2026-07-05) and built a much larger product: weekly meal plans, live shopping with receipt reconciliation, a product catalog, a domain audit trail, and a FastAPI web UI. Most of that is out of scope — it would mean adopting their product rather than improving ours.

This plan ports only the parts that are genuinely better than what we have, adapted to our data model. **You do not need network access or their repository to execute this plan.** Every design decision they made that we are adopting is described in full below. If you want to inspect their code for reference it is at `https://github.com/KoryakovDmitry/meal-manager`, but the plan is self-contained without it.

Explicitly **out of scope** (do not implement, do not scaffold, do not leave TODOs for):

- Weekly meal plans, shopping requests / receipt reconciliation, product catalog, prep items
- The domain audit trail (`src/audit/`) — our `atomic_write_json` already gives write durability
- The web UI — FastAPI/uvicorn/pydantic would break the stdlib-only rule
- `JsonFileLock` (`fcntl`-based cross-process locking) — POSIX-only, and nothing today runs a second process against `data/`

### 0.3 Invariants that must survive every stage

These are load-bearing. Breaking one silently is worse than not doing the stage at all.

1. **`history_repo.load()` must keep returning `dict[str, str]`** mapping normalized dish name → ISO date string (the most recent cook per dish). `_common.days_since_last_cook()` and the whole tuning learner depend on this shape. Stage 4 rewrites the storage underneath it; the projection contract does not change.
2. **`suggestion.score_components(dish, available_ingredients, days_since_last)` must keep its signature and its `(match, recency) | None` return.** `tuning.compute_rewards()` calls it directly and blends the two terms with the learned weight `w` / `1-w`. Adding a third scoring term must not change this function (see Stage 7).
3. **`fridge_repo.load()` must keep returning `{name: count}`** where `None` = pantry staple and `0` = out of stock. Stage 7 adds a *new* method for richer entries rather than changing this one.
4. **`Dish.name` and `Dish.ingredients` keys stay normalized** (`strip().lower()`) on every construction path, enforced in `Dish.__post_init__`.
5. **Every public handler keeps the `@tool_handler(...)` decorator** — it is the single guarantee that no stack trace escapes a tool call.
6. **Tests never touch the real `data/`.** `test_integration.py` points the singletons at a `tempfile.mkdtemp()` directory via `configure()`. Any new repository singleton must be wired into `src/repositories/__init__.py:configure()` or tests will silently write to the live data directory.
7. **Existing on-disk data files must keep loading.** Every format change in this plan is backward compatible: legacy shapes are migrated in memory on load and written back in the new shape on the next write, matching the pattern already used for the legacy flat-list `fridge.json`.

### 0.4 Commands

```bash
python3 test_unit.py
```

```bash
python3 test_integration.py
```

Both are plain assertion scripts (not pytest). They exit non-zero on failure. CI (`.github/workflows/tests.yml`) runs unit then integration on Python 3.12 / 3.13 / 3.14.

Note the trap documented in `AGENTS.md`: a test that only *prints* a failure still passes CI. Use the `check(label, condition, detail)` helper that both scripts already define — it increments the failure counter and drives the exit code.

### 0.5 Stage ordering (and why it is not tier order)

The tiers in the original analysis were a value/effort ranking, not an execution order. Two reorderings are deliberate:

- **The history event log (Tier 2) runs before `list_cooking_history` (Tier 1).** Writing that tool against the old `{name: date}` dict and then rewriting it one stage later is pure waste.
- **Expiry (Tier 3) runs last.** It is the only stage that touches the scoring path, and it is the easiest to get subtly wrong.

Execution order: **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.**

---

## Stage 0 — Preflight and the single question block

### 0.a Verify a clean baseline

```bash
git status --porcelain && python3 test_unit.py && python3 test_integration.py
```

- If the worktree is dirty, **stop** and report. Do not stash, revert, or commit someone else's work.
- If either suite fails on a clean checkout, **stop** and report the failure. Do not start building on a red baseline.

Record the baseline pass counts from both suites — you will compare against them at Stage 8.

### 0.b Create the working branch

```bash
git checkout -b feat/fork-adoption-tier1-3
```

### 0.c Ask the user — one call, four questions, then keep going

Use a **single `AskUserQuestion` call containing all four questions**. This is the only human touchpoint in the plan; do not defer any of it to later stages.

If the user does not answer, or answers only some, **proceed with the option marked (Recommended)**. Do not block.

> **Q1 — Expiry scoring model** *(header: `Expiry score`)*
> How should ingredient expiry influence meal suggestions?
> - **Additive bonus outside the learned blend (Recommended)** — urgency is added after the tuner's match/recency blend. `score_components()` and the learner contract stay untouched. Lowest risk.
> - **Extend the learner to two dimensions** — the tuner learns match/recency/urgency jointly. Much larger change to `src/tuning.py`; the candidate grid becomes 2D.
> - **Store expiry but do not score it** — persist and surface `expires_on` in `list_fridge` / `get_meal_suggestions`, but leave ranking alone.
>
> **Q2 — `history.json` migration** *(header: `Migration`)*
> How should the legacy `{dish: date}` history file become an event log?
> - **Lazy, in-memory on load; written back on the next write (Recommended)** — mirrors how legacy flat-list `fridge.json` is already handled. No migration step for the user.
> - **Explicit one-shot migration script under `scripts/`** — the user runs it once; the repository refuses the legacy shape afterwards.
>
> **Q3 — Commit granularity** *(header: `Commits`)*
> - **One commit per stage (Recommended)** — seven or eight focused commits, each with green tests.
> - **A single squashed commit at the end.**
>
> **Q4 — Read-side tool surface** *(header: `Tool surface`)*
> This plan adds five tools (21 → 26): `set_dish_instructions`, `get_dish_recipe`, `list_cooking_history`, `merge_ingredient_alias`, `list_ingredient_aliases`.
> - **Add all five (Recommended)** — every writable piece of state gets a read path.
> - **Skip `list_ingredient_aliases`** — keep the surface at 25; aliases are visible only through their effect.

Record the answers at the top of your working notes. Q1 and Q4 change what you build; Q2 and Q3 change how.

---

## Stage 1 — Reject unknown tool arguments

**Problem.** If the model calls `add_dish` with `dish_name` instead of `name`, or `update_fridge_inventory` with `qty` instead of a count, the unknown key is **silently ignored**. `require_arg` then raises about the *missing* key, or worse the handler proceeds with defaults and does something the user did not ask for. There is no signal that the caller's mental model was wrong.

**Approach.** Validate argument keys against the handler's own `SCHEMA["properties"]`. Deriving the allowed set from the schema — rather than hand-listing it per handler — means the check can never drift from the declared interface.

### 1.1 Extend the decorator in `src/handlers/_common.py`

Change `tool_handler` to accept the schema:

```python
def tool_handler(name: str, schema: dict | None = None, *, extra_args: set[str] | None = None):
```

- Compute the allowed key set **once at decoration time**, not per call: `allowed = set(schema.get("properties", {})) | (extra_args or set())` when `schema` is not None, else `None`.
- When `allowed` is not `None`, validate `args` **inside the existing `try` block**, before calling `fn`. This matters: validation errors must come back through the normal `{"error": ...}` envelope, not as an exception escaping the wrapper.
- `schema=None` keeps the current unvalidated behaviour, so the decorator stays backward compatible.

Add the standalone helper too (handlers or future code may want it directly):

```python
def reject_unknown_args(args: dict, allowed: set[str]) -> None:
    if not isinstance(args, dict):
        raise ValueError("tool arguments must be an object")
    unknown = set(args) - allowed
    if unknown:
        raise ValueError(f"unknown arguments: {sorted(unknown)}")
```

Have the decorator call this helper rather than reimplementing the check.

**Scope note:** this validates the `args` dict only. The `**kwargs` that handlers receive from the host are a separate channel and must not be touched.

### 1.2 Update all 21 handler call sites

Change every `@tool_handler(NAME)` to `@tool_handler(NAME, SCHEMA)` across `src/handlers/*.py`. `SCHEMA` is defined above `HANDLER` in every module, so the reference resolves at decoration time. Verify with:

```bash
grep -rn "@tool_handler" src/handlers/ | grep -v "SCHEMA"
```

That must return nothing when the stage is complete.

### 1.3 Handle handlers that legitimately accept undeclared keys

Some handlers may read a key that is not in `SCHEMA["properties"]`. Find them:

```bash
grep -rn 'args\.get(\|require_arg(args' src/handlers/*.py
```

For each hit, confirm the key appears in that module's `SCHEMA["properties"]`. If a handler genuinely needs an undeclared key, prefer **adding it to the schema** (the schema is the tool's public interface and should be honest). Use `extra_args={...}` only when the key must stay undocumented, and comment why.

### 1.4 Tests

In `test_unit.py`, add `test_reject_unknown_args()` covering: empty-unknown passes; a single unknown key raises `ValueError` naming it; a non-dict `args` raises; `extra_args` widens the allowed set. Register it in `main()`.

In `test_integration.py`, add `test_unknown_argument_rejected()`: call a real handler (e.g. `list_fridge` or `add_dish`) with a bogus key, parse the returned JSON, and assert `"error"` is present and the message contains the bogus key name. Register it in `main()` alongside the other handler tests.

### 1.5 Done when

- `python3 test_unit.py` and `python3 test_integration.py` both pass with counts ≥ baseline.
- No `@tool_handler(NAME)` single-argument call sites remain.
- Commit: `Reject unknown tool arguments against each handler's schema`

---

## Stage 2 — Sanitize the error envelope

**Problem.** `tool_handler`'s `except` returns `{"error": str(exc)}` for every exception. For `ValueError` and `LookupError` — which handlers raise deliberately with user-facing text — that is correct and useful. For `OSError`, it leaks absolute filesystem paths, and for a `json.JSONDecodeError` it leaks byte offsets into file contents. Both go straight into the LLM's context and the user's chat.

### 2.1 Change the `except` in `src/handlers/_common.py`

Keep `log.exception(...)` exactly as-is for **every** exception — full detail must stay in the logs. Only the returned message changes:

- `ValueError`, `LookupError`, `KeyError` → keep `str(exc)` (deliberate, user-facing).
- `OSError` (covers `FileNotFoundError`, `PermissionError`, disk-full, …) → `"Storage is temporarily unavailable"`.
- `json.JSONDecodeError` → `"Stored data could not be read"`.
- Anything else → `"An internal error occurred"`. This is the deliberate default: an unanticipated exception type is exactly the case where `str(exc)` is most likely to carry something we did not mean to publish.

Note that `json.JSONDecodeError` subclasses `ValueError`, so **order the `isinstance` checks with `JSONDecodeError` before `ValueError`** or it will never match.

Write the mapping as a small module-level helper (`_safe_error_message(exc) -> str`) rather than a chain inside the decorator, so it is unit-testable without going through a handler.

### 2.2 Tests

`test_unit.py`: `test_safe_error_message()` — one assertion per branch above, including the `JSONDecodeError`-before-`ValueError` ordering.

`test_integration.py`: extend an existing not-found test (or add one) to assert that a `LookupError` still surfaces its real message, so the sanitization does not over-reach.

### 2.3 Done when

- Both suites pass.
- A deliberate `ValueError` from a handler is still visible verbatim in the envelope.
- Commit: `Sanitize internal exceptions in the tool error envelope`

---

## Stage 3 — Cooking instructions on recipes

**Gap.** The catalog knows *what a dish contains* but not *how to cook it*. This is the most obvious missing feature in a meal manager, and the port is nearly literal.

### 3.1 Extend `Dish` in `src/dish.py`

Add a module constant `MAX_INSTRUCTIONS_LENGTH = 20_000` and a field:

```python
instructions: str | None = None
```

The field must come **after** `ingredients` so existing positional construction (`Dish(name=..., ingredients=...)`) is unaffected.

In `__post_init__`, after the existing name/ingredient normalization, validate:

- `None` stays `None`.
- Non-`str` → `raise ValueError("instructions must be a string or null")`.
- Strip it; if the result exceeds `MAX_INSTRUCTIONS_LENGTH` → raise. Check length **after** stripping.
- An empty string after stripping normalizes to `None` — "cleared" and "never set" are the same state, and letting both exist would mean two representations of one thing.

In `to_dict()`, emit `"instructions"` **only when it is not `None`**. This keeps every existing `dishes.json` row byte-identical after a round-trip, so this stage causes no diff churn in the data file.

In `from_dict()`, read `data.get("instructions")` and pass it to the constructor. Keep `from_dict` permissive in spirit — but note that `__post_init__` will now raise on a malformed `instructions` value. That is acceptable and consistent: `JsonDishRepository._parse()` already isolates per-row parse failures and preserves the raw rows (see `json_dish.py`), so one bad row is flagged rather than dropping the catalog.

### 3.2 Confirm existing dish handlers preserve the field

- `src/handlers/edit_dish.py` mutates `dish.ingredients` on a loaded instance, so `instructions` survives. **Verify this by reading the code**, and add a test rather than assuming.
- `src/handlers/add_dish.py` constructs `Dish(name=name)` then calls `add_ingredient` in a loop. Optionally accept an `instructions` argument here; if you do, add it to that module's `SCHEMA["properties"]` (Stage 1 now enforces that).
- `src/handlers/add_dishes_batch.py` — check whether it builds dishes via `from_dict` or direct construction, and keep it consistent with `add_dish`.

### 3.3 New tool `src/handlers/set_dish_instructions.py`

- `NAME = "set_dish_instructions"`.
- Schema: `dish_name` (string, required), `instructions` (`{"type": ["string", "null"]}`, required). Description must state the 20,000-character cap and that `null`/blank clears.
- Handler: `require_arg` for `dish_name`; for `instructions` check `"instructions" not in args` explicitly and raise — it must be *present*, but `None` is a legal value, so `require_arg`'s truthiness-free `in` check is what you want (it already uses `key not in args`, so `require_arg` is fine here too; pick one and be consistent).
- Normalize the dish name with `_common.normalize_dish_name`.
- Under `dish_repo.lock`: load, find by `dish.name == name` (names are already normalized — do **not** re-`strip().lower()`), raise `LookupError` if absent, assign, save.
- Validate through `Dish` rather than duplicating the length check: construct a throwaway `Dish(name=dish.name, ingredients=dish.ingredients, instructions=args["instructions"])` and copy the validated `.instructions` across. That keeps the rule in exactly one place.
- Return `{"dish_name":…, "instructions":…, "cleared": bool}`.

### 3.4 New tool `src/handlers/get_dish_recipe.py`

- `NAME = "get_dish_recipe"`. Argument: `dish_name` (required).
- Returns the full recipe: name, ingredients split into essential/optional lists, and `instructions`. Lock-free read (`dish_repo.load()`), consistent with the other read-only tools.
- `LookupError` when the dish is not in the catalog.

### 3.5 Tests

`test_unit.py`:
- `instructions=None` round-trips and `to_dict()` omits the key entirely.
- A whitespace-only string normalizes to `None`.
- Over-length input raises `ValueError`.
- Non-string input raises `ValueError`.
- `from_dict(to_dict(dish))` preserves instructions.

`test_integration.py`:
- `set_dish_instructions` then `get_dish_recipe` returns the text.
- Clearing with `null` works and `get_dish_recipe` reports `None`.
- **`edit_dish` on a dish with instructions preserves them** — this is the regression that would otherwise slip through.
- `set_dish_instructions` on an unknown dish returns an error envelope.

### 3.6 Done when

- Both suites pass; tool count is 23.
- An existing `dishes.json` round-trips with no diff when no instructions are set.
- Commit: `Add cooking instructions to recipes`

---

## Stage 4 — Rewrite cooking history as an append-only event log

**This is the largest and most valuable stage. Read it fully before starting.**

**Problem.** `history.json` stores exactly one date per dish. That single-value model is what forced `set_entry(..., only_if_newer=True)` into existence: without it, logging a forgotten meal from last month would overwrite this morning's cook and hand the dish straight back to the suggestion engine inside its cooldown. That flag is a patch over a modelling error.

An append-only log fixes it *by construction* — `load()` projects the maximum date per dish, so an older event simply cannot win — and unlocks things that are impossible today: how often a dish was cooked, retracting a mistaken entry instead of destroying it, and recording `backfilled` in the data rather than deciding it in the handler.

### 4.1 New module `src/history_event.py`

Pure data, no I/O, matching the style of `src/dish.py`.

```python
@dataclass
class CookingEvent:
    id: str                       # "cook_" + uuid4().hex
    dish_name: str                # normalized at construction
    cooked_on: str                # ISO date, YYYY-MM-DD
    recorded_at: str              # ISO 8601 UTC datetime, tz-aware
    backfilled: bool = False      # cooked_on != the date it was recorded
    retracted_at: str | None = None
```

We deliberately drop the fork's `time_precision`, `plan_occurrence_id`, `actual_portions`, `actual_yield_portions`, and `provenance` fields — they exist to serve the weekly-plan feature, which is out of scope.

`__post_init__` validates:
- `dish_name` normalized via `Dish.normalize_name`, non-empty.
- `id` is a non-empty string starting with `cook_`.
- `cooked_on` parses with `date.fromisoformat`.
- `recorded_at` parses with `datetime.fromisoformat` and is timezone-aware.
- `backfilled` is a real `bool`.
- `retracted_at` is `None` or a tz-aware ISO datetime.

Add:
- `active` property → `self.retracted_at is None`.
- `to_dict()` → all fields.
- `from_dict(data)` classmethod → strict; raise `ValueError` on unknown or missing keys so corruption is caught rather than absorbed.

**Naming note:** `dish_name` is a *snapshot* of the name at cook time. Renaming a dish in the catalog does not rewrite history. Document this in the class docstring.

### 4.2 Rewrite `src/repositories/json_history.py`

New on-disk shape:

```json
{"schema_version": 2, "events": [ { ... }, ... ]}
```

Add `HISTORY_SCHEMA_VERSION = 2` and a `HistoryDataError(ValueError)` for corrupt storage.

**Methods:**

| Method | Behaviour |
|---|---|
| `load_events(*, strict=False)` | Parse and migrate. On corruption: raise `HistoryDataError` if `strict`, else return `[]`. Returns events in insertion order. |
| `load()` | **Unchanged public contract.** Project active events to `{dish_name: latest_cooked_on}`, comparing with `date.fromisoformat`, never lexicographically. |
| `append_event(dish_name, cooked_on, *, backfilled=False)` | Build a `CookingEvent`, append, save, return it. Under the lock. |
| `retract_event(event_id)` | Set `retracted_at` on a matching active event; return it, or `None` if absent/already retracted. Under the lock. |
| `retract_latest_for_dish(dish_name)` | Retract the most recent active event for that dish; return it or `None`. Backs `delete_history_entry`. |
| `delete_event(event_id)` | **Hard delete.** Rollback path only — a cook that was rolled back never happened, so it must leave no trace. Distinct from retraction. |

**Remove** `set_entry`, `remove_entry`, and `revert_entry`. Do not leave compatibility shims: `only_if_newer` exists solely to work around the single-value model, and keeping a dead flag around invites someone to use it. Update every caller (Section 4.4) and `src/repositories/base.py`.

**Migration** (`_migrate(raw)`), per the answer to Q2:
- `{"schema_version": 2, "events": [...]}` → parse each event via `CookingEvent.from_dict`.
- A bare `{name: date}` dict (legacy) → synthesize one event per entry. Use a **deterministic id** — `"cook_" + uuid.uuid5(NAMESPACE, f"{name}|{date}").hex` with a fixed module-level `uuid.UUID` namespace constant — so migrating twice yields identical ids and never produces duplicates. Set `recorded_at` to the migration time, `backfilled=False`, `retracted_at=None`. Skip entries whose name or date is not a string, and lowercase names exactly as the current `load()` does.
- Anything else (a list, a scalar, unsupported `schema_version`) → treat as corrupt.
- **Default (Q2 = lazy):** migrate in memory on load and write the v2 shape on the next mutating call. `load_events()` must never write. This mirrors the existing legacy-list handling in `json_fridge.py`.
- **If Q2 = explicit script:** add `scripts/migrate_history_v2.py` that loads, converts, and atomically writes v2, and make `load_events` raise `HistoryDataError` on the legacy shape with a message naming the script.

Keep using `atomic_write_json` for every write, and keep the existing `self._lock` (`threading.Lock`) — the history repo owns its lock and callers do not hold it.

### 4.3 Update `src/repositories/base.py`

Replace the `HistoryRepository` protocol's `set_entry` / `remove_entry` / `revert_entry` with the methods in the table above. Update the docstring: history is an append-only event log projected to one date per dish on read.

### 4.4 Update the callers

**`src/handlers/register_cooked_meal.py`** — currently:
1. `history_repo.set_entry(name, cooked_iso, only_if_newer=True)` → capture `previous_history`
2. `fridge_repo.consume(essentials)`, and on failure `history_repo.revert_entry(...)`
3. `_kept_newer_entry(...)` decides the `superseded` message

Becomes:
1. Capture `projected_before = history_repo.load().get(name)` **before** appending — this is what the `superseded` message compares against.
2. `event = history_repo.append_event(name, cooked_iso, backfilled=backdated)`.
3. `fridge_repo.consume(essentials)`; on failure `history_repo.delete_event(event.id)` inside the existing `try/except` that logs rollback failures.
4. Recompute `superseded` as: `projected_before is not None and date.fromisoformat(projected_before) > cooked_on`. Delete the now-unused `_kept_newer_entry` helper.
5. Leave the tuning block **completely untouched**. It reads `history_repo.load()` indirectly through the `days_snapshot` captured at the top of the handler, and that contract is unchanged.

The user-facing message stays truthful: when `superseded` is true, say the recency cooldown is unchanged because a more recent cook is on record — which is now a statement about the projection, not about a skipped write.

**`src/handlers/delete_history_entry.py`** — swap `remove_entry` for `retract_latest_for_dish`. Raise `LookupError` when it returns `None`. Update `SCHEMA["description"]`: it retracts the most recent cook of that dish (the undo for `register_cooked_meal`) rather than erasing all history for it. This is a genuine behaviour change and the description must say so.

**`src/handlers/_common.py:days_since_last_cook()`** — no change. It calls `history_repo.load()`, whose contract is preserved. Confirm by reading it; do not edit it.

### 4.5 Tests

Move or rewrite the existing `set_entry(only_if_newer=True)` coverage in `test_unit.py` — that method no longer exists, so leaving the test would fail the build.

`test_unit.py` (against a tmp path, as the current history tests already do):
- Legacy `{name: date}` migrates to one event per entry; ids are deterministic across two migrations of the same input.
- `load()` projects the **latest** date per dish across several events.
- Appending an **older** event does not change the projection — this is the `only_if_newer` bug, now impossible by construction. Make the test name say so.
- A retracted event is excluded from `load()` but still present in `load_events()`.
- `delete_event` removes the row entirely; `load_events()` no longer returns it.
- `CookingEvent.from_dict` rejects unknown and missing keys.
- Corrupt file: `load_events(strict=True)` raises `HistoryDataError`; `load_events()` returns `[]`.

`test_integration.py`:
- `register_cooked_meal` then read `history.json` and assert `schema_version == 2` and exactly one event.
- Backdated cook records `backfilled: true` **and** does not move the projection when a newer cook exists.
- `delete_history_entry` retracts: the event survives in the file with `retracted_at` set, and `get_meal_suggestions` sees the dish as no longer recently cooked.
- Rollback: force the fridge consume to fail (monkeypatch `fridge_repo.consume` to raise) and assert the appended event is **gone** from `load_events()`, not merely retracted.

### 4.6 Done when

- Both suites pass.
- A pre-existing legacy `history.json` loads, projects correctly, and is rewritten as v2 on the next cook.
- `grep -rn "only_if_newer" .` returns hits only in `CLAUDE.md` / `AGENTS.md` / `README.md` (fixed in Stage 8), never in `src/`.
- Commit: `Store cooking history as an append-only event log`

---

## Stage 5 — `list_cooking_history` tool

**Gap.** There is no way to *read* the cooking history. `delete_history_entry` can destroy it and `register_cooked_meal` can write it, but nothing exposes it. The agent cannot answer "when did I last cook this?" except by inferring it from suggestion output.

### 5.1 New tool `src/handlers/list_cooking_history.py`

- `NAME = "list_cooking_history"`.
- Arguments, all optional: `dish_name` (string filter, normalized before comparing), `include_retracted` (boolean, default `True`), `limit` (integer 1–1000, default 100).
- Validate types explicitly — reject `bool` where an `int` is expected (`isinstance(True, int)` is `True` in Python, and `limit=True` must not slip through as `1`).
- Read `history_repo.load_events(strict=True)` so storage corruption surfaces as an error envelope rather than an empty list that reads as "you have never cooked anything".
- Iterate **newest first** (`reversed(events)`), apply filters, stop at `limit`.
- Each row: the event's `to_dict()` plus a derived `"status": "active" | "retracted"`.
- Lock-free read.
- Schema description should tell the model this is the tool for "when did I last cook X" and "how often do I make Y".

Stage 1 applies automatically: decorate with `@tool_handler(NAME, SCHEMA)`.

### 5.2 Tests

`test_integration.py`:
- Empty history returns `[]`.
- After two cooks of different dishes, both appear, newest first.
- `dish_name` filter narrows correctly and normalizes its input (`"Paella"` matches the stored `"paella"`).
- `limit` truncates.
- `include_retracted=False` hides a retracted event that `include_retracted=True` shows.
- `limit=0`, `limit=1001`, and `limit=True` all return error envelopes.

### 5.3 Done when

- Both suites pass; tool count is 24.
- Commit: `Add list_cooking_history tool`

---

## Stage 6 — Ingredient aliases

**Problem.** `"tomate"`, `"tomates"`, and `"tomate pera"` are three distinct keys. The fridge accumulates near-duplicates, and `can_cook_with` fails against a dish that spelled the ingredient differently. This is the failure mode that degrades a real fridge fastest.

**Approach.** The fork solves this with `aliases` on a structured `InventoryItem` plus a `merge_product_identity` operation. Our fridge keys *are* the identity, so we take the operational half: a **one-shot merge that rewrites existing data**, plus a persisted alias map consulted at the tool boundary so future input canonicalizes automatically. This is deliberately not a read-time projection — rewriting once is cheaper and leaves the data honest.

### 6.1 New repository `src/repositories/json_alias.py`

`JsonAliasRepository`, file `<data_dir>/aliases.json`, shape `{"alias": "canonical", ...}` — a flat lowercase map.

- `load() -> dict[str, str]`: missing/corrupt → `{}` with a `logger.warning`, matching `json_fridge.load()`. Skip non-string keys or values and empty strings after stripping.
- `save(mapping)`: `atomic_write_json`.
- `resolve(name) -> str`: **single hop.** `return mapping.get(name, name)`. Single-hop is safe because `add()` guarantees no alias ever points at another alias, so a chain cannot form. Do not write a loop — a loop invites an infinite one on hand-edited data.
- `add(alias, canonical)`: under `self.lock`, load, then:
  - Re-point any existing alias whose target is `alias` to `canonical` (so old mappings never become chains).
  - Set `mapping[alias] = canonical`.
  - Drop `canonical` from the map if it was itself an alias key.
  - Save.
- Own `self.lock = threading.Lock()`.

### 6.2 Wire it in

- `src/repositories/base.py`: add an `AliasRepository` Protocol with `lock`, `load`, `save`, `resolve`, `add`.
- `src/repositories/__init__.py`: add the `alias_repo` singleton at `_DEFAULT_DATA_DIR / "aliases.json"`, **add it to `configure()`**, and add both to `__all__`. Missing the `configure()` line means tests write to the live `data/` — see invariant 6.

### 6.3 Canonicalize at the tool boundary

In `src/handlers/_common.py`, `normalize_ingredient_name` gains alias resolution:

```python
def normalize_ingredient_name(name: str) -> str:
    return alias_repo.resolve(_normalize_label(name, label="Ingredient name"))
```

`_common` already imports `history_repo`, so importing `alias_repo` there is consistent with the existing layering.

**Do not touch `Dish.normalize_ingredient`.** The domain layer stays pure and I/O-free; only the tool boundary resolves aliases. State this in the docstring — it is the kind of asymmetry a later reader will otherwise try to "fix".

**Deadlock rule:** `normalize_ingredient_name` now acquires `alias_repo.lock`. Every handler must therefore normalize its arguments **before** acquiring any repository lock. Check the handlers you touch in 6.4 against this. Document the lock order in `AGENTS.md` at Stage 8: `alias → dish → fridge`.

### 6.4 New tool `src/handlers/merge_ingredient_alias.py`

- `NAME = "merge_ingredient_alias"`. Arguments: `from_name`, `to_name`, both required strings.
- Normalize both **first**, before any lock. Because `normalize_ingredient_name` now resolves aliases, `to_name` automatically collapses to its canonical form — which is exactly right.
- Reject `from_name == to_name` after normalization with a clear `ValueError`.
- Then, acquiring locks in the order `dish_repo.lock` → `fridge_repo.lock`:
  1. **Catalog:** for each dish containing `from_name`: if `to_name` is also present, the merged flag is `essential[from] or essential[to]` — essential wins, because demoting an essential to optional would let `can_cook_with` approve a dish the user cannot actually make. Delete the `from_name` key. Save only if something changed.
  2. **Fridge:** if only `from_name` is present, rename the key. If both are present: `None` (staple) wins over any number; otherwise sum the counts and clamp to `MAX_PORTION_COUNT`. Delete `from_name`. Save only if something changed.
  3. **Alias map:** `alias_repo.add(from_name, to_name)`.
- Return a structured summary: `{"from": …, "to": …, "dishes_updated": [names], "fridge_merged": bool, "resulting_count": …}`.
- Order matters: record the alias **last**. If a step fails partway, the alias is absent and the operation is safely repeatable. Recording it first would canonicalize `from_name` away and make the retry a no-op that silently leaves half-merged data.

### 6.5 New tool `src/handlers/list_ingredient_aliases.py` *(skip if Q4 said so)*

Returns `{"aliases": {alias: canonical}}` sorted by alias. Lock-free read. Twenty lines.

### 6.6 Tests

`test_unit.py`:
- `resolve` returns the input unchanged when unmapped.
- `add` re-points a pre-existing alias that targeted the new alias, so no chain forms.
- Corrupt/missing `aliases.json` → `{}`.

`test_integration.py`:
- Merge where only the catalog is affected; only the fridge; both.
- Essential-wins: merging an optional into an essential leaves the ingredient essential.
- Fridge count merge: `2 + 3 → 5`; staple + `3 → staple`; sum clamped at `MAX_PORTION_COUNT`.
- **After the merge, `update_fridge_inventory` with the old name writes to the canonical key** — the boundary resolution actually works end to end.
- **After the merge, `get_meal_suggestions` proposes a dish that previously failed `can_cook_with`** because of the spelling split. This is the test that proves the feature does what it claims.
- Merging a name onto itself returns an error envelope.

### 6.7 Done when

- Both suites pass; tool count is 25 or 26 depending on Q4.
- `data/aliases.json` is created lazily, never at import time.
- Commit: `Merge duplicate ingredient identities via aliases`

---

## Stage 7 — Ingredient expiry

*(If Q1 selected "Store expiry but do not score it", implement 7.1, 7.2 and 7.5 and skip 7.3/7.4. If Q1 selected the two-dimensional learner, stop and write a short design note in this file instead of implementing it — that change deserves its own plan.)*

**Note on provenance.** The fork stores `expires_on` and computes an `expiring_soon` status at `EXPIRING_SOON_DAYS = 3`, but nothing consumes it: `EXPIRING_SOON_DAYS` appears only in their `src/inventory.py` and never reaches their scoring path. We are taking the data model and adding the ranking use they left on the table.

### 7.1 Extend the fridge value grammar

`fridge.json` currently maps `name → int | null`. Extend to also accept an object:

```json
{
  "milk":  {"count": 2, "expires_on": "2026-08-01"},
  "salt":  null,
  "onion": 3
}
```

Scalars and `null` keep their exact current meaning. This is additive: existing files load unchanged, and entries without an expiry keep being written as bare scalars so the file does not churn.

In `src/repositories/json_fridge.py`:

- **`load()` keeps its contract** — `{name: count}`, expiry stripped. Invariant 3. Every existing caller (`load_set`, `consume`, `remove_items`, `restore_counts`, `list_fridge`, the DII finalizer) is untouched.
- Add **`load_entries() -> dict[str, dict]`** returning `{name: {"count": …, "expires_on": … | None}}`. This is the only new read path.
- Add **`save_entries(entries)`** which serializes back to the compact form: bare scalar/`null` when `expires_on` is `None`, object otherwise.
- Validate `expires_on` on load with `date.fromisoformat`; on failure, `logger.warning` and treat it as `None` rather than dropping the ingredient. Losing a known food item because its date was mistyped is the worse outcome.
- Reuse the existing non-finite-count guard for the `count` inside the object form — the same `NaN`/`Infinity` hazard applies there.

Add a helper alongside `is_available` / `consume_one`:

```python
EXPIRING_SOON_DAYS = 3

def expiry_status(expires_on, today):  # -> "expired" | "expiring_soon" | "fresh" | None
```

**Expired items stay available.** Do not auto-remove them and do not exclude them from `load_set()`. The date is the user's estimate, not ground truth, and silently deleting food is not a call this tool gets to make. Flag it; let the user decide.

### 7.2 Accept expiry at the tool boundary

Add `normalize_ingredient_entries(ingredients)` to `src/handlers/_common.py`, mirroring `normalize_ingredient_counts` (which stays as-is for its other callers — grep first and confirm which handlers use it, `finalize_ingredient_session` is a likely one). It accepts:

- `["a", "b"]` → one portion each, no expiry
- `{"a": 3, "salt": null}` → counts as today
- `{"milk": {"count": 2, "expires_on": "2026-08-01"}}` → full form

Keep the existing collision rule verbatim: two keys that normalize to the same name **raise**, they do not merge. Validate `expires_on` as an ISO date at the boundary and raise on a bad one — the boundary is strict even though `load()` is forgiving, which is the same asymmetry the codebase already applies elsewhere.

Update `src/handlers/update_fridge_inventory.py` to use it, and extend that module's `SCHEMA` to document the object form. Update `src/handlers/list_fridge.py` to report `expires_on` and add an `expiring_soon` list to its output.

### 7.3 Urgency as a bonus outside the learned blend

**Do not modify `score_components()` or `calculate_score()`.** Invariant 2. The learner blends exactly two terms with `w` / `1-w`; a third term inside that function would silently corrupt `tuning.compute_rewards`, which re-blends the tuple per candidate weight.

In `src/suggestion.py` add:

```python
URGENCY_BONUS = 0.15   # maximum additive bonus
URGENCY_CAP = 2        # expiring ingredients needed for the full bonus
```

Give `suggest_dishes` a new keyword-only parameter `expiring_soon: frozenset[str] = frozenset()`. After the existing blended score is computed and passed the `score > 0` gate, add:

```
n = number of the dish's ingredients present in expiring_soon
bonus = URGENCY_BONUS * min(n, URGENCY_CAP) / URGENCY_CAP
```

Count essentials **and** optionals — the goal is using up food before it spoils, and an expiring optional counts toward that.

Apply the bonus only to dishes that already scored above zero, so urgency can never resurrect a dish inside its recency cooldown. A dish cooked yesterday should not be suggested because the milk is turning.

Document at the constant why the bonus sits outside the learned blend and what would have to change to move it inside.

### 7.4 Surface it

`src/handlers/get_meal_suggestions.py`: build the expiring set from `fridge_repo.load_entries()` and today's date, pass it to `suggest_dishes`, and include a per-row `"uses_expiring": [names]` so the agent can explain *why* a dish moved up. An unexplained ranking change reads as a bug.

### 7.5 Tests

`test_unit.py`:
- `expiry_status` at each boundary: today, `EXPIRING_SOON_DAYS` away, one day past, far future, `None`.
- Legacy scalar and `null` entries load through `load_entries()` with `expires_on: None`.
- `save_entries` round-trips: an entry without expiry writes as a bare scalar, not `{"count": n, "expires_on": null}`.
- `suggest_dishes` with an empty `expiring_soon` produces **byte-identical output to before this stage** — the strongest guard that the default path is untouched.
- The bonus is applied, is capped at `URGENCY_BONUS`, and never lifts a cooldown-gated dish above zero.
- **`tuning.compute_rewards` produces identical rewards before and after this stage** for the same fixture. This is the invariant-2 regression test; do not skip it.

`test_integration.py`:
- `update_fridge_inventory` accepts the object form and `list_fridge` reports `expires_on` and `expiring_soon`.
- An expiring ingredient reorders `get_meal_suggestions` and the winning row lists it in `uses_expiring`.
- An expired ingredient is still usable (`get_meal_suggestions` can still propose the dish) and is flagged in `list_fridge`.
- A malformed `expires_on` at the tool boundary returns an error envelope.

### 7.6 Done when

- Both suites pass.
- `python3 test_unit.py` shows the tuning-parity test passing.
- An existing `fridge.json` with only scalar values round-trips with no diff.
- Commit: `Track ingredient expiry and prioritize dishes that use it`

---

## Stage 8 — Documentation, manifest, and final validation

Documentation drift is a real failure mode in this repo — two of the last five commits on `main` were docs-correction commits. Treat this stage as part of the work, not cleanup after it.

### 8.1 `plugin.yaml`

- Add every new tool to `provides_tools`: `set_dish_instructions`, `get_dish_recipe`, `list_cooking_history`, `merge_ingredient_alias`, and `list_ingredient_aliases` (unless Q4 skipped it).
- Bump `version` from `0.1.0` to `0.2.0`. This release changes two persisted formats and one tool's behaviour — that is a minor bump, not a patch.

Verify the manifest matches reality:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.src.handlers', pathlib.Path('.').resolve().name); print(sorted(n for n, _, _ in m.iter_tools()))"
```

Compare that list against `provides_tools` in `plugin.yaml`.

### 8.2 `CLAUDE.md`

Update, at minimum:
- The tool count in **Project Overview** ("twenty-one tool handlers" → the new number).
- **`_common.py`** — add `reject_unknown_args`, `normalize_ingredient_entries`, the alias resolution inside `normalize_ingredient_name`, and the sanitized error envelope.
- **`dish.py`** — the `instructions` field and its cap.
- **`suggestion.py`** — the urgency bonus, and explicitly why it sits outside the learned blend.
- **`json_history.py`** — replace the whole description with the event-log model.
- **`json_fridge.py`** — the extended value grammar and `load_entries` / `save_entries`.
- **New sections** for `history_event.py` and `json_alias.py`.
- **Data files** — `aliases.json`, and `history.json`'s new envelope.
- **Key Design Decisions** — remove the now-obsolete "Backdating never rewinds the cooldown" entry describing `only_if_newer` and replace it with the event-log rationale. Add entries for essential-wins on alias merges, and for expired-but-still-available.

### 8.3 `AGENTS.md`

- **Concurrency** — add the lock ordering rule (`alias → dish → fridge`) and the requirement to normalize arguments before acquiring any lock.
- **Domain Rules** — drop the `only_if_newer` bullet; add event-log, alias, and expiry rules.
- **Testing** — note the new coverage areas.
- **Error Handling** — document the sanitized envelope: `ValueError`/`LookupError` pass through, everything else is mapped.

### 8.4 `README.md` and `skill.md`

- `README.md` is the source of truth for the high-level summary — update the tool list and add short examples for instructions, history, aliases, and expiry.
- `skill.md` is LLM-facing: describe *when* to reach for each new tool. Most important is `merge_ingredient_alias`, since the agent must recognize "these are the same thing" from conversation, and `list_cooking_history` for "when did I last make this?".

### 8.5 Stale references sweep

```bash
grep -rn "only_if_newer\|twenty-one\|21 tools\|21 meal_manager" --include="*.md" --include="*.py" .
```

Every hit must be either fixed or consciously left (the `test_integration.py` module docstring says "all 21 meal_manager tools" — update it).

### 8.6 Final validation

```bash
python3 test_unit.py && python3 test_integration.py
```

Then verify no regression against Stage 0:
- Pass counts are **greater than** the baseline (never merely equal — every stage added tests).
- Zero failures.
- `git status --porcelain` shows only intended files.
- **`data/` is unmodified**: `git diff --stat data/` must be empty. If it is not, a test leaked into the live data directory — find it and fix the `configure()` wiring before committing.

Run the single-tool smoke check from `CLAUDE.md` for one new tool as a final sanity pass:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.src.handlers.list_cooking_history', pathlib.Path('.').resolve().name); print(m.HANDLER({}))"
```

### 8.7 Commit

`Update docs and manifest for tier 1-3 fork adoption`

Then report to the user: stages completed, tools added, tests added, formats migrated, and anything deferred.

---

---

## Stage 7 outcome — design note: a two-dimensional tuner (deferred)

**Status:** not implemented. Q1 selected "extend the learner to two dimensions", which §7 gates behind "stop and write a short design note in this file instead — that change deserves its own plan." This is that note.

**What was implemented anyway.** All three Q1 options store expiry; they differ only in how it influences ranking. So §7.1, §7.2 and §7.5 shipped in full — the fridge value grammar, `load_entries` / `save_entries`, `expiry_status`, `normalize_ingredient_entries`, and expiry reporting in `list_fridge`. What is deferred is exactly the ranking half (§7.3/§7.4) and the learner change that Q1 asked for. Ranking is byte-for-byte unchanged: `suggestion.py` and `tuning.py` were not touched in this stage.

Two things fell out of the storage work that the plan did not anticipate, both now covered by tests:

- `save()`, `consume()`, `restore_counts()` and `remove_items()` all round-tripped the count-only view. Writing that back verbatim erases every `expires_on`, so they were moved onto the entries pair. `save()` keeps its `{name: count}` signature and merges the stored dates back in.
- `normalize_ingredient_counts` had no callers left once `update_fridge_inventory` moved to `normalize_ingredient_entries` (the plan guessed `finalize_ingredient_session` used it; it does not), so it was removed rather than left as an untested duplicate.

### Why the 2D change needs its own plan

The current learner is a bandit over a **one-dimensional** grid. State is `{candidates: [w₁…wₙ], S: [...], C: [...]}` where each `w` implies the pair `(w, 1-w)`. `compute_rewards` walks each dish once, gets `(match, recency)` from `score_components`, and re-blends that same tuple per candidate — which is what makes full-information updates cheap. Adding urgency breaks four things at once:

1. **`score_components` grows a third term.** Invariant 2 says its signature and `(match, recency) | None` return must not change, because `compute_rewards` calls it directly. A third term means changing both in lockstep, plus every caller and every fixture.
2. **The grid becomes a simplex, not an interval.** Weights must satisfy `wₘ + wᵣ + wᵤ = 1`. A 9-point interval becomes a triangular lattice; matching today's resolution costs ~45 candidates, so `S`/`C` grow 5×, and `BAND` (currently an interval clamp) has to be redefined as a region.
3. **Hysteresis and cold-start stop being one-dimensional.** `HYSTERESIS_MARGIN` compares a challenger against the deployed point; on a simplex "adjacent" is no longer "one step left or right", and `select_deployed`'s argmax-within-`BAND` needs a distance metric it does not currently have.
4. **The reward signal gets sparser.** Urgency only discriminates when something is actually expiring. Most cook events would produce a reward vector that is uniform along the urgency axis, hit `MIN_REWARD_SPREAD`, and be discarded — so the third weight would learn far more slowly than the other two, from a fraction of the events. That is an argument for a different update rule (per-axis counts, or a longer `GAMMA` on the urgency axis), not just a bigger grid.

### If it is picked up

The cheap intermediate is the recommended option from Q1: keep the learner 1D and add urgency as a bounded additive bonus outside the blend (§7.3 as written). It gets the ranking behaviour with none of the above, and it is reversible.

If the full 2D learner is still wanted, a plan for it should cover: the migration path for existing `tuning.json` (a v1 1D state must project onto the simplex, not reset to cold start); how `BAND` and `HYSTERESIS_MARGIN` generalize; whether urgency updates on its own counter; and a parity test proving that with `wᵤ = 0` the 2D learner reproduces the 1D one exactly.

---

## Appendix A — Risk register

| Risk | Stage | Mitigation |
|---|---|---|
| A handler reads an argument absent from its schema; Stage 1 breaks it | 1 | Grep every `args.get` / `require_arg` call site (§1.3); integration suite covers all 21 tools |
| `JSONDecodeError` never matches because it subclasses `ValueError` | 2 | Ordering is called out explicitly in §2.1 and unit-tested |
| `edit_dish` silently drops `instructions` | 3 | Dedicated integration test (§3.5) |
| Event-log migration produces duplicate events on re-migration | 4 | Deterministic `uuid5` ids; idempotence unit test |
| Rollback *retracts* instead of hard-deleting, leaving a phantom cook | 4 | `delete_event` is a separate method; integration test asserts absence from `load_events()` |
| Tuning learner breaks because `score_components` changed | 7 | Invariant 2 stated up front; parity test compares `compute_rewards` output across the change |
| Alias resolution deadlocks against a repo lock | 6 | Normalize before locking; lock order documented in `AGENTS.md` |
| Alias merge demotes an essential to optional | 6 | Essential-wins rule, unit-tested |
| A test writes to the live `data/` | all | New singletons wired into `configure()`; `git diff --stat data/` checked at §8.6 |
| Docs drift from code | 8 | Stage 8 is mandatory, with an explicit grep sweep |

## Appendix B — Files touched

**New:**
`src/history_event.py`, `src/repositories/json_alias.py`, `src/handlers/set_dish_instructions.py`, `src/handlers/get_dish_recipe.py`, `src/handlers/list_cooking_history.py`, `src/handlers/merge_ingredient_alias.py`, `src/handlers/list_ingredient_aliases.py` *(Q4)*, `scripts/migrate_history_v2.py` *(Q2)*

**Modified:**
`src/dish.py`, `src/suggestion.py`, `src/handlers/_common.py`, all 21 existing handler modules *(decorator call site)*, `src/handlers/register_cooked_meal.py`, `src/handlers/delete_history_entry.py`, `src/handlers/update_fridge_inventory.py`, `src/handlers/list_fridge.py`, `src/handlers/get_meal_suggestions.py`, `src/handlers/edit_dish.py` *(possibly)*, `src/handlers/add_dish.py` *(possibly)*, `src/repositories/base.py`, `src/repositories/__init__.py`, `src/repositories/json_history.py`, `src/repositories/json_fridge.py`, `test_unit.py`, `test_integration.py`, `plugin.yaml`, `CLAUDE.md`, `AGENTS.md`, `README.md`, `skill.md`

**Never modified:** anything under `data/`.

## Appendix C — Deliberately not implemented

Weekly meal plans · shopping requests and receipt reconciliation · product catalog and replenishment · prep items and `prep_depends` · the domain audit trail · the FastAPI web UI · `JsonFileLock` cross-process locking · `atomic_write_json` changes (ours is already identical to the fork's non-audit path, directory `fsync` included).
