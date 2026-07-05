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
        "availability_weight and recency_weight (which sum to 1.0), how many "
        "learning observations have accumulated, whether learning is active "
        "yet, and the candidate weights the learner searches over. Read-only."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    state = tuning_repo.load()
    availability_weight, recency_weight = tuning.deployed_weights(state)
    observations = state.get("observations", 0)
    return {
        "availability_weight": availability_weight,
        "recency_weight": recency_weight,
        "observations": observations,
        "learning_active": observations >= tuning.MIN_OBSERVATIONS,
        "candidates": state.get("candidates", list(tuning.CANDIDATES)),
    }
