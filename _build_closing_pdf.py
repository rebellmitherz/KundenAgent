# -*- coding: utf-8 -*-
"""Closing-Leitfaden (Abschlussgespraech) als PDF — Sympathieverkauf-Modus.
Gleiches Design wie der Verkaufsleitfaden. Deutsche Quotes als Entities."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)

OUT = r"C:\Users\micha\Desktop\KundenAgent\Rebellsystem_Closing_Leitfaden.pdf"
LO = "&#8222;"   # „
LC = "&#8220;"   # “
DASH = "&#8212;"
EUR = "&#8364;"
MID = "&#183;"

NAVY = colors.HexColor("#0B1F3A"); CYAN = colors.HexColor("#0091B5")
CYAN_SOFT = colors.HexColor("#E7F6FA"); ORANGE = colors.HexColor("#FF7A1A")
INK = colors.HexColor("#1C2530"); GREY = colors.HexColor("#5B6675")
LINE = colors.HexColor("#D6DCE4")

MARGIN = 1.8 * cm
CONTENT_W = A4[0] - 2 * MARGIN

S = ParagraphStyle
body  = S("body", fontName="Helvetica", fontSize=10.3, leading=15, textColor=INK, spaceAfter=6)
bodyG = S("bodyG", parent=body, textColor=GREY)
bullet = S("bullet", parent=body, leftIndent=12, spaceAfter=3)
h3 = S("h3", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=CYAN, spaceBefore=8, spaceAfter=4)
quote = S("quote", fontName="Helvetica-Oblique", fontSize=10.3, leading=15, textColor=NAVY)
small = S("small", fontName="Helvetica", fontSize=8.6, leading=12, textColor=GREY)
bandst = S("bandst", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.white)
th = S("th", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white, alignment=TA_CENTER)
obh = S("obh", fontName="Helvetica-Bold", fontSize=9.3, leading=12, textColor=NAVY)
obb = S("obb", fontName="Helvetica", fontSize=9.3, leading=12.5, textColor=INK)


def band(text):
    t = Table([[Paragraph(text, bandst)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LINEBEFORE", (0, 0), (0, -1), 4, ORANGE), ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([Spacer(1, 10), t, Spacer(1, 8)])


def quotebox(text):
    t = Table([[Paragraph(text, quote)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, CYAN), ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([t, Spacer(1, 6)])


def bullets(items):
    return [Paragraph("&bull;&nbsp; " + it, bullet) for it in items]


story = []

# COVER
cov_in = [
    Paragraph('<font color="#7FD8EC"><b>REBELLSYSTEM</b></font>',
              S("b1", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, spaceAfter=10)),
    Paragraph('<font color="white"><b>Closing-Leitfaden</b></font>',
              S("b2", fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=colors.white, spaceAfter=8)),
    Paragraph('<font color="#C9D6E5">Das Abschlussgespräch im Sympathieverkauf-Modus<br/>'
              'für Termine aus dem System &amp; aus der Kaltakquise</font>',
              S("b3", fontName="Helvetica", fontSize=12.5, leading=18, textColor=colors.white)),
]
cov = Table([[cov_in]], colWidths=[CONTENT_W])
cov.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LINEBELOW", (0, 0), (-1, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 22), ("RIGHTPADDING", (0, 0), (-1, -1), 22),
    ("TOPPADDING", (0, 0), (-1, -1), 34), ("BOTTOMPADDING", (0, 0), (-1, -1), 30)]))
story += [Spacer(1, 6), cov, Spacer(1, 16)]
story += [Paragraph("<b>Der Termin ist der halbe Erfolg " + DASH + " das Abschlussgespräch macht ihn ganz.</b> "
                    "Dieser Leitfaden führt dich ruhig und sympathisch vom ersten Hallo bis zum klaren Ja "
                    "(oder einem sauberen nächsten Schritt).", body)]
story += [Spacer(1, 10), Paragraph("Vertraulich " + DASH + " für den internen Vertriebseinsatz.", small)]
story += [PageBreak()]

# GRUNDHALTUNG + VORBEREITUNG
story += [band("Grundhaltung im Abschlussgespräch")]
story += bullets([
    "Ziel ist nicht " + LO + "drücken" + LC + ", sondern gemeinsam prüfen, ob es wirklich passt. Wer nicht muss, verkauft am besten.",
    "Beziehung zuerst: Der Kunde kauft erst dich, dann die Lösung.",
    "Den Preis ruhig und freundlich nennen " + DASH + " und dann <b>schweigen</b>.",
    "Ein " + LO + "Nein" + LC + " ist erlaubt. Druck zerstört Sympathie und Abschluss.",
    "Du führst das Gespräch (Agenda, Fragen, Tempo) " + DASH + " sicher, aber locker.",
])
story += [band("Vorbereitung (5 Minuten vorher)")]
story += bullets([
    "Quelle des Termins checken: Worauf hat er reagiert (System-Mail / Kaltakquise)?",
    "Firma kurz ansehen (Website, Branche) " + DASH + " 2&#8211;3 Hypothesen zum möglichen Schmerz.",
    "Gesprächsziel festlegen: klares Ja, klares Nein <b>oder</b> konkreter nächster Schritt " + DASH + " kein " + LO + "mal sehen" + LC + ".",
    "Beispiel/Demo &amp; Preise griffbereit. Wasser, Ruhe, Lächeln.",
])
story += [PageBreak()]

# PHASEN 1-3
story += [band("Phase 1 " + DASH + " Eröffnung &amp; Rahmen (erste 2&#8211;3 Min)")]
story += [quotebox(LO + "Schön, dass es klappt, Herr/Frau [Name]! Wie war Ihr Tag bisher?" + LC + " <i>(echt, kurz, warm)</i>")]
story += [Paragraph("Dann den Rahmen setzen (gibt Sicherheit + Kontrolle):", body)]
story += [quotebox(LO + "Ich schlage vor: Ich stelle Ihnen ein paar Fragen, um zu verstehen, wie es bei Ihnen läuft. "
                   "Wenn ich denke, ich kann helfen, sage ich es Ihnen ehrlich " + DASH + " und wenn nicht, auch. "
                   "Passt das so für Sie?" + LC)]

story += [band("Phase 2 " + DASH + " Diagnose: Fragen (der Kunde redet 70 %)")]
story += [quotebox(LO + "Wie gewinnen Sie heute neue Kunden " + DASH + " und wie zufrieden sind Sie damit?" + LC + "<br/>"
                   + LO + "Was hat Sie dazu gebracht, sich den Termin überhaupt zu nehmen?" + LC + " <i>(= Kaufmotiv!)</i><br/>"
                   + LO + "Was würde sich für Sie ändern, wenn das einfach laufen würde?" + LC + "<br/>"
                   + LO + "Was kostet Sie das Thema aktuell " + DASH + " an Zeit oder verpassten Aufträgen?" + LC)]
story += [Paragraph("Zuhören, mitschreiben, spiegeln. Das <b>Kaufmotiv</b> ist Gold " + DASH + " merk es dir wörtlich.", bodyG)]

story += [band("Phase 3 " + DASH + " Zusammenfassen &amp; Einigkeit")]
story += [quotebox(LO + "Wenn ich Sie richtig verstanden habe: [Schmerz] nervt Sie gerade, und eigentlich wollen Sie "
                   "[Wunsch]. Habe ich das so richtig?" + LC)]
story += [Paragraph("Erst wenn er <b>Ja</b> sagt, geht es weiter. Du verkaufst gegen den Schmerz, den ER bestätigt hat.", body)]
story += [PageBreak()]

# PHASEN 4-6
story += [band("Phase 4 " + DASH + " Lösung als Brücke (nur das Passende)")]
story += [quotebox(LO + "Dann zeige ich Ihnen genau den Teil, der zu Ihrer Situation passt " + DASH + " den Rest "
                   "sparen wir uns." + LC)]
story += [Paragraph("Kein Feature-Dump. Nutzen in <b>seiner</b> Sprache, an <b>seinem</b> Schmerz. Kunde = Held, "
                    "Produkt = Brücke.", body)]

story += [band("Phase 5 " + DASH + " Preis souverän nennen &#8230; dann schweigen")]
story += [quotebox(LO + "Für Ihren Fall passt das Paket Wachstum: 1.890 " + EUR + " im Monat, plus einmalig 490 " + EUR + " "
                   "Einrichtung." + LC + " <i>(jetzt bewusst Pause " + DASH + " nichts mehr sagen)</i>")]
story += bullets([
    "<b>Wert vor Preis:</b> " + LO + "Ein einziger gewonnener Kunde deckt das meist mehrfach." + LC,
    "<b>Risiko umkehren:</b> " + LO + "Monatlich kündbar " + DASH + " Sie gehen keine lange Bindung ein." + LC,
    "<b>Nicht rechtfertigen, nicht nachschieben.</b> Wer nach dem Preis weiterredet, verhandelt gegen sich selbst.",
])

story += [band("Phase 6 " + DASH + " Abschluss: weich, aber klar")]
story += [Paragraph("Wähle eine Variante " + DASH + " dann ruhig die Antwort abwarten:", body)]
story += bullets([
    "<b>Annahme-Abschluss:</b> " + LO + "Aus meiner Sicht passt das richtig gut. Sollen wir es aufsetzen?" + LC,
    "<b>Alternativ-Abschluss:</b> " + LO + "Starten wir mit Wachstum " + DASH + " oder erst mit Starter?" + LC,
    "<b>Skala-Abschluss:</b> " + LO + "Auf einer Skala von 1 bis 10 " + DASH + " wie gut passt das für Sie?" + LC
    + " &nbsp;Bei 7&#8211;8: " + LO + "Was fehlt zur 10?" + LC + " (= der echte Einwand).",
])
story += [PageBreak()]

# EINWANDBEHANDLUNG
story += [band("Einwandbehandlung im Closing")]
story += [Paragraph("Einwand = Interesse + offene Frage. Erst verstehen, dann den <b>echten</b> Grund finden, "
                    "dann sanft weiterführen. Nie rechtfertigen, nie drängen.", bodyG)]
ew = [
    (LO + "Zu teuer." + LC,
     "Verstehe. Lassen Sie uns kurz rechnen: Was ist Ihnen <b>ein</b> neuer Kunde wert? " + DASH + " Dann trägt "
     "sich das oft schon ab dem ersten. Geht es ums Geld an sich, oder um die Sicherheit, dass es funktioniert?"),
    (LO + "Ich muss überlegen." + LC,
     "Total ok. Damit ich Sie nicht im Regen stehen lasse: Ist es eher das Bauchgefühl, der Preis oder das Timing?"),
    (LO + "Muss ich mit [Partner] besprechen." + LC,
     "Sinnvoll. Was glauben Sie, ist seine/ihre erste Frage? Lassen Sie es uns jetzt klären, damit Sie es gut "
     "erklären können " + DASH + " oder holen wir ihn/sie kurz dazu?"),
    (LO + "Schicken Sie ein Angebot." + LC,
     "Mach ich gern. Angenommen, Preis und Leistung passen " + DASH + " gibt es dann noch etwas, das Sie vom "
     "Start abhalten würde?"),
    (LO + "Kein Budget." + LC,
     "Verstehe. Heißt das grundsätzlich interessant, nur gerade die Mittel? Dann reden wir über Starter oder "
     "Pay-per-Termin " + DASH + " kleiner anfangen, mitwachsen."),
    (LO + "Läuft auch so ganz ok." + LC,
     "Schön zu hören! Was würde passieren, wenn Sie zusätzlich planbar 3&#8211;5 qualifizierte Termine im Monat "
     "hätten " + DASH + " ohne Mehraufwand für Sie?"),
]
rows = [[Paragraph("Einwand", th), Paragraph("Sympathie-Antwort", th)]]
for e, a in ew:
    rows.append([Paragraph(e, obh), Paragraph(a, obb)])
et = Table(rows, colWidths=[CONTENT_W * 0.27, CONTENT_W * 0.73])
est = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
       ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
       ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
       ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]
for r in range(1, len(rows)):
    if r % 2 == 0:
        est.append(("BACKGROUND", (0, r), (-1, r), CYAN_SOFT))
et.setStyle(TableStyle(est))
story += [et]
story += [PageBreak()]

# NACH DEM JA / BEI NEIN / CHECKLISTE
story += [band("Nach dem Ja " + DASH + " sauber landen")]
story += bullets([
    "Bestätigen &amp; Sicherheit geben: " + LO + "Sehr gute Entscheidung " + DASH + " Sie werden den Unterschied schnell merken." + LC,
    "Konkrete nächste Schritte: Onboarding, Zugang, erster Lauf " + DASH + " mit Datum.",
    "Kurzen Kickoff-Termin direkt fixieren. Vorfreude erzeugen, ehrlich freuen.",
])
story += [band("Bei Nein oder Vielleicht " + DASH + " Tür offen halten")]
story += [quotebox(LO + "Völlig in Ordnung " + DASH + " danke für Ihre Offenheit. Darf ich mich in [3&#8211;4 Wochen] "
                   "nochmal kurz bei Ihnen melden?" + LC)]
story += [Paragraph("Sympathie behalten, konkreten Follow-up vereinbaren, nichts verbrennen. Ein gutes " + LO + "Nein, "
                    "noch nicht" + LC + " ist mehr wert als ein erzwungenes Ja.", body)]

story += [band("Closing-Checkliste (kurz)")]
story += bullets([
    "Kaufmotiv verstanden (wörtlich)?",
    "Schmerz + Wunsch gespiegelt und bestätigt?",
    "Nur das Passende gezeigt (kein Feature-Dump)?",
    "Preis souverän genannt " + DASH + " und geschwiegen?",
    "Den <b>echten</b> Einwand gefunden (nicht den ersten)?",
    "Klaren nächsten Schritt mit Datum vereinbart?",
])
story += [band("Die 6 Closing-Don'ts")]
story += bullets([
    "Nach dem Preis weiterreden / sich rausreden.",
    "Rechtfertigen oder sich kleinmachen.",
    "Druck aufbauen oder zu früh Rabatt geben.",
    "Monolog statt Dialog.",
    "Den ersten Einwand für bare Münze nehmen.",
    "Dem " + LO + "Nein" + LC + " hinterherjagen.",
])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 1.35 * cm, A4[0] - MARGIN, 1.35 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, 1.0 * cm, "Rebellsystem  -  Closing-Leitfaden (Abschlussgespräch)")
    canvas.drawRightString(A4[0] - MARGIN, 1.0 * cm, "Seite %d" % doc.page)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                        topMargin=1.6 * cm, bottomMargin=1.7 * cm,
                        title="Rebellsystem - Closing-Leitfaden", author="Rebellsystem")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("PDF erstellt:", OUT)
