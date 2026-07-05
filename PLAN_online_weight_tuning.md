# Implementation Plan — Online Self-Tuning of Suggestion Weights (`meal-manager`)

**Target repo:** `sergiparpal/meal-manager` (Hermes Agent plugin, Python 3.12+, **stdlib only**)
**Executor:** Claude Code CLI, running autonomously.
**Deliverable:** A `data/tuning.json`-backed online learner that adjusts the availability/recency blend of the suggestion engine as the plugin is used — one update per cooked meal, no background job, no external libraries.

---

## 1. Objective

Today the suggestion engine blends two signals with hardcoded weights in `src/suggestion.py`:

- **availability** (ingredient coverage) — `DEFAULT_MATCH_WEIGHT = 0.6`
- **recency** (days since last cooked) — `DEFAULT_TIME_WEIGHT = 0.4`

Replace the *hardcoded* blend with a **self-adjusting availability weight `w`** (recency weight is always `1 - w`, so this is a **single free parameter**). Learning is **online, event-driven, full-information**: every time a meal is registered as cooked, the learner replays the decision that was in effect *at that moment* and rewards every candidate `w` according to how highly it would have ranked the dish the user actually chose. No external optimizer, no daemon, no cron.

This is deliberately **not** a genetic algorithm or a neural net: with one free parameter and one noisy observation per day, a full-information discounted grid learner is the correct tool. Population-based search and gradient training would be strictly worse here.

### Accepted trade-off (do not "fix" this)
Suggestions will now depend on `data/tuning.json`, not on source constants alone. This softens the plugin's deterministic-core promise **on purpose** (the maintainer has approved it). Preserve what actually matters: output stays **deterministic given the state file**, the learned weight is **bounded, auditable, and slow-moving**, and it is exposed through a read-only tool. Do **not** introduce randomness anywhere in the learner.

---

## 2. Execution rules for the agent (read carefully)

1. **Run straight through all phases without stopping for human approval.** Each phase has machine-checkable acceptance criteria; verify them yourself and continue.
2. **The only permitted pause is the single optional config check in Phase 0.** Present it as one consolidated prompt, wait briefly, and **if there is no objection, proceed with the defaults**. Never block the whole run on it.
3. **Obey the repo's existing conventions** (Section 3). Do not add dependencies. Do not reformat unrelated files.
4. **Self-verify at the end** by running both test scripts (Section 12). The task is done only when both pass and every acceptance box is satisfied.
5. If a genuinely blocking ambiguity appears that is *not* covered here, ask **one** short question via the CLI and continue; do not re-plan the whole feature.

---

## 3. Non-negotiable conventions (from `CLAUDE.md` / `AGENTS.md` — re-read both first)

- **Read `AGENTS.md` and `CLAUDE.md` before writing code.**
- **Stdlib only.** Python 3.12+. No pip installs, ever.
- **Relative imports throughout** (e.g. `from ..suggestion import ...`), because Hermes loads the package as `hermes_plugins.meal_manager`. Absolute `from src.xxx` imports fail at runtime.
- **Persistence lives behind repositories.** Pure domain logic goes in `src/*.py`; all file I/O goes in `src/repositories/json_*.py` and is exposed as a singleton from `src/repositories/__init__.py`. Consumers depend on the `Protocol` in `base.py`, not on the concrete class.
- **Repositories own their own `lock`** (`threading.Lock`) and write via `atomic_write_json` (from `src/__init__.py`).
- **Handlers**: one module per tool under `src/handlers/`, exporting `NAME`, `SCHEMA`, `HANDLER`; `HANDLER` is decorated with `@tool_handler(NAME)`, returns a plain Python object, and raises on error. Discovery is automatic and alphabetical via `iter_tools()`.
- **`plugin.yaml` `provides_tools` is kept in sync by hand** — update it when adding a tool.
- **JSON keys are English.** Names are normalized (`strip().lower()`) once at the boundary; downstream trusts the invariant.
- **Data directory is injectable** via `src.repositories.configure(data_dir)`; any new repo singleton MUST be redirected there too.
- **Tests are plain assertion scripts** (`test_unit.py`, `test_integration.py`), not pytest/unittest. Match that style.

---

## 4. Algorithm specification

### 4.1 Parameterization
The learner searches over a small set of **availability-weight candidates** `w`. The deployed pair is always `(match_weight=w, time_weight=1 - w)`.

