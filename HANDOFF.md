# ÜBERGABE — Hermes Sales Operator → Autonomer Kampagnen-Agent

> Diese Datei ist die **einzige Quelle der Wahrheit** für den Projektstand.
> Jede neue Session liest zuerst diese Datei, dann `git log`, dann beginnt sie.
> Nach jedem Schritt wird diese Datei aktualisiert (Stand + erledigt-Haken).

---

## 0. SOFORT BEIM START (jede neue Session)

```powershell
cd C:\Users\micha\Desktop\KundenAgent
git status
git log --oneline -8
```

Dann diese Datei zu Ende lesen. **Nichts raten** — bei Unklarheit Code lesen.

**REGEL: Bei jeder Antwort am Ende nennen, welches Modell + Stufe der nächste
Schritt braucht** (z. B. „Nächster Schritt: Phase A.2 → Opus 4.8 / High").
Der User wechselt das Modell selbst. High-/Denk-Schritte = Opus, Routine = Sonnet 4.6.

---

## 1. ARBEITSUMGEBUNG

- Ordner (NUR hier): `C:\Users\micha\Desktop\KundenAgent`
- Sprache: **Deutsch**. Windows 11, PowerShell.
- Python-Tests immer mit `PYTHONUTF8=1` (Konsole = cp1252, sonst Emoji-Crash).
- GitHub: https://github.com/rebellmitherz/KundenAgent (branch `master`)
  - git user: Michael / rebellmitherz@gmail.com (bereits gesetzt)
  - **Nach jedem grünen Schritt: committen.** Push macht der USER selbst
    (Classifier blockiert Push durch den Agenten) — Agent sagt nur:
    „Bitte `git push` ausführen."

---

## 2. HARTE SICHERHEITSGRENZEN (NIEMALS VERLETZEN)

- **Hermes Prime / OpenClaw / Sandra**: nie kopieren, ändern, referenzieren.
  Der Agent den wir bauen ist ein NEUER, EIGENSTÄNDIGER, eingeschränkter Agent —
  keine Kopplung an Hermes Prime.
- **Engine-Kern** (`b2bbot/mine.py`, `b2bbot/cae`, `b2bbot/modules`): NICHT anfassen.
  Zugriff NUR über die Bridge (Subprozess).
- **Kein Auto-Send ohne menschlichen Freigabe-Klick.** Senden, CRM, Live-Mail,
  Termin-Buchung = immer hartes Tor mit menschlicher Bestätigung.
- **Keine `.env` lesen/kopieren/anzeigen. Keine API-Keys ausgeben/loggen.**
- Kein `git clean`, kein `reset --hard`, kein `git add .`, keine großen Refactors.
- **Closer (`ClouseAgent/`)** nicht mit B2B-Bot mischen. Bleibt eigenständig.
- Kunde sieht nie: Kommando-Syntax, Rohdaten, Engine-Interna, Logs.
- Additiv arbeiten: neue Dateien, keine Umbauten am Bestehenden außer nötig.

---

## 3. WAS DAS PRODUKT IST

Kundenfähige Produktschicht (`product/`) über zwei bestehenden, unveränderten Bots:
- `b2bbot/` = reife B2B-Lead-Engine (Motor, Black Box, Entry = `mine.py`)
- `ClouseAgent/` = eigenständiger Live-Closer (Audio + STT, Entry = `app.py`)

Architektur:
```
Kunde → Operator/Agent → Bridge (einzige Engine-Leitung) → b2bbot-Engine
Mini-UI (Port 8767) und Closer laufen parallel, NICHT vermischt.
```

Engine-Aufruf: `python mine.py -i "<Branche>" -c "<Ort>" -n <Anzahl> --mode local`
- Pipeline `outreach_pipeline.json` akkumuliert + dedupliziert (stabiler entry_key).
- „sendbar" = `ready_to_send=yes` UND nicht `do_not_resend`, Telefon Pflicht.
- Engine hat eigene Gates: preview→approve→send, Blocklists, MX-Validierung.
  Wir VERPACKEN das, ersetzen es nicht.

---

## 4. STAND — SCHRITTE 0–13 + PHASEN A–D + CLOSER ALLE GRÜN ✅

Alles in `product/` (additiv, b2bbot/ClouseAgent unverändert). **294 Tests grün.**
(Schritte 0–13 = Produktschicht: 121 Tests; Phasen A–D + Closer = +173 Tests.)

```
product/
  README.md SPEC.md PACKAGING.md HANDOFF.md(diese)  version.py
  product_config.example.json   start_operator.bat
  operator/   order_schema, intake, confirm, reporter, expansion_maps,
              target_fill, llm_anthropic, persona.md
  bridge/     engine_bridge.py  (EINZIGE Engine-Leitung; Subprozess)
              V1: suchen(), status_lesen(), leads_lesen()
              V2-Stubs: vorschau_lesen(), freigabe_ausfuehren()  (approve+send,
              nur nach explizitem UI-POST). KEIN crm_push, KEIN auto_reply.
  telegram/   bot.py (Owner-Lock, Single-Instance-Lock, /status /hilfe,
              natürliche Sprache), dialog.py (Zustandsmaschine
              IDLE→INTAKE→CONFIRMING→RUNNING→IDLE), config.py
  ui/         server.py (stdlib HTTP, Port 8767), dashboard.html (iPad-futuristisch,
              dunkel/Cyan/Orb). Tabs: Status, Leads, Mail-Vorschau, Freigabe,
              Closer, Einrichtung. Admin-Token-Schutz + Feature-Gates.
  setup/      onboarding.py (getpass-Wizard, ui_token+license_key), smtp_store.py
  licensing/  features.py (STARTER/PRO/ENTERPRISE), license.py (HMAC-Verify),
              keygen.py (NUR Verkäufer, in .gitignore)
  closer/     closer_adapter.py (ClouseAgent als Subprozess, Secret-Filter)
  packaging/  check_install.py (Installations-Check), package.py (ZIP-Build)
  agent/      DAS GEHIRN (Phase A): tools.py (7 Werkzeuge, nur lesen+suchen,
              Sende-Werkzeuge gesperrt), brain.py (Agent-Loop + ClaudePolitik
              mit deterministischem Fallback + Guardrails), memory.py
              (persistenter Lauf-Speicher data/agent/), runner.py (geteilte
              Anbindung für Telegram + UI). Senden bleibt Mensch-Tor.
  admin/ orders/ data/   (Doku + Laufzeitdaten; data/agent/ = Agent-Läufe)
```

Config-Felder (`product_config.json`, NICHT im Git):
`bot_token, owner_chat_id, engine_dir, data_dir, anthropic_api_key,
license_key, ui_token`

Test-Suiten (alle standalone, `PYTHONUTF8=1 python <pfad>`):
```
product/setup/test_onboarding.py      28
product/setup/test_trennung.py        13
product/closer/test_closer_adapter.py 22
product/licensing/test_licensing.py   27
product/packaging/test_packaging.py   31
product/agent/test_agent.py           31   (Phase A.1 — Werkzeuge)
product/agent/test_brain.py           26   (Phase A.2 — Agent-Loop)
product/agent/test_memory.py          18   (Phase A.3 — Lauf-Speicher)
product/agent/test_runner.py           8   (Phase A.5 — Runner)
product/telegram/test_dialog_agent.py  4   (Phase A.5 — Dialog-Anbindung)
product/bridge/test_freigabe.py        6   (Phase B.1 — Sende-Tor Bridge)
product/agent/test_freigeben.py        7   (Phase B.1 — Runner-Freigabe)
product/bridge/test_antworten.py       5   (Phase B.2 — Antworten lesen)
product/agent/test_replies.py          7   (Phase B.2 — Antworten-Bericht)
product/bridge/test_followup.py        6   (Phase B.3 — Nachfassen Bridge)
product/agent/test_nachfassen.py       8   (Phase B.3 — Runner-Nachfassen)
product/agent/test_funnel.py          21   (Phase C — Trichter + Kampagnen)
product/bridge/test_kampagne.py        5   (Phase C — Rohdaten read-only)
product/agent/test_notifier.py        13   (Phase D — Notifier + Watcher)
product/telegram/test_closer_bot.py    8   (Closer — Telegram-Steuerung)
                                     ----
                                     = 294 grün
```

WICHTIG (Engine-Sende-Modell, B.1): Ein echter SMTP-Versand feuert NUR mit
`OUTREACH_SEND_CONFIRMED=true` in der Subprozess-Umgebung. Die Bridge setzt das
ausschließlich scoped beim Send-Schritt und nur bei `bestaetigt=True` (Mensch-
Klick). `runner.freigeben()` verlangt zusätzlich Status `wartet_auf_mensch`.
Der Agent-Loop sendet NIE (Sende-Werkzeuge gesperrt). UI: `/api/agent/freigeben`.

WICHTIG (Antworten-Modell, B.2): `bridge.antworten_lesen()` LIEST nur
`output/reply_queue.json` (kein Subprozess, kein Versand). Diese Datei füllt die
Engine, wenn `mine.py --outreach process-replies` läuft (IMAP-Abruf + Klassi-
fizierung). Den Abruf-TRIGGER haben wir bewusst NICHT gebaut (process-replies
kann mit `REPLY_AUTO_SEND=true` Auto-Antworten senden). Falls später nötig: nur
mit `REPLY_AUTO_SEND=false` scoped — analog zum Sende-Tor in B.1.

Was schon LÄUFT:
- ✅ **Agent-Loop (Phase A)**: Ziel → denkt (Claude/det.) → sucht + füllt selbst
  auf → hält am harten Tor. Persistent. In Telegram + UI verdrahtet.
- ✅ Suche + Target Fill (Lücken erkennen, Varianten vorschlagen)
- ✅ Mail-Vorschau + Freigabe-Gate (UI)
- ✅ Bridge zu mine.py
- ✅ `llm_anthropic.py` (optionaler Claude-Adapter, Key nur aus os.environ)
- ✅ Senden nach Freigabe (B.1) — human-gated, fail-closed, OUTREACH_SEND_CONFIRMED
- ✅ Antworten lesen + melden (B.2) — read-only aus reply_queue.json
- ✅ Nachfassen (B.3) — human-gated followups + read-only Fällig-Vorschau
- ✅ Kampagnen-Trichter (C) — je Lead Stufe gefunden→bereit→angeschrieben→
  geantwortet→termin, aus Pipeline+reply_queue; persistenter Verlauf/Trend
- ✅ Push-Meldungen (D) — Watcher meldet Termin-Signale, offene Tore, Nachfassen
  fällig via Telegram; dedupliziert; kein Auto-Send
- ✅ Closer (ClouseAgent) per Telegram steuerbar (`closer starten/stoppen/status`),
  bei Termin-Signal automatisch erwähnt; eigenständig, NICHT im B2B-Fluss (§2)
- ⬜ Versand-Abruf-Trigger (process-replies/IMAP) bewusst NICHT gebaut (siehe §4-Notiz)

---

## 5. DIE NEUE VISION — AUTONOMER KAMPAGNEN-AGENT

Nicht 5 Bots. **EIN zielgetriebener Agent**, der eine Kampagne zu Ende führt:

```
Kunde: "1000 Handwerker NRW, anschreiben, bis zum Termin betreuen"
Agent: findet 20 → erkennt 980 fehlen → sucht selbst weiter (Regionen/Zweitbranchen)
       950/1000 → fragt: "Senden?"  (HARTES TOR)
Kunde: "ja"
Agent: sendet → überwacht Antworten → plant Follow-up selbst
       "Termin-Anfrage von Firma Y" → meldet dem Kunden  (HARTES TOR)
```

**Ziel rein. Agent denkt, handelt, fragt nur an harten Toren.**

### Warum so (= zukunftssicher, der eigentliche Wert)
- **Claude ist das Gehirn** (Reasoning), nicht hartcodierte Wenn-Dann-Logik.
- **Agent-Loop**: Lage lesen → entscheiden → handeln → berichten → wiederholen.
- **Gedächtnis**: jeder Lead im Funnel, über Neustarts hinweg persistent.
- Das ist das Muster von Claude Agent SDK / OpenClaw — Industrie-Standard.
  Eine Zustandsmaschine wäre in 1 Jahr Müll; ein Agent-Loop ist das Fundament.

---

## 6. QUALITÄTS-LATTE (das „unfassbar, und 5k/Monat ist billig"-Gefühl)

Jeder Schritt muss diese Latte reißen — sonst nicht abgeben:
1. **Autonomie spürbar**: Der Agent löst Probleme selbst, bevor der User fragt.
   („20 von 1000? Ich kümmere mich." — nicht „Fehler: nur 20 gefunden.")
2. **Sprache wie ein Top-Vertriebsleiter**: ruhig, kompetent, proaktiv, nie technisch.
3. **Immer ehrlich**: nie faken. Lücke = Lücke, klar benannt + Lösungsweg.
4. **Sicht-Trennung sauber**: Kunde sieht Magie, du (Admin) siehst Maschinenraum.
5. **Jeder harte Schritt bestätigt**: Senden/Termin nie ohne menschliches Ja.
6. **Alles getestet, grün, committet.** Kein „müsste klappen".

---

## 7. DER PLAN — 4 PHASEN (A zuerst)

```
A  DAS GEHIRN        Agent-Loop: Ziel → Claude denkt → wählt Bridge-Werkzeug → handelt
B  LOOPS SCHLIESSEN  Senden / Antworten-lesen / Follow-up real an Bridge anbinden
C  GEDÄCHTNIS        Kampagnen-State: jeder Lead im Funnel, persistent
D  TORE + MELDUNGEN  "Senden?" / "Termin von X" → Telegram + UI Push
```

### >>> JETZT: PHASE A — DAS GEHIRN <<<  (Opus 4.8 / High)

Neuer Ordner `product/agent/`. Ziel: aus dem Operator wird ein echter Agent.

A.1 `agent/tools.py` — Bridge-Aktionen als „Werkzeuge" deklarieren
    (Name, Beschreibung, Parameter-Schema, Ausführfunktion). In V1 nur LESEND +
    SUCHEN/TARGET_FILL — KEIN Senden (hartes Tor bleibt Mensch).
A.2 `agent/brain.py` — Agent-Loop:
    Eingabe = Ziel (Auftrag aus order_schema) + aktueller Engine-Stand (Reporter).
    Claude (llm_anthropic) entscheidet die nächste Aktion aus der Werkzeug-Liste.
    Loop: lesen → entscheiden → handeln → bewerten → (weiter oder fertig/fragen).
    Guardrails: nur erlaubte Werkzeuge; bei „Senden nötig" → STOP + Mensch fragen.
A.3 `agent/memory.py` — schlanker Lauf-Speicher (Ziel, getane Schritte, Funnel-Zahlen).
    JSON in `data/agent/`. (Voller Funnel-State = Phase C.)
A.4 Tests `agent/test_agent.py` — Claude GEMOCKT (deterministisch), läuft OHNE Key.
    Fälle: Ziel erreicht / Lücke→Target-Fill / Erschöpfung→ehrlich stop /
    Senden-nötig→Mensch-Tor. Min. 20 Tests, grün.
A.5 Dünne Anbindung: Telegram + Mini-UI können den Agenten auf einen Auftrag setzen
    (noch keine harten Sends). Live verifizieren (UI Snapshot, PYTHONUTF8=1).

Wichtig in A: Der Agent ist ein **Aufsatz** auf die bestehende Bridge/Operator —
nichts Bestehendes zerstören. `llm_anthropic.py` wird vom optionalen Helfer zum
Reasoning-Kern (mit deterministischem Fallback, damit Tests ohne Key laufen).

---

## 8. ARBEITSWEISE (jeder Schritt)

1. Erst prüfen was existiert (lesen), dann additiv bauen.
2. Mit echten Tests verifizieren (`PYTHONUTF8=1`). UI live (Snapshot/Screenshot).
3. Grün → committen (sprechende Message). User um `git push` bitten.
4. Diese HANDOFF.md aktualisieren (Stand + Haken).
5. Modell + Stufe für den nächsten Schritt nennen.

---

## 9. STARTBEFEHLE

```powershell
# Mini-UI:   $env:PYTHONUTF8=1; python product/ui/server.py   (Port 8767)
# Telegram:  python product/telegram/bot.py   (braucht product_config.json)
# Check:     $env:PYTHONUTF8=1; python product/packaging/check_install.py
# Alle Tests laufen lassen (Beispiel):
#   $env:PYTHONUTF8=1; python product/licensing/test_licensing.py
```

---

## 10. STAND-PROTOKOLL (hier abhaken)

```
0–13  Produktschicht + Lizenz + Paket .... ✅ (121 Tests grün, auf GitHub)
A     Das Gehirn (Agent-Loop) ............ ✅ FERTIG
  A.1 agent/tools.py + 31 Tests ......... ✅ (commit ce82c9e, Review 456de72)
  A.2 agent/brain.py + 26 Tests ......... ✅ (commit 724f2b1)
  A.3 agent/memory.py + 18 Tests ........ ✅ (commit b87969b)
  A.4 Tests agent/brain/memory/runner ... ✅ (83 Agent-Tests, Claude+Engine gemockt)
  A.5 agent/runner.py + Telegram + UI ... ✅ (commit f0fbcda, live verifiziert)
B     Loops schließen (Send/Reply/Followup) ✅ FERTIG
  B.1 Senden nach Freigabe (human-gated)  ✅ (commit 34e2c44, +13 Tests)
  B.2 Antworten lesen + melden (read-only) ✅ (commit 47860a6, +12 Tests)
  B.3 Nachfassen (human-gated followups) . ✅ (commit ffe7743, +14 Tests)
C     Kampagnen-Gedächtnis ............... ✅ (commit c9198f9, +26 Tests)
D     Tore + Push-Meldungen .............. ✅ (commit f09a2b2, +13 Tests)
Closer Telegram-Steuerung ............... ✅ (commit cce0cdc, +8 Tests, 294 total)

NACH-ÜBERGABE (Live-Test mit echten Daten, 05.06.):
Antwort-Details + Termin abschließen .... ✅ (commit 9391240, +15 Tests, 309 total)
  - bridge.antworten_lesen: +von/postfach/gesendet_am/auto_antwort (keine Roh-IDs)
  - replies: termin_detail_bericht (Original-Mail + voller Text) + antwort_detail_bericht
  - agent/erledigt.py: erledigte Termine agent-lokal, raus aus Push/Überblick/Detail
  - Telegram-Befehle: 'Mail zeigen', 'Termin aufbereiten', 'Termin abschließen <Firma>'
Desktop-Button 'Hermes UI' .............. ✅ (commit cf88262, start_ui.bat öffnet Browser)
D: Agent in der UI + Auftrag aus Browser  ✅ (commit e7638dd, +5 Tests, 314 total)
  - memory.lauf_anlegen + runner.starten_im_hintergrund (async, stoppt am harten Tor)
  - server: POST /api/agent/auftrag + /api/agent/termin-abschliessen (admin-gated)
  - dashboard.html: Tabs Kampagne (Trichter), Antworten (Detail-Karten), Neuer Auftrag
  - Hinweis: Browser muss http://127.0.0.1:8767 sein (IPv4), nicht localhost (IPv6)

E: Aktiver Antwort-Abruf (fail-closed) ... ✅ (commit 6b21cba, +8 Tests, 322 total)
  - bridge.antworten_abrufen: process-replies, ALLE Auto-Send-Gates scoped AUS
    (REPLY_DRY_RUN=1 + REPLY_AUTO_SEND=false + ... ) → abrufen, nie senden
  - watcher auto_abruf=True: Bot holt Antworten alle 5 Min selbst (vollautomatisch)
  - Telegram 'Antworten abrufen' + UI-Button + POST /api/agent/antworten-abrufen
  - Faehigkeit zum Auto-Reply bleibt in der Engine (Flags), Produktregel haelt sie aus
Branding: Hermes → Rebellsystem ......... ✅ (commit 6b21cba, nur Sichtflaechen;
  Guardrail-Hinweise 'Hermes Prime/OpenClaw/Sandra' bewusst unveraendert)

ALLE PHASEN A–E FERTIG. 322 Tests grün.
```
