class RetryableJobError(Exception):
    """Raised when a job fails but should be retried (e.g., network error)."""
    pass

class PermanentJobError(Exception):
    """Raised when a job fails and should not be retried (e.g., invalid payload)."""
    pass
