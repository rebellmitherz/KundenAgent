# PACKAGING — Customer Package / Installer-Konzept

> **Diese Runde:** nur Analyse. **Kein** Installer-Bau.
> Ziel: festlegen, welche Architektur-Entscheidungen **heute** gelten müssen,
> damit ein Installer später sauber möglich ist — ohne Doppelarbeit.

---

## 1. Zielbild (später, nicht jetzt)

Ein Kunde soll das Produkt auf seinem **eigenen Windows-PC** möglichst einfach
installieren/starten können — **ohne Entwicklerwissen**:

- Windows-Setup (Installer oder portable ZIP).
- Eigene Kunden-Konfiguration (pro Installation).
- `.env.example` statt echter `.env`.
- Desktop-Shortcut / Start-Menü-Eintrag.
- Telegram-Verbindung per geführtem Onboarding.
- Update-Möglichkeit.
- Logs **ohne** Geheimnisse.
- Klare Trennung: lokale Kundeninstallation vs. spätere Server-/SaaS-Version.

---

## 2. Was die Architektur HEUTE erfüllen muss

Damit der Installer später nicht erzwingt, alles umzubauen, gelten ab sofort
folgende Regeln für **jeden** neuen Code in `product/`:

### 2.1 Keine hardcodierten Pfade
- **Verboten:** `C:\Users\micha\...`, absolute Emilio-Pfade, feste Laufwerke.
- **Pflicht:** Pfade relativ zum Installationsordner auflösen
  (z. B. „eine Ebene über `product/` liegt die Engine") **oder** über Config.
- Die Engine-Lage darf konfigurierbar sein (analog `bot_config.engine_dir`,
  das heute schon korrekt den Elternordner als Default nimmt).

### 2.2 Drei getrennte Pfad-Arten
| Art | Inhalt | Wo | Schreibbar? |
|---|---|---|---|
| **Programm** | Code, Engine, Operator | Install-Dir | nein (read-only nach Install) |
| **Konfiguration** | Kunden-Config, `.env` | Daten-Dir | ja |
| **Daten/Output** | Aufträge, Leads, Logs | Daten-Dir | ja |

- Konfiguration und Daten **niemals** in den Programmordner schreiben
  (sonst bricht der Installer/Update, und `Program Files` ist read-only).
- Empfehlung: ein konfigurierbares `DATA_DIR` (Default z. B.
  `%LOCALAPPDATA%\HermesSalesOperator\` oder ein `data/`-Ordner neben dem Start).
  Heute schreibt die Engine alles nach `output/` relativ zum Engine-Ordner —
  das bleibt für lokale Installation ok, muss aber **konfigurierbar** bleiben.

### 2.3 Secrets-Hygiene
- Nur `.env.example` ausliefern, **nie** eine echte `.env`.
- Keine Bot-Tokens, SMTP-Passwörter, API-Keys im Paket.
- Erststart-Onboarding erzeugt die lokale Config/`.env` selbst — sicher,
  **nicht** im Telegram-Chat-Klartext (heutiger `/setup`-Flow wird dafür ersetzt).
- Der Verkäufer-Lizenz-`SECRET` (`license.py`) darf **nie** mitgeliefert werden,
  wenn er Schlüssel erzeugen kann — Lizenzprüfung und Lizenz**erzeugung** trennen.

### 2.4 Start-Mechanik installer-freundlich
- Ein **einziger** klarer Startpunkt pro Komponente
  (Operator/Telegram-Front, optional UI), per `.bat`/Shortcut aufrufbar.
- Keine Annahme „Entwickler tippt Befehle". Doppelklick muss reichen.
- Single-Instance-Lock existiert schon (`bot.lock`) — Muster beibehalten.

### 2.5 Logs ohne Geheimnisse
- Logs dürfen **keine** Keys, Passwörter, Tokens, vollständige `.env`-Inhalte enthalten.
- Ein Support-/Fehlerbericht soll sammelbar sein (Version, Fehlertext, Auftrags-ID)
  — **redigiert**. Niemals rohe Credentials.

### 2.6 Update-Fähigkeit von Anfang an
- **Produktschicht (`product/`) und Engine (`b2bbot/`) sauber getrennt halten.**
  So kann die Engine aktualisiert werden, ohne Kunden-Config/Operator zu zerstören.
- Versionsstand pro Komponente kennzeichnen (z. B. `version.txt` / Manifest;
  ein `bot_manifest.json` existiert in der Engine bereits als Muster).
- Kunden-Config + Daten liegen **außerhalb** des updatebaren Programmteils
  (siehe 2.2), damit ein Update sie nicht überschreibt.

### 2.7 Lokal vs. Server von Anfang an entkoppeln
- Operator, Bridge und State **nicht** an „läuft genau auf diesem einen PC" koppeln.
- State über ein konfigurierbares `DATA_DIR` adressieren (nicht über feste lokale Pfade),
  damit dieselbe Codebasis später serverseitig pro Mandant laufen kann.
- Mandanten-/Feature-Trennung gedanklich vorsehen (Feature-Flags existieren schon
  in `bot_config.py`) — aber in V1 bewusst Single-Tenant lokal.

---

## 3. Zwei Auslieferungsformen (später)

| Form | Wann | Merkmale |
|---|---|---|
| **Lokale Kundeninstallation** | V1/V2 | Windows, eigener PC, eigene Config/`.env`, Daten lokal, Shortcut-Start |
| **Server-/SaaS-Version** | V3+ | zentral gehostet, Mandanten, zentrales Update, keine Kunden-`.env` auf dessen PC |

Beide teilen sich **dieselbe** Operator-/Bridge-Codebasis — Voraussetzung dafür
sind die Regeln aus Abschnitt 2 (vor allem 2.1, 2.2, 2.7).

---

## 4. Was in dieser Runde NICHT passiert

- Kein Installer, kein Setup-Programm, kein Packaging-Skript.
- Keine PyInstaller-/Inno-Setup-/MSIX-Entscheidung festgezurrt
  (kommt, wenn V1-Code steht).
- Keine Änderung am bestehenden `telegram_seller`-`/setup`-Flow.
- Keine `.env`-Erzeugung, kein Token-Handling.

Nur diese Vorgaben festhalten, damit der spätere Installer additiv möglich ist.

---

## 5. Installer-Checkliste (für später, als Erinnerung)

- [ ] Keine hardcodierten Nutzerpfade im gesamten `product/`-Code.
- [ ] `DATA_DIR` konfigurierbar, Default außerhalb des Programmordners.
- [ ] Nur `.env.example` im Paket, nie echte Secrets.
- [ ] Lizenz**erzeugung** nicht im Kundenpaket.
- [ ] Ein Doppelklick-Start pro Komponente + Desktop-Shortcut.
- [ ] Logs redigiert (kein Secret), Support-Report sammelbar.
- [ ] `product/` und `b2bbot/` getrennt updatebar; Versions-Manifest.
- [ ] Lokal-vs-Server-Pfad nur über Config, nicht über Code-Annahmen.
