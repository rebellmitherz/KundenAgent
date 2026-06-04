# Auftrags-Schema (Order Schema)

> Das Fundament, an dem alles hängt. Spec-only — noch kein Code.
> Der Operator füllt genau diese Felder aus freiem Text. Die Bridge akzeptiert
> **nur** Aufträge, die diesem Schema entsprechen und bestätigt sind.

## Felder

| Feld | Pflicht | Beschreibung | Beispiel |
|---|---|---|---|
| `zielgruppe` | ja | Branche/ICP | „Handwerker" |
| `region` | ja | Ort/Region | „NRW" |
| `lead_anzahl` | ja | Zielmenge | `100` |
| `angebot` | ja | Was verkauft wird | „Website-Erstellung" |
| `qualitaetskriterien` | ja | Sauberkeits-Regeln | Telefon Pflicht, kein Konzern, keine Dublette |
| `erlaubte_aktion` | ja | **Enum**, was der Bot darf | `suchen_aufbereiten` |
| `status` | system | Lebenszyklus | siehe unten |
| `auftrags_id` | system | eindeutige ID | `2026-06-04_handwerker_nrw` |

## `erlaubte_aktion` — erlaubte Werte

| Wert | Bedeutung | Verfügbar ab |
|---|---|---|
| `suchen_aufbereiten` | nur suchen + aufbereiten, **kein** Versand | **V1** |
| `vorschau_erstellen` | zusätzlich Mail-Vorschau generieren (kein Versand) | V2 |
| `senden_nach_freigabe` | senden — **nur** nach separatem menschlichem Freigabe-Klick | V2 |

In V1 ist `suchen_aufbereiten` der **einzige** Wert, den die Bridge ausführen kann.
`senden_*` existiert als Pfad in V1 gar nicht.

## `status` — Lebenszyklus

```
entwurf → bestaetigt → laeuft → fertig
                         │
                         └→ wartet_auf_freigabe (V2, vor jedem Versand)
```

- `entwurf` — Operator hat geparst, Kunde hat noch nicht bestätigt.
- `bestaetigt` — Kunde hat „Ja" gesagt; Bridge darf erlaubte Aktion starten.
- `laeuft` — Engine arbeitet (Hintergrund).
- `fertig` — Ergebnis liegt vor, Bericht erstellt.
- `wartet_auf_freigabe` — (V2) Versand erst nach menschlichem Klick.

## Qualitätskriterien (Default-Regeln)

- Telefon Pflicht (entspricht heutiger Engine-Logik).
- Persönlicher Ansprechpartner bevorzugt.
- Keine Konzerne (Engine-Blocklist existiert).
- Keine generischen Mails (`info@`, `support@` — Engine filtert das).
- Keine Dubletten (Engine dedupliziert; über Läufe hinweg = Target Fill, V2).

## Target Fill (Bezug)

Wenn `lead_anzahl` nicht sauber erreicht wird, liefert die Engine bereits
Funnel-Diagnosen (`output/latest/lead_funnel_diagnostics.json`). Der Operator
nutzt das, um „X von N sauber, Y fehlen" zu berichten und Varianten vorzuschlagen.
Voller Ausbau in V2.

## Persistenz

Aufträge werden datei-basiert in `../orders/` abgelegt (JSON), passend zum
datei-basierten Ansatz der Engine. Pfad über konfigurierbares `DATA_DIR`
(siehe `../PACKAGING.md`), nicht hardcodiert.
