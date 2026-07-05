"""Online self-tuning of the suggestion engine's availability/recency blend.

Pure functions only — no file I/O, no locking, no randomness. Persistence
lives in ``repositories/json_tuning.py``; the cook handler owns the lock and
the read-modify-write sequence. This module just defines the learner math.

The learner searches a small grid of availability-weight candidates ``w`` (the
recency weight is always ``1 - w``, so there is a single free parameter). It is
online, event-driven, and full-information: every cooked meal replays the
decision that was in effect at that moment and rewards every candidate by how
highly it would have ranked the dish the user actually chose. A discounted
grid learner is the right tool for one free parameter and one noisy observation
per event — no optimizer, no daemon, no external libraries.

Determinism: given a state file, the output is fully reproducible. There is no
randomness anywhere in this module.
"""

from .suggestion import suggest_dishes

# ---------------------------------------------------------------------------
# Hyperparameters (module constants — there is no external config surface)
# ---------------------------------------------------------------------------

CANDIDATES = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
PRIOR_W = 0.60              # anchor; equals today's DEFAULT_MATCH_WEIGHT
BAND = (0.35, 0.80)         # hard clamp: never deploy w outside this
GAMMA = 0.98               # forgetting factor (~50-event effective window)
PRIOR_STRENGTH = 10.0       # pseudo-observations backing the prior
PRIOR_REWARD_ANCHOR = 0.60  # seed reward for the anchor candidate
PRIOR_REWARD_OTHER = 0.50   # seed reward for all other candidates
MIN_OBSERVATIONS = 20       # cold start: below this, always deploy PRIOR_W
HYSTERESIS_MARGIN = 0.03    # don't switch deploy unless clearly better

VERSION = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key(w) -> str:
    """Fixed-format candidate key so JSON round-trips are stable."""
    return f"{float(w):.2f}"


def _clamp_to_band(w: float) -> float:
    return min(max(w, BAND[0]), BAND[1])


def _mean(state: dict, key: str) -> float:
    """Discounted mean reward for a candidate; 0.0 if it has no mass yet."""
    count = state["C"].get(key, 0.0)
    if count <= 0:
        return 0.0
    return state["S"].get(key, 0.0) / count


# ---------------------------------------------------------------------------
# State construction / validation
# ---------------------------------------------------------------------------

def initialize_state() -> dict:
    """Fresh state: prior-seeded, anchor deployed, zero real observations.

    Every candidate gets ``C = PRIOR_STRENGTH`` pseudo-observations. The anchor
    is seeded with a slightly higher reward so it is the initial argmax; the
    forgetting factor makes this seed fade as real data accumulates.
    """
    S: dict[str, float] = {}
    C: dict[str, float] = {}
    for w in CANDIDATES:
        key = _key(w)
        C[key] = PRIOR_STRENGTH
        if key == _key(PRIOR_W):
            S[key] = PRIOR_STRENGTH * PRIOR_REWARD_ANCHOR
        else:
            S[key] = PRIOR_STRENGTH * PRIOR_REWARD_OTHER
    return {
        "version": VERSION,
        "candidates": list(CANDIDATES),
        "S": S,
        "C": C,
        "observations": 0,
        "deployed_match_weight": PRIOR_W,
        "deployed_time_weight": round(1 - PRIOR_W, 4),
    }


def validate_state(raw) -> dict:
    """Return *raw* if it has the expected shape and candidate set.

    Anything unexpected (wrong type, missing field, mismatched candidate set,
    non-numeric mass) falls back to a fresh :func:`initialize_state`, so a
    corrupt file behaves exactly like a missing one.
    """
    if not isinstance(raw, dict):
        return initialize_state()

    candidates = raw.get("candidates")
    S = raw.get("S")
    C = raw.get("C")
    observations = raw.get("observations")

    if not isinstance(candidates, list) or not isinstance(S, dict) or not isinstance(C, dict):
        return initialize_state()
    if not isinstance(observations, int) or isinstance(observations, bool):
        return initialize_state()

    expected_keys = {_key(w) for w in CANDIDATES}
    try:
        got_keys = {_key(w) for w in candidates if isinstance(w, (int, float))}
    except (TypeError, ValueError):
        return initialize_state()
    if got_keys != expected_keys:
        return initialize_state()
    if set(S.keys()) != expected_keys or set(C.keys()) != expected_keys:
        return initialize_state()
    for key in expected_keys:
        if not isinstance(S[key], (int, float)) or isinstance(S[key], bool):
            return initialize_state()
        if not isinstance(C[key], (int, float)) or isinstance(C[key], bool):
            return initialize_state()

    return raw


