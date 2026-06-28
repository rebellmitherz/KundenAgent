"""Personalisierter Akquise-Brief je Lead (postalisch / PDF-Download).

Erzeugt einen druckfertigen DIN-5008-Brief als HTML-Seite.

Konfiguration
-------------
Absender und Unterschrift einmalig in ``ABSENDER`` und ``UNTERSCHRIFT`` unten
anpassen — ein Ort, gilt für alle Briefe sofort.

Empfänger-Anschrift
-------------------
Firma + Ansprechpartner + Ort. Straße/PLZ nicht in Leads vorhanden — sobald
sie verfügbar sind, kommen sie automatisch aus ``lead["street"]`` / ``lead["zip"]``.

b2bbot bleibt read-only. Liegt im product/-Layer.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

LLM = Callable[[str], str]

# =============================================================================
# KONFIGURATION — hier einmalig ausfüllen, gilt für alle Briefe
# =============================================================================

ABSENDER = {
    "name":       "[Ihr Name]",            # z.B. "Emilio Allegro"
    "firma":      "[Ihre Firma]",           # z.B. "Rebell System"
    "strasse":    "[Straße und Hausnummer]",
    "plz_ort":    "[PLZ Ort]",
    "telefon":    "[Telefon]",              # optional, leer lassen = wird nicht gedruckt
    "email":      "[E-Mail]",               # optional
    "website":    "[Website]",              # optional
}

UNTERSCHRIFT = {
    # Pfad zu eingescanntem Unterschrift-PNG (transparent oder weiß).
    # Leer lassen → Platzhalter-Linie wird gedruckt.
    # Sobald du das Bild hast: "img/unterschrift.png" eintragen.
    "bild":  "",
    "name":  ABSENDER["name"],
    "titel": "",   # z.B. "Geschäftsführer" — optional
}

# =============================================================================

# ─── Signal → Brieftext-Bausteine (deterministisch, 0 € laufend) ─────────────

_SIGNAL_BETREFF: dict[str, str] = {
    "sales_hiring":       "Ihr Vertriebsaufbau — und wie wir ihn von Tag 1 unterstützen",
    "appointment_setter": "Ihr Outbound-Aufbau — qualifizierte Termine vom ersten Tag",
    "growth_expansion":   "Ihr Wachstum — und wie wir die passende Pipeline dazu liefern",
    "marketing_hiring":   "Ihre Marketing-Investition — und die Leads, die dazu passen",
    "leadership_hiring":  "Ihre neue Führungskraft — Leads bereit, bevor sie startet",
    "new_location":       "Ihr neuer Standort — Kunden in der Region, die jetzt kaufen",
}

_SIGNAL_ABSATZ1: dict[str, str] = {
    "sales_hiring": (
        "Wir haben festgestellt, dass Sie aktuell eine Vertriebsposition besetzen. "
        "Das ist ein klares Signal: Sie investieren in Wachstum und brauchen ab sofort "
        "eine Pipeline, die zu dieser Investition passt."
    ),
    "appointment_setter": (
        "Wir haben gesehen, dass Sie gerade einen Terminierer oder SDR suchen. "
        "Das bedeutet: Sie bauen Outbound-Kapazität auf — und brauchen dafür "
        "Kontakte, bei denen sich der Aufwand wirklich lohnt."
    ),
    "growth_expansion": (
        "Wir haben mitverfolgt, dass Ihr Unternehmen gerade wächst und das Team ausbaut. "
        "Wachstumsphasen sind der beste Zeitpunkt, um die richtigen Kunden zu gewinnen — "
        "bevor die Kapazität wieder knapp wird."
    ),
    "marketing_hiring": (
        "Wir haben festgestellt, dass Sie aktuell in Marketing und Leadgenerierung investieren. "
        "Das zeigt: Neukundengewinnung hat für Sie gerade höchste Priorität — "
        "und genau da setzen wir an."
    ),
    "leadership_hiring": (
        "Wir haben wahrgenommen, dass Sie eine neue Vertriebs- oder Marketingleitung holen. "
        "Ein Neustart im Vertrieb funktioniert am besten, wenn vom ersten Tag an "
        "qualifizierte Leads auf dem Tisch liegen."
    ),
    "new_location": (
        "Wir haben gesehen, dass Sie einen neuen Standort eröffnen. "
        "Expansion bedeutet neuer Markt, neue Kunden — und die Frage, "
        "wie man dort schnell sichtbar und erfolgreich wird."
    ),
}

_ABSATZ2 = (
    "Genau hier kommen wir ins Spiel. Wir identifizieren Unternehmen, "
    "die im richtigen Moment kaufen wollen — verifiziert durch echte Kaufsignale "
    "wie Stellenausschreibungen, Expansionsmeldungen und Investitionsankündigungen. "
    "Kein Datenbankrauschen, keine kalten Adressen — nur Firmen, "
    "bei denen der Zeitpunkt stimmt."
)

_ABSATZ3 = (
    "Ich würde Ihnen gerne in einem kurzen Gespräch zeigen, wie das konkret "
    "für Ihr Unternehmen aussieht. Kein Pitch, kein Druck — nur 15 Minuten, "
    "damit Sie selbst entscheiden können, ob es passt."
)

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _esc(s: object) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _datum_de() -> str:
    try:
        import locale
        locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
    except Exception:
        pass
    try:
        return date.today().strftime("%-d. %B %Y")
    except ValueError:
        return date.today().strftime("%d. %B %Y").lstrip("0")


def _anrede(ansprechpartner: str) -> str:
    name = (ansprechpartner or "").strip()
    if not name:
        return "Sehr geehrte Damen und Herren"
    nachname = name.split()[-1]
    return f"Sehr geehrte/r {nachname}"


# ─── LLM-Verbesserung für Absatz 1 ───────────────────────────────────────────

def _absatz1_llm(lead: dict, basis: str, llm: LLM) -> str:
    firma = (lead.get("company_name") or "Ihr Unternehmen").strip()
    ansp = (lead.get("contact_full_name") or lead.get("managing_director") or "").strip()
    signal_titel = (lead.get("signal_titel") or "").strip()
    hint = f'Beleg: "{signal_titel}"' if signal_titel else ""
    prompt = (
        f"Schreib einen kurzen, professionellen Eröffnungsabsatz (3–4 Sätze, Deutsch, "
        f"sachlich-persönlich) für einen Akquise-Brief an {firma}. "
        f"{'Ansprechpartner: ' + ansp + '. ' if ansp else ''}"
        f"Ausgangspunkt: {basis} {hint} "
        f"Stil: direkt, kein Geschwätz, kein 'ich freue mich' oder 'herzlich'. "
        f"Nur den Absatz, kein Titel."
    )
    try:
        result = (llm(prompt) or "").strip()
        return result if len(result) > 30 else basis
    except Exception:
        return basis


# ─── Öffentliche API ──────────────────────────────────────────────────────────

def brief_html(lead: dict, *, llm: Optional[LLM] = None) -> str:
    """Druckfertiger DIN-A4-Akquise-Brief als HTML-String.

    Absender + Unterschrift kommen aus den Modul-Konstanten ``ABSENDER`` und
    ``UNTERSCHRIFT`` — einmalig oben konfigurieren, gilt für alle Briefe.
    """
    # ── Empfänger ──
    firma = (lead.get("company_name") or "").strip()
    ansprechpartner = (
        lead.get("contact_full_name") or lead.get("managing_director") or
        lead.get("ansprechpartner") or ""
    ).strip()
    strasse = (lead.get("street") or lead.get("address") or "").strip()
    plz = (lead.get("zip") or lead.get("postal_code") or "").strip()
    ort = (lead.get("city") or lead.get("region") or "").strip()
    plz_ort = f"{plz} {ort}".strip() if plz else ort

    # ── Signal ──
    signal = (lead.get("entdeckt_per_signal") or "").strip().lower()
    signal_titel = (lead.get("signal_titel") or "").strip()

    betreff = _SIGNAL_BETREFF.get(signal, "Ihr Unternehmen — und wie wir unterstützen können")
    absatz1_basis = _SIGNAL_ABSATZ1.get(signal, (
        "Wir haben Ihr Unternehmen im Zusammenhang mit einem aktuellen Kaufsignal "
        "identifiziert — und glauben, dass der Zeitpunkt für ein kurzes Gespräch ideal wäre."
    ))
    if signal_titel:
        absatz1_basis = absatz1_basis.rstrip() + f' (Beleg: „{signal_titel}")'

    absatz1 = _absatz1_llm(lead, absatz1_basis, llm) if llm else absatz1_basis
    anrede = _anrede(ansprechpartner)
    datum = _datum_de()

    # ── Absender-Block (oben links, DIN-5008) ──
    abs_zeilen = [ABSENDER["name"]]
    if ABSENDER.get("firma") and ABSENDER["firma"] != ABSENDER["name"]:
        abs_zeilen.append(ABSENDER["firma"])
    abs_zeilen.append(ABSENDER["strasse"])
    abs_zeilen.append(ABSENDER["plz_ort"])
    abs_kontakt = []
    if ABSENDER.get("telefon") and "[" not in ABSENDER["telefon"]:
        abs_kontakt.append(f'Tel.: {ABSENDER["telefon"]}')
    if ABSENDER.get("email") and "[" not in ABSENDER["email"]:
        abs_kontakt.append(ABSENDER["email"])
    if ABSENDER.get("website") and "[" not in ABSENDER["website"]:
        abs_kontakt.append(ABSENDER["website"])

    absender_html = "".join(f"<div>{_esc(z)}</div>" for z in abs_zeilen)
    if abs_kontakt:
        absender_html += f'<div class="abs-kontakt">{_esc(" · ".join(abs_kontakt))}</div>'

    # ── Empfänger-Block ──
    empf: list[str] = []
    if firma:
        empf.append(f"<div><strong>{_esc(firma)}</strong></div>")
    if ansprechpartner:
        empf.append(f"<div>z.&nbsp;Hd. {_esc(ansprechpartner)}</div>")
    if strasse:
        empf.append(f"<div>{_esc(strasse)}</div>")
    if plz_ort:
        empf.append(f"<div>{_esc(plz_ort)}</div>")
    if not empf:
        empf.append("<div>—</div>")
    empfaenger_html = "\n".join(empf)

    # ── Unterschrift ──
    if UNTERSCHRIFT.get("bild") and "[" not in UNTERSCHRIFT["bild"]:
        unterschrift_html = (
            f'<img src="{_esc(UNTERSCHRIFT["bild"])}" alt="Unterschrift" '
            f'style="height:55px;display:block;margin-bottom:4px"/>'
        )
    else:
        unterschrift_html = '<div class="unt-linie"></div>'

    unt_name = UNTERSCHRIFT.get("name") or ABSENDER["name"]
    unt_titel = UNTERSCHRIFT.get("titel") or ""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"/>
<title>Brief · {_esc(firma or "Lead")}</title>
<style>
  @page{{size:A4 portrait;margin:20mm 20mm 25mm 25mm}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{
    font:11.5pt/1.6 "Times New Roman",Times,Georgia,serif;
    color:#111;background:#fff;
    max-width:165mm;margin:0 auto;padding:16px;
  }}
  .noprint{{margin-bottom:18px}}
  .print-btn{{
    padding:8px 20px;background:#1d4ed8;color:#fff;border:none;
    border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;font-family:sans-serif;
  }}
  /* DIN-5008 Layout */
  .kopf{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10mm}}
  .absender-block{{font-size:9.5pt;line-height:1.45;color:#333}}
  .abs-kontakt{{margin-top:4px;color:#555;font-size:9pt}}
  .datum-block{{font-size:10.5pt;text-align:right;padding-top:2px}}
  .anschrift-fenster{{
    min-height:27mm;border:1px dashed #ccc;padding:4mm 5mm;
    margin-bottom:8mm;font-size:10.5pt;line-height:1.5;
    /* Im Druck: kein Rahmen — nur Fensterbereich simulieren */
  }}
  @media print{{.anschrift-fenster{{border:none;padding:0}}}}
  .abs-klein{{font-size:8pt;color:#888;border-bottom:1px solid #ccc;
    padding-bottom:2px;margin-bottom:4px}}
  .betreff{{font-weight:bold;font-size:11.5pt;margin:6mm 0 5mm;text-decoration:underline}}
  .anrede{{margin-bottom:5mm}}
  .absatz{{margin-bottom:4mm;text-align:justify}}
  .gruss{{margin-top:8mm;margin-bottom:14mm}}
  .unt-linie{{border-bottom:1px solid #444;width:55mm;margin-bottom:3px}}
  .unt-name{{font-size:10.5pt}}
  .unt-titel{{font-size:9pt;color:#555}}
  @media print{{.noprint{{display:none}}}}
</style>
</head>
<body>
<div class="noprint">
  <button class="print-btn" onclick="window.print()">📄 Als PDF speichern / Drucken</button>
</div>

<div class="kopf">
  <div class="absender-block">
    {absender_html}
  </div>
  <div class="datum-block">
    {_esc(ort + ", " if ort else "")}{datum}
  </div>
</div>

<div class="anschrift-fenster">
  <div class="abs-klein">{_esc(ABSENDER["name"])} · {_esc(ABSENDER["strasse"])} · {_esc(ABSENDER["plz_ort"])}</div>
  {empfaenger_html}
</div>

<div class="betreff">Betreff: {_esc(betreff)}</div>

<p class="anrede">{_esc(anrede)},</p>

<p class="absatz">{_esc(absatz1)}</p>
<p class="absatz">{_esc(_ABSATZ2)}</p>
<p class="absatz">{_esc(_ABSATZ3)}</p>

<p class="gruss">Mit freundlichen Grüßen</p>

{unterschrift_html}
<div class="unt-name">{_esc(unt_name)}</div>
{f'<div class="unt-titel">{_esc(unt_titel)}</div>' if unt_titel else ""}

<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),350));</script>
</body>
</html>"""
