"""Optionaler LLM-Adapter (Anthropic) für den Operator-Intake.

Baut eine llm_fn(system, user) -> str, die der OperatorIntake nutzen kann.

Sicherheit / Packaging:
  - Key wird zur Laufzeit aus der Umgebung gelesen (os.environ), NICHT aus
    einer .env-Datei und NICHT geloggt/angezeigt.
  - Ohne Key oder ohne SDK gibt build_anthropic_llm() None zurück — der Intake
    läuft dann deterministisch weiter (kein harter Fehler).
"""
from __future__ import annotations

import os
from typing import Optional

from product.operator.intake import LLMFn

_MODELL = "claude-haiku-4-5-20251001"  # schnell + günstig für reine Extraktion


def build_anthropic_llm(api_key: Optional[str] = None) -> Optional[LLMFn]:
    """Erzeugt eine llm_fn oder None, wenn kein Key/SDK verfügbar ist.

    api_key: optional explizit übergeben (z. B. aus Kunden-Config).
             Fällt sonst auf die Umgebungsvariable ANTHROPIC_API_KEY zurück.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    client = Anthropic(api_key=key)

    def llm_fn(system: str, user: str) -> str:
        resp = client.messages.create(
            model=_MODELL,
            max_tokens=300,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Text-Teile zusammenfügen
        teile = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(teile)

    return llm_fn
