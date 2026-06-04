# ui/ — Mini-UI (iPad-/futuristisch)

> Spec-only. Kein Code in dieser Runde.

Schlanke Oberfläche für Kunden, die **nicht** über Telegram arbeiten wollen.
Optisch ruhig/futuristisch (dunkel + Cyan-Akzent), iPad-artige Bedienung.
Designsprache an die vorhandenen Orb-Mockups angelehnt
(`../../b2bbot/ui/mockups/`).

## Genau vier Ansichten
1. **Status** — ein Auftrag, Fortschritt („72/100 sauber"), Live-Zustand, Orb-Signal.
2. **Leadliste** — saubere Karten (Firma, Ort, Telefon, Ansprechpartner, Score). Keine Rohdaten.
3. **Mail-Vorschau** — generierte Erst-Mails, lesbar, „Sieht gut aus"/„Anpassen".
4. **Report & Freigabe** — Zusammenfassung + **ein** Freigabe-Knopf.

## Harte Regeln
- Liest **nur** aufbereitete Ergebnisse (aus `../orders/` und Engine-Output).
- Startet selbst **keine** Live-Sends. Versand nur über den expliziten
  Freigabe-Klick (V2), der durch die Bridge geht.
- Zeigt **keine** Rohdaten, Debug-Spalten, Logs oder Engine-Interna.
- Nicht das bestehende Admin-Cockpit (`cockpit_server.py`) — das bleibt intern.

## Versionen
- V1: Ansicht 1 + 2 (Status, Leadliste), nur lesend.
- V2: Ansicht 3 + 4 (Mail-Vorschau, Report & Freigabe).
