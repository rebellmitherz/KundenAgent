# Betreiber-Deployment — Rebellsystem Akquise-Plattform

> Diese Anleitung richtet sich an **dich als Betreiber** (Admin). Sie beschreibt,
> wie du die Plattform produktiv betreibst — Single-Tenant (du allein) und
> Multi-Tenant (mehrere zahlende Kunden, je isoliert).
>
> **Diese Datei enthält keine Secrets.** Trage Zugangsdaten nur in die lokalen,
> gitignorierten Konfig-Dateien ein (siehe unten). Gib niemals das Betreiber-
> System oder Secrets an Kunden weiter.

---

## 1. Voraussetzungen

- Windows 10/11, **Python 3.10+**
- Die Engine `b2bbot/` liegt neben `product/` (enthält `mine.py`)
- Pro produktivem Kunden: eine **eigene, isolierte** Engine-Instanz (eigenes
  `engine_dir` mit eigenem Postfach/Pipeline) — niemals geteilt
- Telegram-Bot-Token (via @BotFather) + deine Telegram-Chat-ID

Prüfen, ob alles startbereit ist:

```powershell
$env:PYTHONUTF8=1
python product/packaging/check_install.py
```

---

## 2. Lizenz-Secret setzen (Produktionsmodus)

Das Lizenz-Secret kommt **ausschließlich** aus der Umgebungsvariable
`REBELLSYSTEM_LICENSE_SECRET` — nie aus Code oder Repo. Ohne gesetztes Secret
läuft das System im Entwicklungsmodus.

```powershell
# dauerhaft (neue Shell nötig danach):
setx REBELLSYSTEM_LICENSE_SECRET "<dein-langes-zufalls-secret>"
```

`check_install.py` weist (nur als Hinweis) darauf hin, wenn es fehlt.

---

## 3. Konfiguration

Kopiere die Vorlage und fülle deine Werte ein (Datei ist gitignored):

```powershell
copy product\product_config.example.json product\product_config.json
```

Felder in `product_config.json`:

| Feld | Bedeutung |
|------|-----------|
| `bot_token` | Telegram-Bot-Token |
| `owner_chat_id` | **Betreiber-Chat** (du). Im Multi-Tenant = Operator für `/plattform` |
| `engine_dir` | Pfad zur Engine (Single-Tenant). Default `../b2bbot` |
| `data_dir` | Laufzeit-Daten (Default `data`). Enthält auch das Mandanten-Register |
| `anthropic_api_key` | optional — Plattform-Default-Key (Reasoning) |
| `license_key` | optional |
| `ui_token` | optional — schützt Admin-Tabs der Mini-UI |

> Wird beim ersten Telegram-Kontakt noch keine `owner_chat_id` gefunden, wird
> die erste schreibende Chat-ID automatisch als Owner registriert.

---

## 4. Start

```powershell
# Telegram-Bot (Live-Entry):
python product/telegram/bot.py
# oder: start_operator.bat

# Mini-UI (optional, nur 127.0.0.1):
$env:PYTHONUTF8=1; python product/ui/server.py   # http://127.0.0.1:8767
```

Der Bot entscheidet den Modus **automatisch beim Start**:

- **Kein** aktiver Mandant registriert → **Single-Tenant** (Verhalten wie bisher:
  eine Engine, dein Owner-Chat, ein Watcher).
- **Mindestens ein** aktiver Mandant → **Multi-Tenant** (je Kunde isolierter
  Agent + Watcher; Routing über die `owner_chat_id` des Kunden).

---

## 5. Mandanten (Kunden) anlegen — Multi-Tenant

Jeder Kunde bekommt eine **harte Isolation**: eigenes Daten-Verzeichnis (aus der
ID abgeleitet) und eine **eigene** Engine-Instanz. Das Register erzwingt, dass
keine zwei aktiven Mandanten dasselbe `engine_dir` teilen.

Das Register liegt unter `data_dir/platform/mandanten.json` (enthält Kunden-
Secrets → **gitignored**, niemals committen).

