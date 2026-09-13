"""SEC ``companyfacts`` JSON, which nests facts → taxonomy → concept → units."""

from __future__ import annotations


def concept_units(facts: object, taxonomy: str, concept: str) -> dict[str, list]:
    """One concept's facts keyed by unit; empty when the document lacks it."""
    if not isinstance(facts, dict):
        return {}
    concepts = (facts.get("facts") or {}).get(taxonomy) or {}
    units = (concepts.get(concept) or {}).get("units") or {}
    return units if isinstance(units, dict) else {}
