"""Erweiterungs-Wissen — regionale und branchliche Varianten.

Gemeinsam genutzt von reporter.py (Vorschläge) und target_fill.py (echte Auffüllung).
Eine einzige Quelle der Wahrheit, damit Vorschlag und Ausführung übereinstimmen.
"""
from __future__ import annotations

# Region (lowercase-Schlüssel) → angrenzende Gebiete, Priorität absteigend
REGION_ERWEITERUNGEN: dict[str, list[str]] = {
    "nrw":                ["Niederrhein", "Ruhrgebiet", "Münsterland", "Bergisches Land"],
    "nordrhein-westfalen":["Niederrhein", "Ruhrgebiet", "Münsterland", "Bergisches Land"],
    "münchen":            ["Augsburg", "Ingolstadt", "Landshut", "Rosenheim"],
    "muenchen":           ["Augsburg", "Ingolstadt", "Landshut", "Rosenheim"],
    "hamburg":            ["Lübeck", "Kiel", "Bremen", "Lüneburg"],
    "berlin":             ["Potsdam", "Brandenburg", "Frankfurt (Oder)", "Cottbus"],
    "köln":               ["Bonn", "Düsseldorf", "Aachen", "Leverkusen"],
    "koeln":              ["Bonn", "Düsseldorf", "Aachen", "Leverkusen"],
    "frankfurt":          ["Wiesbaden", "Darmstadt", "Offenbach", "Mainz"],
    "stuttgart":          ["Karlsruhe", "Freiburg", "Heilbronn", "Ulm"],
    "bayern":             ["München", "Nürnberg", "Augsburg", "Regensburg", "Würzburg"],
    "baden-württemberg":  ["Stuttgart", "Karlsruhe", "Mannheim", "Freiburg", "Ulm"],
    "hessen":             ["Frankfurt", "Wiesbaden", "Kassel", "Darmstadt"],
    "niedersachsen":      ["Hannover", "Braunschweig", "Osnabrück", "Oldenburg"],
    "sachsen":            ["Leipzig", "Dresden", "Chemnitz", "Zwickau"],
}

# Zielgruppe (lowercase-Schlüssel) → verwandte Branchen, Priorität absteigend
BRANCHEN_VERWANDT: dict[str, list[str]] = {
    "handwerker":         ["Dachdecker", "Elektriker", "Sanitär", "Maler", "Schreiner"],
    "dachdecker":         ["Zimmerei", "Spengler", "Fassadenbau", "Handwerker"],
    "agenturen":          ["IT Dienstleister", "Beratungen", "Coaches", "Webdesigner"],
    "agentur":            ["IT Dienstleister", "Beratungen", "Coaches", "Webdesigner"],
    "it dienstleister":   ["Beratungen", "Agenturen", "Softwarehäuser", "Systemhäuser"],
    "beratungen":         ["IT Dienstleister", "Steuerberater", "Coaches", "Wirtschaftsprüfer"],
    "steuerberater":      ["Rechtsanwälte", "Unternehmensberater", "Wirtschaftsprüfer", "Buchhalter"],
    "coaches":            ["Trainer", "Berater", "Therapeuten", "Speaker"],
    "reinigung":          ["Hausmeisterdienste", "Sicherheitsdienst", "Gebäudeservice", "Facility"],
    "immobilienmakler":   ["Hausverwaltungen", "Bauträger", "Sachverständige", "Architekten"],
    "fitnessstudios":     ["Personal Trainer", "Physiotherapie", "Yoga-Studios", "Wellness"],
    "gastronomie":        ["Cafés", "Catering", "Hotels", "Bars"],
    "arztpraxen":         ["Zahnärzte", "Physiotherapie", "Heilpraktiker", "Tierärzte"],
}


def _suche_im_dict(quelle: dict[str, list[str]], schluessel: str) -> list[str]:
    """Findet Erweiterungen für einen (Teil-)Schlüssel. Tolerant gegenüber Varianten."""
    low = schluessel.lower().strip()
    # Exakte Treffer zuerst
    if low in quelle:
        return list(quelle[low])
    # Teilstring-Treffer (z. B. "handwerker betrieb" → "handwerker")
    for k, v in quelle.items():
        if k in low or low in k:
            return list(v)
    return []


def region_erweiterungen(region: str) -> list[str]:
    return _suche_im_dict(REGION_ERWEITERUNGEN, region)


def verwandte_branchen(zielgruppe: str) -> list[str]:
    return _suche_im_dict(BRANCHEN_VERWANDT, zielgruppe)