Anlegen per kurzem Skript (verifizierte API):

```python
from product.platform.mandant import Mandant, MandantenRegister

reg = MandantenRegister("product/data/platform")   # = data_dir/platform
reg.anlegen(Mandant(
    mandant_id="kunde-mueller",         # wird zu sauberem Slug
    name="Müller Bau GmbH",
    owner_chat_id="123456789",          # Telegram-Chat-ID DES KUNDEN
    engine_dir="C:/Rebellsystem/engines/mueller",  # eigene, isolierte Engine
    anthropic_api_key="",               # leer = Plattform-Default
    license_key="",
    standard_zielgruppe="Handwerker",
    standard_region="NRW",
    branche="Bau",
    aktiv=True,
))
```

Danach den Bot **neu starten** (Laufzeiten werden beim Start aufgebaut/gecacht).

Weitere Register-Operationen: `reg.alle()`, `reg.holen(id)`, `reg.aktualisieren(m)`,
`reg.entfernen(id)`.

### Pro Mandant: Engine einrichten
- Lege je Kunde einen eigenen `engine_dir` an (eigene b2bbot-Instanz, eigenes
  Postfach/Pipeline). Ein Mandant ohne baubare Engine wird höflich als „in
  Einrichtung" gemeldet und nicht bedient — er blockiert die anderen nicht.

---

## 6. Betrieb & Bedienung

- **Kunde** schreibt seinem Bot natürlichsprachig („Such 100 Handwerker in NRW…").
  Der Agent sucht, füllt Lücken selbst auf und **hält an harten Toren** (Senden,
  Termin) — nie Auto-Send.
- **Betreiber** (`owner_chat_id`): `/plattform` → Gesamtsicht aller Kunden
  (bestätigte Termine je Mandant, sortiert). Closer-Befehle sind im Multi-Tenant
  nur für den Betreiber.
- Watcher meldet je Kunde an dessen Owner: Termin-Signale, offene Freigabe-Tore,
  fällige Follow-ups (alle 5 Min, Auto-Abruf des Postfachs read-only).

---

## 7. Pakete erstellen

Strikt getrennt — **nie vermischen**:

```powershell
python product/packaging/package.py              # beide
python product/packaging/package.py --typ betreiber
python product/packaging/package.py --typ kunde
```

- `dist/rebellsystem-operator-v{V}.zip` — **Betreiber-Paket**, voll lauffähig
  inkl. Engine. **Niemals an Kunden ausliefern.**
- `dist/rebellsystem-saas-v{V}.zip` — **Kunden-Paket**, SaaS-sicher (nur
  generierte Onboarding-/Konfig-/Doku-Artefakte, kein Quellcode/Engine/Secrets).

---

## 8. Backup & Sicherheit

- Sichere regelmäßig: `data_dir/` (Agent-Läufe, Kampagnen) und besonders
  `data_dir/platform/mandanten.json` (Kunden-Stammdaten/Secrets).
- **Niemals committen:** `product_config.json`, `product_smtp.json`,
  `mandanten.json`, `.env*`, `keygen.py` (alle in `.gitignore`).
- Die Engine (`b2bbot/`, `ClouseAgent/`) ist read-only und wird **nur** über die
  Bridge (Subprozess) angesprochen — nicht direkt anfassen.
- Es wird **nie automatisch versendet** — Senden/Approve/Follow-up bleibt ein
  hartes menschliches Tor.

---

## 9. Schnell-Checkliste (Go-Live)

1. `python product/packaging/check_install.py` → startbereit ✓
2. `REBELLSYSTEM_LICENSE_SECRET` gesetzt
3. `product_config.json` ausgefüllt (Token + Betreiber-Chat)
4. (Multi-Tenant) Mandanten registriert, je eigene Engine eingerichtet
5. `python product/telegram/bot.py` startet ohne Fehler
6. Testnachricht vom Kunden-Chat → wird korrekt bedient; fremde ID → abgelehnt
7. `/plattform` vom Betreiber-Chat → Gesamtsicht erscheint
