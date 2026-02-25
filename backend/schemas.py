"""
Shared Pydantic config for strict input validation (OWASP).
Reject unexpected fields, enforce type and length limits on all user input.
"""

from pydantic import ConfigDict

# Base config: forbid extra fields so clients cannot inject unexpected data.
STRICT_REQUEST_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)