```
CANDIDATES        = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
PRIOR_W           = 0.60        # anchor; equals today's DEFAULT_MATCH_WEIGHT
BAND              = (0.35, 0.80)# hard clamp: never deploy w outside this
GAMMA             = 0.98        # forgetting factor (~50-event effective window)
PRIOR_STRENGTH    = 10.0        # pseudo-observations backing the prior
PRIOR_REWARD_ANCHOR = 0.60      # seed reward for the anchor candidate
PRIOR_REWARD_OTHER  = 0.50      # seed reward for all other candidates
MIN_OBSERVATIONS  = 20          # cold start: below this, always deploy PRIOR_W
HYSTERESIS_MARGIN = 0.03        # don't switch deploy unless clearly better
```

Keep every candidate inside `BAND`. If any config change in Phase 0 pushes a candidate outside `BAND`, clamp the candidate list to `BAND`.

### 4.2 State (`data/tuning.json`)
```json
{
  "version": 1,
  "candidates": [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80],
  "S": {"0.40": 5.0, "0.45": 5.0, "...": "discounted reward sum per candidate"},
  "C": {"0.40": 10.0, "...": "discounted observation count per candidate"},
  "observations": 0,
  "deployed_match_weight": 0.60,
  "deployed_time_weight": 0.40
}
```
Store candidate keys as fixed-format strings (e.g. `f"{w:.2f}"`) so JSON round-trips are stable. `mean[w] = S[w] / C[w]`.

**Initialization** (`initialize_state`): for every candidate, `C[w] = PRIOR_STRENGTH`; `S[w] = PRIOR_STRENGTH * PRIOR_REWARD_OTHER`, except the anchor `S[PRIOR_W] = PRIOR_STRENGTH * PRIOR_REWARD_ANCHOR`. `observations = 0`. Deployed = anchor. This makes the anchor the initial argmax; discounting makes the seed fade as real data accumulates.

### 4.3 One learning event (when a meal is cooked)
Use the state **as it was at the moment the user decided to cook** — i.e. the fridge and history *before* this cook is recorded and *before* essentials are removed.

1. Snapshot `fridge_set` and `days_map = days_since_last_cook()` **before** any mutation in `register_cooked_meal`.
2. Determine the **cookable set**: dishes where `dish.can_cook_with(fridge_set)` (this gate is `w`-independent).
   - If the cooked dish is **not** in the cookable set → **skip the event** (degenerate: it could not have been suggested).
   - If cookable set size `N < 2` → **skip the event** (no ranking signal).
3. For each candidate `w`: rank the cookable set with `suggest_dishes(..., match_weight=w, time_weight=1-w)`, find the 1-based position `pos` of the cooked dish (dishes scoring 0 sort to the bottom; if absent from the ranking, treat `pos = N`). Compute:
   ```
   reward[w] = (N - pos) / (N - 1)     # top -> 1.0, bottom -> 0.0
   ```
4. Apply the discounted update for every candidate:
   ```
   S[w] = GAMMA * S[w] + reward[w]
   C[w] = GAMMA * C[w] + 1
   ```
   Increment `observations`.
5. **Select deployed** `w`:
   - If `observations < MIN_OBSERVATIONS`: deploy `PRIOR_W`.
   - Else: `best = argmax_w mean[w]` over candidates within `BAND`; deploy `best` **only if** `mean[best] - mean[deployed] > HYSTERESIS_MARGIN`, otherwise keep the current deployed `w`.
   - Always store both `deployed_match_weight = w` and `deployed_time_weight = round(1 - w, 4)`.

The learning update is **best-effort and non-critical**: if anything in steps 1–5 raises, log it and let `register_cooked_meal` still succeed. Cook registration must never fail or roll back because learning failed.

### 4.4 Backward compatibility
If `data/tuning.json` is missing or corrupt, `load()` returns a freshly initialized state (deploy = `PRIOR_W`). Existing installs therefore behave **exactly as today** until `MIN_OBSERVATIONS` cook events accumulate. No migration step is required.

---

## 5. Phase 0 — Orientation + optional config check

- Read `AGENTS.md`, `CLAUDE.md`, `src/suggestion.py`, `src/handlers/register_cooked_meal.py`, `src/handlers/get_meal_suggestions.py`, `src/handlers/_common.py`, `src/repositories/__init__.py`, `src/repositories/base.py`, `src/repositories/json_history.py`, `test_unit.py`, `test_integration.py`.
- **Optional single prompt (non-blocking):** "About to implement online weight tuning with these defaults: candidates 0.40–0.80 step 0.05, GAMMA 0.98, cold-start 20 events, band [0.35, 0.80], hysteresis 0.03. Reply with any override or just continue." **If no override arrives promptly, proceed with the defaults.** Do not gate any later phase on this.

**Acceptance:** conventions understood; defaults confirmed or overridden; proceed.

---

## 6. Phase 1 — Make the scoring path weight-parameterized

