# SPEC — Hermes Sales Operator (Produktschicht)

> Reine Spezifikation. Kein Code. Beschreibt das Zielprodukt, nicht den heutigen Stand.

---

## 1. Produktziel (ein Satz)

Der Kunde sagt in normaler Sprache, was er will — der Hermes Sales Operator macht
daraus einen sauberen, bestätigten Auftrag und lässt die geprüfte B2B-Engine
**erst nach Freigabe** laufen, sichtbar in einer einfachen, futuristischen,
iPad-artigen Oberfläche.

---

## 2. Zielarchitektur

```
   KUNDE  (spricht normal — Telegram ODER Mini-UI)
     │
     ▼
┌─────────────────────────────────────────────┐
│  OPERATOR-SCHICHT  (das Herzstück)           │
│  Freitext → Auftrag → Bestätigung → Freigabe │
└───────────────┬─────────────────────────────┘
                │  nur strukturierte, erlaubte Aufträge
                ▼
┌─────────────────────────────────────────────┐
│  BRIDGE  (genau 1 Modul, wie engine.py heute)│
│  Auftrag → mine.py-Aufrufe                    │
│  erzwingt Sicherheitsgrenzen (kein Auto-Send)│
└───────────────┬─────────────────────────────┘
                ▼
┌─────────────────────────────────────────────┐
│  B2B-ENGINE  (BESTEHEND, unverändert)        │
│  mine.py / cae / modules                     │
└─────────────────────────────────────────────┘

  Parallel, NICHT vermischt:
  ┌───────────────────────┐   ┌────────────────────────┐
  │ MINI-UI (4 Ansichten) │   │ CLOSER (ClouseAgent)   │
  └───────────────────────┘   └────────────────────────┘
```

Das Brücken-Muster existiert bereits korrekt in `../b2bbot/telegram_seller/engine.py`
(Subprozess-Aufruf von `mine.py`, fasst den Kern nicht an). Die neue `bridge/`
übernimmt genau dieses Muster — aber **ohne** Send-/Approve-/Reply-Pfade in V1.

---

## 3. Die vier Schichten

### 3.1 Operator (eingeschränkter Hermes Sales Operator)
- Eigene, schmale Persona (`operator/persona.md`). **Nicht** der echte Hermes Prime.
- Kein Zugriff auf Hermes Prime, OpenClaw, Sandra. Nichts wird kopiert.
- Aufgaben: Freitext verstehen → Auftrags-Schema füllen → Lücken erfragen →
  Bestätigung einholen → erlaubte Aktion über Bridge auslösen → Ergebnis
  menschlich berichten → bei „Target Fill" Lücken erkennen + Varianten vorschlagen.
- Hart eingeschränkt: kann technisch nur Bridge-Aktionen aufrufen. Senden/CRM/
  Live-Mail sind in V1 kein erreichbarer Pfad.

### 3.2 Bridge (einzige Brücke zur Engine)
- Übersetzt einen bestätigten Auftrag in konkrete `mine.py`-Aufrufe.
- Kennt in V1 genau drei Aktionen: **suchen**, **Status lesen**, **Leadliste lesen**.
- Kennt **nicht**: senden, approve, process-replies, CRM-Push.
- Erzwingt alle Sicherheitsgrenzen technisch (nicht nur per Prompt).

### 3.3 Telegram (Hauptbedienung)
- Natürliche Sprache, **keine** `|`-Kommando-Syntax mehr für den Kunden.
- Pflicht-Bestätigung vor jedem Lauf.
- Hintergrund-Läufe mit automatischer Rückmeldung (Muster existiert in `leads_cmd.py`).

### 3.4 Mini-UI (optional, für Kunden ohne Telegram)
- Genau vier Ansichten, ruhig/futuristisch (dunkel + Cyan, Orb-Designsprache aus
  `../b2bbot/ui/mockups/`).
- Liest **nur** aufbereitete Ergebnisse. Startet selbst keine Live-Sends.

---

## 4. Kundenfluss (Telegram, Beispiel)

```
Kunde:    "Such mir 100 saubere Leads für Website-Angebote an Handwerker in NRW."

Operator: "Verstanden. Auftrag-Entwurf:
   🎯 Zielgruppe:        Handwerker
   📍 Region:            NRW
   🔢 Lead-Anzahl:       100
   💼 Angebot:           Website-Erstellung
   ✅ Qualität:          Telefon Pflicht, persönl. Ansprechpartner bevorzugt,
                         keine Konzerne, keine Dubletten
   🤖 Erlaubte Aktion:   NUR suchen & aufbereiten (kein Mailversand)
   Passt das? 'Ja, starten' oder sag, was ich ändern soll."

Kunde:    "Ja, starten"
Operator: "🔎 Läuft im Hintergrund. Ich melde mich, sobald sauber befüllt."
...
Operator: "✅ Fertig. 72/100 sauber (Telefon + valide). 28 fehlen — NRW-Handwerker
           ist enger als 100. Vorschlag: Niederrhein dazu, oder Zweitbranche
           'Dachdecker'? 👉 /freigabe für die Mail-Vorschau."
```

---

## 5. Mini-UI — die vier Ansichten

