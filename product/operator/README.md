# operator/ — Hermes Sales Operator (eingeschränkt)

> Spec-only. Kein Code in dieser Runde.

Die einzige Intelligenz, die der Kunde sieht. Ein **eingeschränkter, lokal
definierter** Operator — **nicht** der echte Hermes Prime, keine Kopie davon,
kein Zugriff auf Hermes Prime / OpenClaw / Sandra.

## Aufgaben
1. Freitext des Kunden verstehen.
2. In das feste Auftrags-Schema gießen (`ORDER_SCHEMA.md`).
3. Lücken erfragen (z. B. fehlende Region/Anzahl).
4. Auftrag zurückspiegeln + **Bestätigung** einholen.
5. Erst nach „Ja" eine **erlaubte** Bridge-Aktion auslösen.
6. Ergebnis menschlich berichten.
7. Bei Target Fill: Lücke erkennen, Varianten vorschlagen.

## Harte Grenzen
- Kann technisch nur Bridge-Aktionen aufrufen.
- Senden / CRM / Live-Mail sind in V1 **kein erreichbarer Pfad**.
- Keine Kommando-Syntax gegenüber dem Kunden.

## Geplante Bestandteile (später, als Code)
- `persona.md` — die eingeschränkte Operator-Persona (Doku, existiert hier).
- `ORDER_SCHEMA.md` — das Auftrags-Schema (Doku, existiert hier).
- `intake` — Freitext → Auftrags-Entwurf (V1).
- `confirm` — Bestätigungs-Gate (V1).
