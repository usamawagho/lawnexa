
"""Curated source registry for LawNexa's Pakistani legal research.

A registered portal is a discovery starting point, not proof that an
individual statute, amendment, or judgment is current or verified.
"""

from typing import Any


LEGAL_SOURCES: list[dict[str, Any]] = [
    {
        "id": "pakistan_code",
        "title": "Pakistan Code — Ministry of Law and Justice",
        "url": "https://pakistancode.gov.pk/english/index.html",
        "source_type": "federal_legislation_portal",
        "jurisdiction": "Pakistan — federal",
        "verification_note": (
            "Check the individual law's status and relevant Gazette "
            "notifications. Portal availability alone does not verify "
            "the current legal status of a provision."
        ),
    },
]


def get_legal_sources() -> list[dict[str, Any]]:
    """Return a copy of the curated source registry."""
    return [source.copy() for source in LEGAL_SOURCES]
