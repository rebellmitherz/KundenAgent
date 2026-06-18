"""Signal-Personalisierung — verkaufspsychologischer Aufhänger pro Lead.

Öffentliche API:
    aufhaenger_text(lead, angebot_typ, ...) -> str
        Ein/zwei personalisierte Einstiegssätze für die Erstmail. Leerer String,
        wenn kein verwertbares Signal vorliegt (→ generische Standard-Mail).
"""
from __future__ import annotations

from .aufhaenger import (
    Aufhaenger,
    aufhaenger_angle,
    aufhaenger_text,
    standard_llm,
)

__all__ = ["Aufhaenger", "aufhaenger_angle", "aufhaenger_text", "standard_llm"]