# ---------------------------------------------------------------------------
# One learning event
# ---------------------------------------------------------------------------

def compute_rewards(cooked_name, dishes, fridge_set, days_map, candidates):
    """Reward every candidate by how highly it ranked the cooked dish.

    Uses the pre-cook fridge/history snapshot. Returns ``None`` to signal
    "skip this event" when the cooked dish could not have been suggested
    (not cookable) or there is no ranking signal (fewer than two cookable
    dishes). Otherwise returns ``{candidate_key: reward}`` where reward is
    ``(N - pos) / (N - 1)`` — top rank -> 1.0, bottom rank -> 0.0.
    """
    cookable = [d for d in dishes if d.can_cook_with(fridge_set)]
    if not any(d.name == cooked_name for d in cookable):
        return None
    N = len(cookable)
    if N < 2:
        return None

    rewards: dict[str, float] = {}
    found_any = False
    for w in candidates:
        ranking = suggest_dishes(cookable, fridge_set, days_map,
                                 match_weight=w, time_weight=1 - w)
        pos = N  # dishes scoring 0 are dropped from the ranking -> bottom
        for index, (dish, _score) in enumerate(ranking):
            if dish.name == cooked_name:
                pos = index + 1
                found_any = True
                break
        rewards[_key(w)] = (N - pos) / (N - 1)
    # If the cooked dish scored 0 for *every* candidate it was dropped from all
    # rankings (cooldown gate or empty-ingredient dish — both weight-independent).
    # That carries no discriminating signal, so skip the event like N<2 rather
    # than feeding a uniform all-zero reward that only discounts accumulated mass.
    if not found_any:
        return None
    return rewards


def apply_update(state: dict, rewards: dict) -> dict:
    """Apply the discounted update for every candidate. Pure — returns a new
    state dict and never mutates its input."""
    S = dict(state["S"])
    C = dict(state["C"])
    for key, reward in rewards.items():
        S[key] = GAMMA * S.get(key, 0.0) + reward
        C[key] = GAMMA * C.get(key, 0.0) + 1
    new_state = dict(state)
    new_state["S"] = S
    new_state["C"] = C
    new_state["observations"] = state.get("observations", 0) + 1
    return new_state


def select_deployed(state: dict) -> dict:
    """Choose the deployed weight per Section 4.3 step 5 and record it.

    Cold start (below ``MIN_OBSERVATIONS``) always deploys the anchor. Once
    warm, switch to the best-mean candidate within ``BAND`` only if it beats
    the current deployed candidate by more than ``HYSTERESIS_MARGIN``.
    """
    # Copy before mutating so we honour the module's pure-function contract
    # (a caller passing a snapshot must not see its deployed_* fields change).
    state = dict(state)
    observations = state.get("observations", 0)
    candidates = state.get("candidates", list(CANDIDATES))

    if observations < MIN_OBSERVATIONS:
        deployed_w = PRIOR_W
    else:
        current_mw, _current_tw = deployed_weights(state)
        in_band = [w for w in candidates if BAND[0] <= w <= BAND[1]]
        if not in_band:
            in_band = [PRIOR_W]
        best = max(in_band, key=lambda w: _mean(state, _key(w)))
        if _mean(state, _key(best)) - _mean(state, _key(current_mw)) > HYSTERESIS_MARGIN:
            deployed_w = best
        else:
            deployed_w = current_mw

    deployed_w = _clamp_to_band(deployed_w)
    state["deployed_match_weight"] = deployed_w
    state["deployed_time_weight"] = round(1 - deployed_w, 4)
    return state


def deployed_weights(state) -> tuple[float, float]:
    """Safe reader: ``(match_weight, time_weight)`` from *state*.

    Falls back to the prior blend if the match weight is missing or unreadable,
    and otherwise clamps it to ``BAND`` and re-derives ``time_weight = 1 - mw``.
    This guarantees the returned blend is always in-band and normalized even if
    the on-disk file was hand-edited, written by another version, or left with a
    non-summing pair (``validate_state`` does not police the deployed fields).
    """
    try:
        mw = float(state["deployed_match_weight"])
    except (KeyError, TypeError, ValueError):
        return (PRIOR_W, round(1 - PRIOR_W, 4))
    if mw != mw:  # NaN
        return (PRIOR_W, round(1 - PRIOR_W, 4))
    mw = _clamp_to_band(mw)
    return (mw, round(1 - mw, 4))
