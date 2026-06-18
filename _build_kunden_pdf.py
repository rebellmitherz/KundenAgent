# -*- coding: utf-8 -*-
"""Kundenfertiges Werbe-/Verkaufs-PDF (zum Mailen). Marketing-Stil, nutzenorientiert.
Deutsche Quotes als Entities, echte Umlaute, keine ASCII-Doublequotes im Inhalt."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)

OUT = r"C:\Users\micha\Desktop\KundenAgent\Rebellsystem_Akquise_fuer_Sie.pdf"
LO = "&#8222;"; LC = "&#8220;"; DASH = "&#8212;"; EUR = "&#8364;"; MID = "&#183;"; ARR = "&#8250;"

NAVY = colors.HexColor("#0B1F3A"); CYAN = colors.HexColor("#0091B5")
CYAN_SOFT = colors.HexColor("#E7F6FA"); ORANGE = colors.HexColor("#FF7A1A")
INK = colors.HexColor("#1C2530"); GREY = colors.HexColor("#5B6675")
LINE = colors.HexColor("#D6DCE4"); GREEN = colors.HexColor("#1E8E5A")

MARGIN = 1.7 * cm
CW = A4[0] - 2 * MARGIN

S = ParagraphStyle
body = S("body", fontName="Helvetica", fontSize=10.5, leading=15.5, textColor=INK, spaceAfter=6)
lead = S("lead", fontName="Helvetica", fontSize=12, leading=17, textColor=INK, spaceAfter=8)
h2 = S("h2", fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=NAVY, spaceBefore=6, spaceAfter=2)
small = S("small", fontName="Helvetica", fontSize=8.4, leading=11.5, textColor=GREY)
benefit = S("benefit", fontName="Helvetica", fontSize=10.3, leading=14, textColor=INK)


def heading(text):
    return KeepTogether([
        Spacer(1, 8),
        Paragraph('<font color="#0091B5"><b>' + text + '</b></font>', h2),
        HRFlowable(width=CW, thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=8, lineCap='round'),
    ])


def check(text):
    return Paragraph('<font color="#1E8E5A"><b>' + ARR + '</b></font>&nbsp;&nbsp;' + text, benefit)


story = []

# ───────── HERO ─────────
hero_inner = [
    Paragraph('<font color="#7FD8EC"><b>REBELLSYSTEM &#183; AKQUISE-PLATTFORM</b></font>',
              S("kx", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white, spaceAfter=12)),
    Paragraph('<font color="white"><b>Mehr Termine mit Entscheidern.<br/>Ohne Kaltakquise-Stress.</b></font>',
              S("hl", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.white, spaceAfter=12)),
    Paragraph('<font color="#D7E2EE">Ihr persönlicher Akquise-Agent findet passende Firmen, schreibt sie '
              'persönlich an und bringt <b>qualifizierte Gespräche in Ihren Kalender</b>. '
              'Sie entscheiden &#8212; das System arbeitet.</font>',
              S("hs", fontName="Helvetica", fontSize=12.5, leading=18, textColor=colors.white)),
]
hero = Table([[hero_inner]], colWidths=[CW])
hero.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), NAVY),
    ("LINEBELOW", (0, 0), (-1, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 24), ("RIGHTPADDING", (0, 0), (-1, -1), 24),
    ("TOPPADDING", (0, 0), (-1, -1), 30), ("BOTTOMPADDING", (0, 0), (-1, -1), 28),
]))
story += [hero, Spacer(1, 14)]

# ───────── PROBLEM / EMPATHIE ─────────
story += [Paragraph("Kennen Sie das? Neukunden gewinnen frisst Zeit und Nerven: recherchieren, texten, "
                    "nachfassen, Absagen wegstecken. Und am Monatsende bleibt die Frage: <b>Wie viele echte "
                    "Termine sind eigentlich dabei herausgekommen?</b>", lead)]

# ───────── SO EINFACH ─────────
story += [heading("So einfach läuft es für Sie")]


def step(num, title, txt):
    inner = [
        Paragraph('<font color="#FF7A1A"><b>' + num + '</b></font>',
                  S("sn", fontName="Helvetica-Bold", fontSize=22, leading=24, alignment=TA_LEFT)),
        Paragraph('<b>' + title + '</b>', S("stt", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=2, spaceAfter=2)),
        Paragraph('<font color="#1C2530">' + txt + '</font>', S("stx", fontName="Helvetica", fontSize=9.3, leading=12.5)),
    ]
    return inner


steps = Table([[step("1", "Ziel sagen", "Ein Satz genügt: " + LO + "100 Handwerksbetriebe in NRW" + LC + " &#8212; per Telegram oder im Dashboard."),
                step("2", "System arbeitet", "Es sucht passende Firmen, schreibt persönlich an, prüft Antworten und fasst nach."),
                step("3", "Termine erhalten", "Sie bekommen geprüfte Terminchancen gemeldet &#8212; und geben jeden Versand selbst frei.")]],
               colWidths=[CW / 3.0] * 3)
steps.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT),
    ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 6, colors.white),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
]))
story += [steps]

# ───────── WAS SIE DAVON HABEN ─────────
story += [heading("Was Sie davon haben")]
left = [check("<b>Planbar neue Termine</b> statt Zufall und Flaute."),
        check("<b>Schluss mit stundenlanger Kaltakquise</b> &#8212; das übernimmt der Agent."),
        check("<b>Persönliche Mails</b>, die beim Kunden ansetzen &#8212; kein Spam-Gefühl.")]
right = [check("<b>Nur echte Terminchancen</b> gemeldet (Fehlalarme gefiltert)."),
         check("<b>Volle Kontrolle:</b> nichts geht ohne Ihr Ja raus."),
         check("<b>Ihre Daten bleiben Ihre Daten</b> &#8212; sauber getrennt.")]
bt = Table([[left, right]], colWidths=[CW / 2.0, CW / 2.0])
bt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 14),
    ("LEFTPADDING", (1, 0), (1, 0), 6), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
# kleiner Abstand zwischen den Checks
left2 = []
for c in left:
    left2 += [c, Spacer(1, 6)]
right2 = []
for c in right:
    right2 += [c, Spacer(1, 6)]
bt = Table([[left2, right2]], colWidths=[CW / 2.0, CW / 2.0])
bt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("RIGHTPADDING", (0, 0), (0, 0), 14), ("LEFTPADDING", (1, 0), (1, 0), 6)]))
story += [bt, Spacer(1, 4)]

# ───────── WARUM ANDERS (Highlight) ─────────
hl = [
    Paragraph('<font color="white"><b>Warum das anders ist als jedes Lead-Tool</b></font>',
              S("wa", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.white, spaceAfter=5)),
    Paragraph('<font color="#E7F6FA">Die meisten Tools liefern <b>Lead-Masse</b>. Wir liefern, worauf es ankommt: '
              '<b>geprüfte Termine</b>. Der Agent denkt mit, arbeitet eigenständig &#8212; und hält an jedem '
              'wichtigen Punkt an, damit <b>Sie</b> entscheiden. Ehrlich, ruhig, ohne Spam.</font>',
              S("wb", fontName="Helvetica", fontSize=10.3, leading=14.5, textColor=colors.white)),
]
hlb = Table([[hl]], colWidths=[CW])
hlb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LINEBEFORE", (0, 0), (0, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
story += [Spacer(1, 6), hlb, Spacer(1, 12)]

# ───────── TRUST-BADGES ─────────
def badge(t):
    return Paragraph('<font color="#0B1F3A"><b>' + t + '</b></font>',
                     S("bg", fontName="Helvetica-Bold", fontSize=9.5, leading=12, alignment=TA_CENTER))


tb = Table([[badge("Monatlich kündbar"), badge("Kein Auto-Versand"), badge("Daten pro Kunde getrennt")]],
           colWidths=[CW / 3.0] * 3)
tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 6, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
story += [tb]

# ───────── CTA ─────────
cta = [
    Paragraph('<font color="white"><b>Sehen Sie es an einem echten Beispiel &#8212; kostenlos.</b></font>',
              S("c1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.white, spaceAfter=6)),
    Paragraph('<font color="#FFE6D2">In <b>15 Minuten</b> zeige ich Ihnen, wie das für einen Betrieb wie Ihren '
              'aussieht &#8212; und nenne Ihnen 2&#8211;3 konkrete Punkte. Passt es, super. Wenn nicht, '
              'auch völlig in Ordnung.</font>',
              S("c2", fontName="Helvetica", fontSize=11, leading=15.5, textColor=colors.white, spaceAfter=10)),
    Paragraph('<font color="white"><b>Jetzt kurzen Termin sichern:</b>&nbsp;&nbsp; [Telefon] &#160;&#183;&#160; '
              '[E-Mail] &#160;&#183;&#160; [Web]</font>',
              S("c3", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=colors.white)),
    Spacer(1, 6),
    Paragraph('<font color="#FFD9BD">Transparent: Investition ab 890 ' + EUR + '/Monat &#8212; monatlich kündbar, '
              'kein Risiko. Passendes Paket besprechen wir im Erstgespräch.</font>',
              S("c4", fontName="Helvetica", fontSize=8.8, leading=12, textColor=colors.white)),
]
ctab = Table([[cta]], colWidths=[CW])
ctab.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 20), ("RIGHTPADDING", (0, 0), (-1, -1), 20),
    ("TOPPADDING", (0, 0), (-1, -1), 16), ("BOTTOMPADDING", (0, 0), (-1, -1), 16)]))
story += [Spacer(1, 14), ctab]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, 1.0 * cm, "Rebellsystem Akquise-Plattform")
    canvas.drawRightString(A4[0] - MARGIN, 1.0 * cm, "[Ihr Name]  ·  [Firma]  ·  [Web]")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                        title="Rebellsystem Akquise-Plattform - Mehr Termine mit Entscheidern", author="Rebellsystem")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("PDF erstellt:", OUT)
