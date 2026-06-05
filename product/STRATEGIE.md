# Produkt- & Vertriebsstrategie — Rebellsystem Akquise-Plattform

> Festgehalten, damit die Architektur **nicht** versehentlich auf ein einziges
> Geschäftsmodell festgelegt wird. Diese Datei ist Leitplanke für künftige
> Entscheidungen — kein Implementierungsauftrag.

---

## 1. Was das Produkt ist

Eine **branchenunabhängige Multi-Mandanten-B2B-Akquise-Plattform**. Jeder Kunde
ist ein **isolierter Agent**: eigene Zielgruppe, eigenes Postfach/Engine, eigene
Pipeline, eigene Historie, eigenes Reporting, eigene Lizenz. Der Agent ist
**signal-first** (geprüfte Termine statt Lead-Masse) und **human-gated**
(Senden/Termin nie ohne menschliches Ja).

---

## 2. Aktuelles Modell (Phase 1): Managed SaaS / Vermietung

- **Der Betreiber (du) betreibt die Engine.** Der Kunde bekommt **keinen**
  proprietären Engine-Code.
- Kunde zahlt **monatlich**.
- Kunde erhält: **Ergebnisse, Reports, Hot Handoffs** (Termin-Signale), Bedienung
  zunächst über Telegram; ein echtes Kundenportal kommt später.
- Bedienung heute: pro Kunde ein isolierter Agent, Routing über die Telegram-
  `owner_chat_id`. Betreiber-Gesamtsicht via `/plattform`.

---

## 3. Hybrid bleibt offen (bewusst nicht verbaut)

Die Architektur muss alle drei Wege weiter zulassen:

1. **Managed SaaS / Vermietung** durch den Betreiber — *jetzt aktiv*.
2. **Kundenportal** mit Login + Connector zur isolierten Mandanten-Laufzeit —
   *später (F8)*.
3. **Enterprise / Self-Hosted** oder Lizenzverkauf — *später, optional*.

Was das ermöglicht (bereits gebaut):
- **Harte Mandanten-Isolation** (`product/platform/mandant.py`): eigenes
  data_dir, kein geteiltes engine_dir, Slug-IDs.
- **Plattform-Orchestrierung** (`plattform.py`): pro Mandant isolierter
  Runner+Bridge; `bridge_factory`/`reporter_factory` injizierbar → austauschbar
  für andere Deployment-Formen.
- **Bridge als einzige Engine-Leitung** (`bridge/engine_bridge.py`): Engine ist
  entkoppelt; ein Connector/Remote-Backend lässt sich später dahinter setzen,
  ohne die Produktschicht umzubauen.
- **Zwei strikt getrennte Pakete** (`packaging/package.py`): Betreiber-Paket
  (voll lauffähig, intern) vs. Kunden-/SaaS-Paket (kein Quellcode).

---

## 4. Bewusst zurückgestellt (NICHT jetzt bauen)

- **F8 — Echtes Kunden-Frontend + Connector.** Erfordert zuerst eine klare
  Produkt-/Vertriebsentscheidung und einen Design-Vorschlag (Web-Stack,
  Auth/Login-Modell, Connector-API zur Mandanten-Laufzeit).
- Heutiges Kunden-Paket ist daher bewusst nur ein **Onboarding-/Konfig-Paket**.

---

## 5. Unveränderliche Grenzen (für jede künftige Phase)

- Engine (`b2bbot/`) und Closer (`ClouseAgent/`) bleiben **read-only**, Zugriff
  nur über die Bridge.
- **Kein Auto-Send.** Senden/Approve/Follow-up = hartes menschliches Tor.
- Kunde bekommt **nie** proprietären Engine-/Akquise-Code oder das Betreiber-
  Dashboard mit Setup/SMTP/Token/Engine-Feldern.
- Keine Engine-Logik entfernen, keine Sende-/Reply-/Follow-up-/CRM-/Handoff-
  Logik einschränken, kein großer Refactor ohne ausdrückliche Freigabe.
- Secrets niemals committen oder ins Kundenpaket geben.

---

## 6. Stand

- **F0–F7 abgeschlossen** (Plattform, Isolation, Routing, Reporting, Branding,
  SaaS-sichere Paket-Trennung, Betreiber-Deployment dokumentiert, E2E-Smoke).
- Nächster Meilenstein **erst nach Produkt-/Vertriebsentscheidung**: F8 (Portal/
  Connector) — mit vorgeschaltetem Design-Vorschlag.
