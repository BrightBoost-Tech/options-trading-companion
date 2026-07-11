from enum import Enum

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # F-A4-1: ran to completion, some units failed (terminal, honest)
    FAILED_RETRYABLE = "failed_retryable"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"
