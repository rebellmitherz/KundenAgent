"""Versions-Manifest für Rebellsystem Sales Operator.

Einzige Quelle der Wahrheit für Version, Build-Datum und Komponenten-Versionen.
Wird vom Package-Skript und vom Installations-Checker gelesen.
"""
from __future__ import annotations

VERSION = "1.0.0"
PRODUCT_NAME = "Rebellsystem Sales Operator"
BUILD_DATE = "2026-06-04"

# Mindest-Python-Version
MIN_PYTHON = (3, 10)

MANIFEST: dict = {
    "product": PRODUCT_NAME,
    "version": VERSION,
    "build_date": BUILD_DATE,
    "min_python": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
    "components": {
        "operator":  "1.0",
        "bridge":    "1.0",
        "telegram":  "1.0",
        "ui":        "1.0",
        "setup":     "1.0",
        "licensing": "1.0",
        "closer":    "1.0",
    },
}


def version_string() -> str:
    return f"{PRODUCT_NAME} v{VERSION} ({BUILD_DATE})"
