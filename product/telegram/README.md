# telegram/ — Kunden-Front (Hauptbedienung)

> Spec-only. Kein Code in dieser Runde.

Die dünne, kundenseitige Telegram-Front. **Hauptbedienung** des Produkts.
Sie reicht freien Text an den Operator durch und gibt dessen Antworten zurück.

## Prinzipien
- **Natürliche Sprache**, keine `|`-Kommando-Syntax für den Kunden.
- Pflicht-Bestätigung vor jedem Lauf (über Operator-Gate).
- Hintergrund-Läufe mit automatischer Rückmeldung
  (Muster existiert in `../../b2bbot/telegram_seller/commands/leads_cmd.py`).
- Owner-Lock + Single-Instance-Lock beibehalten
  (Muster in `../../b2bbot/telegram_seller/bot.py`).

## Wiederverwendung
- Das bestehende `telegram_seller`-Gerüst (Registry, tg_api, Locks, Lizenz,
  Feature-Flags) ist eine **gute Vorlage**. Die neue Front ersetzt die
  **Kommando-UX** durch die **Operator-Gesprächs-UX** — additiv, ohne den
  bestehenden Bot kaputt zu machen.

## Sicherheit
- Kein SMTP-Passwort/Token im Klartext-Chat (heutiger `/setup`-Flow wird ersetzt —
  siehe `../PACKAGING.md`, Abschnitt 2.3).
- Keine Engine-Befehle, Pfade oder Logs an den Kunden ausgeben.
