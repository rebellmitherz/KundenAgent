# bridge/ — einzige Brücke zur Engine

> Spec-only. Kein Code in dieser Runde.

Die **einzige** Verbindung zwischen der Produktschicht und der B2B-Engine.
Übersetzt einen **bestätigten** Auftrag in konkrete `../../b2bbot/mine.py`-Aufrufe
(Subprozess) — exakt das bewährte Muster aus
`../../b2bbot/telegram_seller/engine.py`, aber bewusst eingeschränkt.

## V1 — genau drei Aktionen
| Aktion | Engine-Aufruf (Konzept) | Wirkung |
|---|---|---|
| `suchen` | `mine.py -i … -c … -n … --mode local` | Leads suchen + aufbereiten |
| `status_lesen` | liest `output/…json` | Fortschritt/Zahlen |
| `leads_lesen` | liest aufbereitete Leadliste | für UI/Bericht |

## V1 — NICHT vorhanden (kein Pfad)
- `senden`, `approve`, `process-replies`, CRM-Push.
- Diese existieren in V1 in der Bridge **gar nicht** — nicht nur „deaktiviert".

## Pflichten der Bridge
- Erzwingt Sicherheitsgrenzen **technisch** (nicht nur per Prompt).
- Fasst den Engine-Kern **nicht** an — nur Subprozess + Datei lesen.
- Engine-Pfad **konfigurierbar** (kein hardcodierter Nutzerpfad — siehe `../PACKAGING.md`).
- Gibt nie Rohdaten/Logs/Secrets an die Kundensicht weiter.

## V2 (später)
- `vorschau_erstellen` (Mail-Preview, kein Versand).
- `senden_nach_freigabe` — **nur** nach separatem menschlichem Freigabe-Klick.
