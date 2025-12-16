def backoff_seconds(attempt: int) -> int:
    """
    Returns the number of seconds to backoff based on the attempt number.
    Schedule:
    - Attempt 1: 30s
    - Attempt 2: 2m (120s)
    - Attempt 3: 10m (600s)
    - Attempt 4: 30m (1800s)
    - Attempt 5+: 2h (7200s)
    """
    if attempt <= 1:
        return 30
    elif attempt == 2:
        return 120
    elif attempt == 3:
        return 600
    elif attempt == 4:
        return 1800
    else:
        return 7200
