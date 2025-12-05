import hashlib
from typing import Optional

def get_experiment_cohort(user_id: str, experiment_name: str) -> str:
    """
    Deterministically assigns a user to a cohort for a given experiment.
    Returns: 'variant_B' or 'control_A'
    """
    if not user_id:
        return "control_A"

    key = f"{user_id}:{experiment_name}"
    # Use MD5 for stable hashing
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)

    # Simple 50/50 split
    return "variant_B" if h % 2 == 0 else "control_A"
