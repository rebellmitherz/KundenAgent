# KundenAgent – B2B Operator-System

## Hauptprojekte (Priorität)
- Hermes Prime
- OpenClaw / Sandra
- Operator-System
- MCP / lokale Automationsstruktur
- KundenAgent (B2B Bot)
→ Ziel: schnelle Umsatzfähigkeit

## KundenAgent Fokus
B2B Bot für Client Acquisition, Automation, Operator-Integration

## Pfad
C:\Users\micha\Desktop\KundenAgent

## Tech-Stack
[ergänzen]

## Aktueller Stand
[ergänzen]

## Offene TODOs
- [ ] 

## Letzte Änderungen
- 

## Arbeitsregeln
- Vor Code/Repo-Arbeit: Konkreten Ordner/Pfad abfragen
- Keine alten Annahmen, ein Problem nach dem anderen
- Keine großen Refactors ohne Freigabe
- Keine Live-Send/CRM/Mail/Kalender-Aktionen ohne Bestätigung
- Bei Unklarheit: Prüfen statt Raten

## Nicht der Fokus
TikTok, RebelBot, Video-Automation (nur wenn explizit angesprochen)

## Session-Abschluss (PFLICHT für Code-Agenten)
Vor dem Beenden JEDER Session mit echter Arbeit (Code, Daten, Assets, Config)
MÜSSEN diese OPERATOR_SYSTEM-Übergabedateien aktualisiert werden — nicht nur der Handoff:
- `LAST_SESSION_SUMMARY.md` — was getan + warum (für Hermes/nächste Session)
- `CURRENT_CONTEXT.md` — aktueller Stand + nächste Aktion
- `CODE_AGENT_HANDOFF.md` — bei Code-/Datei-/Asset-Arbeit (Kollisions-/Übergabe-Notiz)
- `B2B_CURRENT_TRUTH.md` — nur bei Engine-Lauf nötig; sonst hält der Truth-Watcher (Autostart) sie frisch

Ein **Stop-Hook** (`OPERATOR_SYSTEM/session_end_check.py`, registriert in `~/.claude/settings.json`)
erinnert automatisch, falls KundenAgent-Arbeit erkannt wird, aber `LAST_SESSION_SUMMARY.md`
älter ist. Das Sicherheitsnetz ersetzt NICHT die Sorgfalt — der Inhalt kommt vom Agenten.
