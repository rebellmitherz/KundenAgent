# -*- coding: utf-8 -*-
"""Kundenfertiges Werbe-/Verkaufs-PDF (FINAL, 1 Seite, zum Mailen)."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)

OUT = r"C:\Users\micha\Desktop\KundenAgent\Rebellsystem_Akquise_fuer_Sie_FINAL.pdf"
LO = "&#8222;"; LC = "&#8220;"; DASH = "&#8212;"; EUR = "&#8364;"; ARR = "&#8250;"

NAVY = colors.HexColor("#0B1F3A"); CYAN = colors.HexColor("#0091B5")
CYAN_SOFT = colors.HexColor("#E7F6FA"); ORANGE = colors.HexColor("#FF7A1A")
INK = colors.HexColor("#1C2530"); GREY = colors.HexColor("#5B6675")
LINE = colors.HexColor("#D6DCE4"); GREEN = colors.HexColor("#1E8E5A")

MARGIN = 1.7 * cm
CW = A4[0] - 2 * MARGIN

S = ParagraphStyle
lead = S("lead", fontName="Helvetica", fontSize=10.8, leading=14.5, textColor=INK, spaceAfter=4)
h2 = S("h2", fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=NAVY, spaceBefore=2, spaceAfter=2)
benefit = S("benefit", fontName="Helvetica", fontSize=10, leading=13, textColor=INK)


def heading(text):
    return KeepTogether([
        Spacer(1, 4),
        Paragraph('<font color="#0091B5"><b>' + text + '</b></font>', h2),
        HRFlowable(width=CW, thickness=2, color=ORANGE, spaceBefore=1, spaceAfter=5, lineCap='round'),
    ])


def check(text):
    return Paragraph('<font color="#1E8E5A"><b>' + ARR + '</b></font>&nbsp;&nbsp;' + text, benefit)


story = []

# HERO
hero_inner = [
    Paragraph('<font color="#7FD8EC"><b>REBELLSYSTEM &#183; AKQUISE-PLATTFORM</b></font>',
              S("kx", fontName="Helvetica-Bold", fontSize=9.5, textColor=colors.white, spaceAfter=7)),
    Paragraph('<font color="white"><b>Mehr Termine mit Entscheidern.<br/>Ohne Kaltakquise-Stress.</b></font>',
              S("hl", fontName="Helvetica-Bold", fontSize=22, leading=25, textColor=colors.white, spaceAfter=8)),
    Paragraph('<font color="#D7E2EE">Ihr persönlicher Akquise-Agent findet passende Firmen, schreibt sie '
              'persönlich an und bringt <b>qualifizierte Gespräche in Ihren Kalender</b>. '
              'Sie entscheiden &#8212; das System arbeitet.</font>',
              S("hs", fontName="Helvetica", fontSize=11.5, leading=16, textColor=colors.white)),
]
hero = Table([[hero_inner]], colWidths=[CW])
hero.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LINEBELOW", (0, 0), (-1, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 22), ("RIGHTPADDING", (0, 0), (-1, -1), 22),
    ("TOPPADDING", (0, 0), (-1, -1), 18), ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
]))
story += [hero, Spacer(1, 8)]

# PROBLEM
story += [Paragraph("Kennen Sie das? Neukunden gewinnen frisst Zeit und Nerven: recherchieren, texten, "
                    "nachfassen, Absagen wegstecken. Und am Monatsende bleibt die Frage: <b>Wie viele echte "
                    "Termine sind eigentlich dabei herausgekommen?</b>", lead)]

# SO EINFACH
story += [heading("So einfach läuft es für Sie")]


def step(num, title, txt):
    return [
        Paragraph('<font color="#FF7A1A"><b>' + num + '</b></font>',
                  S("sn", fontName="Helvetica-Bold", fontSize=20, leading=22, alignment=TA_LEFT)),
        Paragraph('<b>' + title + '</b>', S("stt", fontName="Helvetica-Bold", fontSize=10.3, leading=12,
                  textColor=NAVY, spaceBefore=1, spaceAfter=2)),
        Paragraph('<font color="#1C2530">' + txt + '</font>', S("stx", fontName="Helvetica", fontSize=9, leading=12)),
    ]


steps = Table([[step("1", "Ziel sagen", "Ein Satz genügt: " + LO + "100 Handwerksbetriebe in NRW" + LC + " &#8212; per Telegram oder im Dashboard."),
                step("2", "System arbeitet", "Es sucht passende Firmen, schreibt persönlich an, prüft Antworten und fasst nach."),
                step("3", "Termine erhalten", "Sie bekommen geprüfte Terminchancen gemeldet &#8212; und geben jeden Versand selbst frei.")]],
               colWidths=[CW / 3.0] * 3)
steps.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 6, colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
    ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
]))
story += [steps]

# WAS SIE DAVON HABEN
story += [heading("Was Sie davon haben")]
left = [check("<b>Planbar neue Termine</b> statt Zufall und Flaute."),
        check("<b>Schluss mit stundenlanger Kaltakquise</b> &#8212; das übernimmt der Agent."),
        check("<b>Persönliche Mails</b>, die beim Kunden ansetzen &#8212; kein Spam-Gefühl.")]
right = [check("<b>Nur echte Terminchancen</b> gemeldet (Fehlalarme gefiltert)."),
         check("<b>Volle Kontrolle:</b> nichts geht ohne Ihr Ja raus."),
         check("<b>Ihre Daten bleiben Ihre Daten</b> &#8212; sauber getrennt.")]
left2 = []
for c in left:
    left2 += [c, Spacer(1, 3)]
right2 = []
for c in right:
    right2 += [c, Spacer(1, 3)]
bt = Table([[left2, right2]], colWidths=[CW / 2.0, CW / 2.0])
bt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("RIGHTPADDING", (0, 0), (0, 0), 14), ("LEFTPADDING", (1, 0), (1, 0), 6)]))
story += [bt, Spacer(1, 3)]

# WARUM ANDERS
hl = [
    Paragraph('<font color="white"><b>Warum das anders ist als jedes Lead-Tool</b></font>',
              S("wa", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=colors.white, spaceAfter=4)),
    Paragraph('<font color="#E7F6FA">Die meisten Tools liefern <b>Lead-Masse</b>. Wir liefern, worauf es ankommt: '
              '<b>geprüfte Termine</b>. Der Agent denkt mit, arbeitet eigenständig &#8212; und hält an jedem '
              'wichtigen Punkt an, damit <b>Sie</b> entscheiden. Ehrlich, ruhig, ohne Spam.</font>',
              S("wb", fontName="Helvetica", fontSize=10, leading=14, textColor=colors.white)),
]
hlb = Table([[hl]], colWidths=[CW])
hlb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LINEBEFORE", (0, 0), (0, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 15), ("RIGHTPADDING", (0, 0), (-1, -1), 15),
    ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
story += [Spacer(1, 4), hlb, Spacer(1, 6)]


# TRUST
def badge(t):
    return Paragraph('<font color="#0B1F3A"><b>' + t + '</b></font>',
                     S("bg", fontName="Helvetica-Bold", fontSize=9.3, leading=11, alignment=TA_CENTER))


tb = Table([[badge("Monatlich kündbar"), badge("Kein Auto-Versand"), badge("Daten pro Kunde getrennt")]],
           colWidths=[CW / 3.0] * 3)
tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 6, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
story += [tb]

# CTA
cta = [
    Paragraph('<font color="white"><b>Sehen Sie es an einem echten Beispiel &#8212; kostenlos.</b></font>',
              S("c1", fontName="Helvetica-Bold", fontSize=14, leading=16, textColor=colors.white, spaceAfter=4)),
    Paragraph('<font color="#FFE6D2">In <b>15 Minuten</b> zeige ich Ihnen, wie das für einen Betrieb wie Ihren '
              'aussieht &#8212; und nenne Ihnen 2&#8211;3 konkrete Punkte. Passt es, super. Wenn nicht, '
              'auch völlig in Ordnung.</font>',
              S("c2", fontName="Helvetica", fontSize=10.3, leading=13.5, textColor=colors.white, spaceAfter=7)),
    Paragraph('<font color="white"><b>Jetzt kurzen Termin sichern:</b>&nbsp;&nbsp; 015128141644 &#160;&#183;&#160; '
              'partners@rebellsystem.de &#160;&#183;&#160; rebellsystem.de</font>',
              S("c3", fontName="Helvetica-Bold", fontSize=10.8, leading=14, textColor=colors.white)),
    Spacer(1, 4),
    Paragraph('<font color="#FFD9BD">Transparent: Investition ab 890 ' + EUR + '/Monat &#8212; monatlich kündbar, '
              'kein Risiko. Passendes Paket besprechen wir im Erstgespräch.</font>',
              S("c4", fontName="Helvetica", fontSize=8.6, leading=11.5, textColor=colors.white)),
]
ctab = Table([[cta]], colWidths=[CW])
ctab.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 18), ("RIGHTPADDING", (0, 0), (-1, -1), 18),
    ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
story += [Spacer(1, 8), ctab]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, 1.0 * cm, "Rebellsystem Akquise-Plattform")
    canvas.drawRightString(A4[0] - MARGIN, 1.0 * cm, "Rebellsystem  ·  015128141644  ·  rebellsystem.de")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
                        title="Rebellsystem Akquise-Plattform - Mehr Termine mit Entscheidern", author="Rebellsystem")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("PDF erstellt:", OUT)