1. **Status** — ein Auftrag, Fortschritt („72/100 sauber"), Live-Zustand, Orb-Signal.
2. **Leadliste** — saubere Karten (Firma, Ort, Telefon, Ansprechpartner, Score). Keine Rohdaten.
3. **Mail-Vorschau** — generierte Erst-Mails, lesbar, „Sieht gut aus"/„Anpassen".
4. **Report & Freigabe** — Zusammenfassung + **ein** Freigabe-Knopf. Erst dieser Klick erlaubt Senden.

---

## 6. Admin-Fluss (intern, getrennt)

- Bestehendes `cockpit_server.py` + Premium-Dashboard = **Admin-Werkzeug**, nicht ausliefern.
- Rohdaten, `run_intent_*.py`, alle `smoke_*.py`, Funnel-Diagnosen, Logs → intern.
- Regel: Kundensicht geht **immer** durch Operator/Bridge. Admin greift direkt auf die Engine zu — der Kunde nie.

---

## 7. Rollen

| Baustein | Rolle | V1 |
|---|---|---|
| **B2B-Engine** | Motor, Black Box, unverändert | aktiv über Bridge |
| **Operator** | einzige sichtbare Intelligenz | aktiv |
| **Closer (ClouseAgent)** | Nachbar, eigenständig | nur konzeptionell, nicht im Telegram-Fluss |
| **Hermes Sales Operator-Persona** | eingeschränkt, lokal definiert | aktiv, **nicht** Hermes Prime |

---

## 8. Target Fill Mode

- Technische Basis existiert bereits: **Target-Count-Loop / Multi-Round-Discovery**
  in der Engine (`output/latest/lead_funnel_diagnostics.json`, Telefon-Pflicht).
- Der Operator **orchestriert und berichtet** das nur kundenfreundlich — er baut es nicht neu.
- Verhalten: Lücke erkennen („950 fehlen") → neue Suchvarianten vorschlagen/später
  ausführen → Dubletten vermeiden → Qualität vor Menge → stoppen, wenn Zielgruppe
  ausgeschöpft → sauber berichten.
- Voller Ausbau: **V2**.

---

## 9. Versionen

### V1 — kleinster sicherer MVP
1. Operator-Intake: Freitext → Auftrags-Schema.
2. Bestätigungs-Gate (erst nach „Ja" weiter).
3. Bridge: bestätigter Auftrag → `mine.py`-**Suche** (kein Senden).
4. Telegram als Hauptbedienung (natürliche Sprache).
5. Ergebnis-Bericht („X von N sauber, Y fehlen").
6. Mini-UI nur lesend: Status + Leadliste.

Nicht in V1: Auto-Send, CRM, Closer, Mail-Editing, Multi-Mandant.

### V2
- Mail-Vorschau + Freigabe (kontrollierter Send-Pfad, nur nach menschlichem Klick).
- Target Fill Mode voll (Lücken-Report, Varianten, Dedup über Läufe, Stop bei Erschöpfung).
- Report-Ansicht (Ansicht 4) komplett.
- Kunde/Admin-Trennung final.

### V3
- Closer-Anbindung als optionales Modul (über UI startbar, nie im B2B-Telegram-Fluss).
- Rückfluss Call-Ergebnis → Follow-up/CRM, nur nach separater Freigabe.
- Multi-Mandant / Pakete (Feature-Flag-Gerüst existiert in `bot_config.py`).
- Optional: Sprach-Bedienung des Operators (**ohne** Hermes-Prime-Kopplung).

---

## 10. Sicherheitsgrenzen (technisch in der Bridge verankert)

- Kein Auto-Send (Send-Pfad existiert in V1 in der Bridge gar nicht).
- Keine CRM-Pushes, keine Live-Mails ohne expliziten menschlichen Freigabe-Schritt.
- Keine `.env` lesen/kopieren/anzeigen, keine Keys sichtbar — auch nicht in Telegram-Chats.
  (Der heutige `/setup`-Flow, der das SMTP-Passwort im Chat abfragt, wird für das
  10/10-Produkt durch einen sichereren Weg ersetzt — eigenes To-do, hier nicht angefasst.)
- Hermes Prime / OpenClaw / Sandra: nie kopieren/verändern/referenzieren.
- Engine-Kern nicht anfassen — nur über Bridge.
- Kein `git clean`, kein `reset --hard`, kein `git add .`, keine großen Refactors.

---

## 11. Stop-Regeln

Sofort anhalten und nachfragen, wenn:
- die Engine-Kernlogik verändert würde;
- ein Send-/CRM-/Live-Mail-Pfad in V1 entstünde;
- etwas Richtung Hermes Prime / OpenClaw / Sandra koppelt oder kopiert;
- Closer und B2B-MVP vermischt werden;
- `.env`/Keys gelesen, kopiert oder angezeigt werden müssten;
- ein großer Refactor statt einer additiven neuen Datei nötig erscheint;
- der Kunde im Fluss Kommando-Syntax oder Rohdaten sähe.

---

## 12. Packaging

Siehe `PACKAGING.md` — das Customer-Package-/Installer-Konzept und die
Architektur-Vorgaben, die **schon heute** gelten müssen, damit ein Installer
später sauber möglich ist (keine Doppelarbeit).
