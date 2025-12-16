class RetryableJobError(Exception):
    """Raised when a job fails but should be retried."""
    pass

class PermanentJobError(Exception):
    """Raised when a job fails and should not be retried."""
    pass
