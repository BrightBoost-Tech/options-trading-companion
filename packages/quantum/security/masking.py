"""
Security v4: Log Masking Utilities

This module provides utilities to sanitize log messages and exceptions
by masking sensitive information like API keys, passwords, and tokens.
"""

import re
from typing import Optional

# Pre-compile regexes for performance
MASKING_PATTERNS = [
    # Database Connection Strings: postgres://user:password@host
    # Capture group 1: postgres://user:
    # Capture group 2: password
    # Capture group 3: @
    (re.compile(r'(postgres://[^:]+:)([^@]+)(@)'), r'\1****\3'),
    (re.compile(r'(postgresql://[^:]+:)([^@]+)(@)'), r'\1****\3'),

    # OpenAI API Keys: sk-...
    # Keep first 7 chars (sk-xxxx), mask rest
    # Matches standard keys and new project keys (sk-proj-...)
    (re.compile(r'(sk-[a-zA-Z0-9_-]{4})[a-zA-Z0-9._-]{20,}'), r'\1****'),

    # JWT Tokens: eyJ...
    # Keep first 13 chars (header prefix), mask rest
    (re.compile(r'(eyJ[a-zA-Z0-9_-]{10})[a-zA-Z0-9._-]+'), r'\1****'),

    # AWS Access Keys
    (re.compile(r'(AKIA[0-9A-Z]{4})[0-9A-Z]{12}'), r'\1****'),

    # Plaid Client ID / Secret (often labeled in logs)
    (re.compile(r'(Client ID:\s*)[a-zA-Z0-9]{10,}'), r'\1****'),
    (re.compile(r'(Secret:\s*)[a-zA-Z0-9]{10,}'), r'\1****'),
]

def sanitize_message(message: str) -> str:
    """
    Sanitize a log message by masking known secret patterns.
    """
    if not message:
        return ""

    sanitized = str(message) # Ensure string
    for pattern, replacement in MASKING_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized

def sanitize_exception(exc: Exception) -> str:
    """
    Return a sanitized string representation of an exception.
    """
    return sanitize_message(str(exc))
