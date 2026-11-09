"""Tool: get_tuning_state — report the self-adjusted suggestion weights."""

from .. import tuning
from ..repositories import tuning_repo
from ._common import tool_handler

NAME = "get_tuning_state"

SCHEMA = {
    "description": (
        "Report the current self-adjusted suggestion weights and learning "
        "status. The availability/recency blend used by get_meal_suggestions "
        "adapts as meals are registered as cooked. Returns the deployed "
        "availability_weight and recency_weight (which sum to 1.0); how many "
        "learning observations have accumulated (cooked meals that told the "
        "learner something about the blend, which not every meal does); "
        "whether learning is active yet, and at how many observations it "
        "starts; the default blend used until then; last_change, the latest "
        "move of the blend, with its date and the weights before and after "
        "(null if it never moved); and the candidate weights the learner "
        "searches over. Use last_change to explain why suggestions changed. "
        "Read-only."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


def _blend(match_weight: float) -> dict:
    return {"availability_weight": match_weight, "recency_weight": round(1 - match_weight, 4)}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    state = tuning_repo.load()
    availability_weight, recency_weight = tuning.deployed_weights(state)
    observations = state.get("observations", 0)
    change = tuning.last_change(state)
    return {
        "availability_weight": availability_weight,
        "recency_weight": recency_weight,
        "observations": observations,
        "learning_active": observations >= tuning.MIN_OBSERVATIONS,
        "learning_starts_at": tuning.MIN_OBSERVATIONS,
        "default_availability_weight": tuning.PRIOR_W,
        "default_recency_weight": round(1 - tuning.PRIOR_W, 4),
        "last_change": None if change is None else {
            "on": change["on"],
            "observations": change["observations"],
            "from": _blend(change["from_match_weight"]),
            "to": _blend(change["to_match_weight"]),
        },
        "candidates": state.get("candidates", list(tuning.CANDIDATES)),
    }