**File:** `src/suggestion.py`
- Extend `suggest_dishes` to accept optional `match_weight` / `time_weight`, defaulting to `DEFAULT_MATCH_WEIGHT` / `DEFAULT_TIME_WEIGHT`, and pass them through to `calculate_score` (which already accepts these kwargs). Do **not** change scoring math or the existing default behavior.

```python
def suggest_dishes(dishes, available_ingredients, days_since_last,
                   match_weight=DEFAULT_MATCH_WEIGHT, time_weight=DEFAULT_TIME_WEIGHT):
    ...
    score = calculate_score(dish, available_ingredients, days,
                            match_weight=match_weight, time_weight=time_weight)
    ...
```

**Acceptance:** calling `suggest_dishes` with no weight args produces byte-identical rankings to before; passing explicit weights changes the ranking accordingly.

---

## 7. Phase 2 — Pure learner logic

**New file:** `src/tuning.py` (pure functions, no I/O, no locking, no randomness). Define the constants from Section 4.1 and:

- `initialize_state() -> dict` — per Section 4.2.
- `default_state() -> dict` — alias returning a fresh `initialize_state()`; used as the fallback for missing/corrupt files.
- `validate_state(raw) -> dict` — return `raw` if it has the expected shape and candidate set; otherwise return `initialize_state()`.
- `compute_rewards(cooked_name, dishes, fridge_set, days_map, candidates) -> dict[str, float] | None` — implements Section 4.3 steps 2–3; returns `None` to signal "skip event". Import `suggest_dishes` from `.suggestion`.
- `apply_update(state, rewards) -> dict` — Section 4.3 step 4; returns a new state dict (pure; do not mutate input).
- `select_deployed(state) -> dict` — Section 4.3 step 5; sets `deployed_match_weight` / `deployed_time_weight`; returns the state.
- `deployed_weights(state) -> tuple[float, float]` — safe reader returning `(match_weight, time_weight)`, falling back to `(PRIOR_W, 1 - PRIOR_W)` if fields are missing.

**Acceptance:** functions are importable and pure; `apply_update` never mutates its input; all deployed weights stay within `BAND`.

---

## 8. Phase 3 — Tuning repository + wiring

**New file:** `src/repositories/json_tuning.py` — `JsonTuningRepository`, modeled on `json_history.py`:
- `__init__(self, path)`, `self.lock = threading.Lock()`.
- `load(self) -> dict` — read JSON; on missing/invalid/failed-schema, return `tuning.validate_state(...)`/`initialize_state()`. Never raise on read.
- `save(self, state) -> None` — `atomic_write_json(self.path, state)`.

**Edit `src/repositories/base.py`:** add a `TuningRepository(Protocol)` with `lock`, `load() -> dict`, `save(state: dict) -> None`.

**Edit `src/repositories/__init__.py`:**
- import `JsonTuningRepository` and `TuningRepository`;
- add singleton `tuning_repo = JsonTuningRepository(_DEFAULT_DATA_DIR / "tuning.json")`;
- in `configure(data_dir)`, add `tuning_repo.path = data_dir / "tuning.json"`;
- add both names to `__all__`.

**Acceptance:** `from ..repositories import tuning_repo` works; `configure(tmp)` redirects the tuning path; loading a nonexistent file yields a valid initialized state.

---

## 9. Phase 4 — Learn on each cooked meal

**File:** `src/handlers/register_cooked_meal.py`
- At the **top of the handler, before any mutation**, snapshot the pre-cook state:
  ```python
  fridge_snapshot = fridge_repo.load_set()
  days_snapshot = days_since_last_cook()   # import from ._common
  ```
- Keep the existing record-history + remove-essentials logic **unchanged** (including its rollback).
- **After** the existing logic has succeeded, run the learning update **best-effort**:
  ```python
  try:
      with tuning_repo.lock:
          state = tuning_repo.load()
          rewards = tuning.compute_rewards(name, dishes, fridge_snapshot,
                                           days_snapshot, state["candidates"])
          if rewards is not None:
              state = tuning.apply_update(state, rewards)
              state = tuning.select_deployed(state)
              tuning_repo.save(state)
  except Exception:
      logger.exception("weight tuning update failed (non-critical)")
  ```
- Import `tuning` (`from .. import tuning` or `from ..tuning import ...`) and `tuning_repo`; reuse the existing `dishes` list loaded in the handler.

**Acceptance:** registering a cook still returns the same success message and still removes essentials; a valid `data/tuning.json` is created/updated; a forced exception inside the tuning block does not fail the cook registration.

---

## 10. Phase 5 — Deploy the learned weight in suggestions

