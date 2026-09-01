"""Phone-number normalization helpers for identity flows.

The platform is India-first today, so we canonicalize local 10-digit
numbers to E.164-style `+91XXXXXXXXXX`. Inputs that already include a
leading `+` are preserved after stripping non-digits.
"""
from __future__ import annotations

import re

DEFAULT_COUNTRY_CODE = "91"


def normalize_mobile_number(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("mobile_number is required")

    has_plus = cleaned.startswith("+")
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        raise ValueError("mobile_number must contain digits")

    if has_plus:
        if len(digits) == 12 and digits.startswith(DEFAULT_COUNTRY_CODE):
            return f"+{digits}"
        raise ValueError("Enter a valid Indian mobile number.")

    if len(digits) == 10:
        return f"+{DEFAULT_COUNTRY_CODE}{digits}"

    if len(digits) == 11 and digits.startswith("0"):
        return f"+{DEFAULT_COUNTRY_CODE}{digits[1:]}"

    if len(digits) == 12 and digits.startswith(DEFAULT_COUNTRY_CODE):
        return f"+{digits}"

    raise ValueError("Enter a valid Indian mobile number.")
