# Hermes Sales Operator — Produktschicht (`product/`)

> **Status:** Spezifikation / Struktur. Noch **kein** ausführbarer Code.
> Diese Runde legt nur Ordner + Doku an. Keine Engine-Änderung, keine Live-Funktion.

## Was das ist

Die **kundenfähige Produktschicht** über zwei bestehenden, unveränderten Bausteinen:

- `../b2bbot/` — die reife B2B-Engine (Motor). **Wird nicht verändert.**
- `../ClouseAgent/` — der eigenständige Closer-Prototyp. **Wird nicht verändert, nicht vermischt.**

Der Kunde bedient **nicht** die komplizierte Engine. Er spricht in normaler Sprache
mit einem **eingeschränkten Hermes Sales Operator** (Telegram als Hauptbedienung,
optional eine schlanke Mini-UI). Der Operator macht aus freiem Text einen
**strukturierten Auftrag**, holt **Bestätigung** ein und lässt die Engine
**erst nach Freigabe** laufen.

## Leitprinzip

```
Kunde spricht normal
   → Operator macht daraus einen sauberen, bestätigten Auftrag
   → Bridge ruft die geprüfte Engine auf (nur erlaubte Aktionen)
   → Ergebnis menschlich berichtet + Freigabe vor jedem Versand
```

**Der Operator ist die einzige Intelligenz, die der Kunde sieht.
Die Engine bleibt eine Black Box hinter genau einer Brücke.
Der Closer ist ein Nachbar, kein Mitbewohner.**

## Ordnerübersicht

| Ordner | Zweck | Status |
|---|---|---|
| `operator/` | Hermes Sales Operator: Freitext → Auftrag → Bestätigung | Spec |
| `bridge/` | **Einzige** Brücke zur Engine (`mine.py`-Aufrufe, erzwingt Grenzen) | Spec |
| `telegram/` | Dünne Kunden-Front (natürliche Sprache, keine Kommando-Syntax) | Spec |
| `ui/` | Mini-UI: 4 Ansichten, iPad-/futuristisch | Spec |
| `orders/` | Strukturierte Aufträge + Status (datei-basiert) | Spec |
| `admin/` | Debug/Rohdaten — **nur intern**, nie im Kundenfluss | Spec |
| `closer/` | Nur Adapter-Konzept zu `ClouseAgent` (V2+), in V1 leer | Spec |

## Verbindliche Grenzen (gelten für die ganze Produktschicht)

- Kein Auto-Send, keine CRM-Pushes, keine Live-Mails ohne expliziten menschlichen Freigabe-Schritt.
- Keine `.env` lesen/kopieren/anzeigen. Keine echten Keys/Tokens. Nur `.env.example`.
- Hermes Prime / OpenClaw / Sandra: nie kopieren, nie verändern, nie referenzieren.
- Engine-Kern (`mine.py` / `cae` / `modules`): nicht anfassen — nur über `bridge/`.
- Keine Emilio-spezifischen Pfade hardcoden (siehe `PACKAGING.md`).

## Weiterlesen

- `SPEC.md` — vollständige Produktspezifikation (Architektur, Flüsse, Versionen).
- `PACKAGING.md` — Customer-Package-/Installer-Konzept + was die Architektur **heute** erfüllen muss.
- `operator/ORDER_SCHEMA.md` — das feste Auftrags-Schema (Fundament von allem).