**File:** `src/handlers/get_meal_suggestions.py`
- Load the deployed weights and pass them into `suggest_dishes`:
  ```python
  mw, tw = tuning.deployed_weights(tuning_repo.load())
  ranking = suggest_dishes(dishes, fridge, days, match_weight=mw, time_weight=tw)
  ```
- Keep the returned shape (`[{"dish", "score"}]`) **unchanged** so no host/skill contract breaks. On any load failure, `deployed_weights` falls back to the prior.

**Acceptance:** suggestions use the deployed weight; with a fresh/missing `tuning.json`, output equals current behavior (0.6/0.4).

---

## 11. Phase 6 — Transparency tool `get_tuning_state`

**New file:** `src/handlers/get_tuning_state.py` — read-only tool exposing the current blend so the user can see e.g. "availability 0.62 / recency 0.38".
- `NAME = "get_tuning_state"`.
- `SCHEMA`: empty properties, description explaining it returns the current self-adjusted suggestion weights and learning status.
- `HANDLER`: load `tuning_repo`, return:
  ```json
  {
    "availability_weight": <deployed_match_weight>,
    "recency_weight": <deployed_time_weight>,
    "observations": <int>,
    "learning_active": <observations >= MIN_OBSERVATIONS>,
    "candidates": [...]
  }
  ```
- **Edit `plugin.yaml`:** add `get_tuning_state` to `provides_tools`.

**Acceptance:** tool auto-discovers (alphabetical order handles placement), returns the current weights, and is listed in `plugin.yaml`.

---

## 12. Phase 7 — Tests (match existing plain-assert style)

**`test_unit.py`** — add pure-logic assertions for `src/tuning.py`:
- fresh state deploys `PRIOR_W`; all candidates inside `BAND`;
- `compute_rewards` returns `None` when the cooked dish is not cookable, and when `N < 2`;
- top-ranked cooked dish yields reward `1.0` for the winning candidate;
- repeatedly rewarding high-availability scenarios shifts the deployed weight upward **only after** `MIN_OBSERVATIONS`;
- cold start: with `observations < MIN_OBSERVATIONS`, deployed stays at `PRIOR_W` regardless of rewards;
- hysteresis: a sub-margin advantage does not switch the deployed weight;
- `apply_update` does not mutate its input.

**`test_integration.py`** — using the existing `tempfile.mkdtemp()` + `configure` pattern:
- register several cooked meals end-to-end; assert `tuning.json` is created and `deployed_match_weight` stays within `BAND`;
- assert `get_meal_suggestions` still returns the `[{dish, score}]` shape;
- assert `get_tuning_state` returns weights that sum to ~1.0.

**Acceptance:** `python3 test_unit.py` and `python3 test_integration.py` both pass with no external packages.

---

## 13. Phase 8 — Docs

- **`CLAUDE.md`**: under Architecture, add `src/tuning.py` (learner), `src/repositories/json_tuning.py` + `tuning_repo`, the `get_tuning_state` tool, and `data/tuning.json`. Under Key Design Decisions, add a short "Adaptive suggestion weights" entry noting the accepted determinism trade-off (deterministic *given* `tuning.json`, bounded, auditable, exposed via `get_tuning_state`).
- **`README.md`**: one or two sentences that the availability/recency blend self-adjusts with use and can be inspected via `get_tuning_state`.
- **`skill.md`**: brief note that suggestion weights adapt over time and that `get_tuning_state` reports the current blend.
- **`AGENTS.md`**: update only if it enumerates tools/modules that now need the new entries.

**Acceptance:** docs mention the new module, repo, tool, and data file; the "nineteen tool handlers" count in `CLAUDE.md` is updated to twenty.

---

## 14. Final verification (must all hold)

- [ ] `python3 test_unit.py` passes.
- [ ] `python3 test_integration.py` passes.
- [ ] No non-stdlib imports anywhere; all internal imports are relative.
- [ ] Fresh checkout (no `data/tuning.json`) reproduces today's 0.6/0.4 behavior.
- [ ] A raised exception inside the tuning block leaves `register_cooked_meal`'s success path and rollback semantics intact.
- [ ] Deployed weight is always inside `BAND`; `get_tuning_state` reports it.
- [ ] `plugin.yaml`, `configure()`, `base.py`, and `__all__` all include the new tuning wiring.
- [ ] No randomness introduced; the learner is deterministic given its state file.

---

## 15. Non-goals (do not implement)

- No genetic algorithm, neural net, Bayesian optimizer, or bandit.
- No background job, scheduler, cron, or daemon — learning is strictly event-driven on cook registration.
- No changes to the DII flow, shopping logic, or the fridge/history data schemas.
- No new external configuration UI; hyperparameters are module constants in `src/tuning.py`.
- No changes to the `get_meal_suggestions` return shape.
