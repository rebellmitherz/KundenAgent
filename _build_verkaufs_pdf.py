# -*- coding: utf-8 -*-
"""Erzeugt das Verkaufs-PDF (Produktbeschreibung + Telefonleitfaden + Preise).
Deutsche Anfuehrungszeichen als HTML-Entities (&#8222; / &#8220;), echte Umlaute
im Text (Helvetica/WinAnsi kann sie). Keine ASCII-Doublequotes im Inhalt."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)

OUT = r"C:\Users\micha\Desktop\KundenAgent\Rebellsystem_Akquise_Verkaufsleitfaden.pdf"
LO = "&#8222;"   # „
LC = "&#8220;"   # “
DASH = "&#8212;"  # —
EUR = "&#8364;"   # €
MID = "&#183;"    # ·

NAVY      = colors.HexColor("#0B1F3A")
CYAN      = colors.HexColor("#0091B5")
CYAN_SOFT = colors.HexColor("#E7F6FA")
ORANGE    = colors.HexColor("#FF7A1A")
INK       = colors.HexColor("#1C2530")
GREY      = colors.HexColor("#5B6675")
LINE      = colors.HexColor("#D6DCE4")

MARGIN = 1.8 * cm
CONTENT_W = A4[0] - 2 * MARGIN

S = ParagraphStyle
body   = S("body",   fontName="Helvetica", fontSize=10.3, leading=15, textColor=INK, spaceAfter=6)
bodyG  = S("bodyG",  parent=body, textColor=GREY)
bullet = S("bullet", parent=body, leftIndent=12, spaceAfter=3)
h3     = S("h3",     fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=CYAN, spaceBefore=8, spaceAfter=4)
quote  = S("quote",  fontName="Helvetica-Oblique", fontSize=10.3, leading=15, textColor=NAVY)
small  = S("small",  fontName="Helvetica", fontSize=8.6, leading=12, textColor=GREY)
bandst = S("bandst", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.white)
th     = S("th",     fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white, alignment=TA_CENTER)
tprice = S("tprice", fontName="Helvetica-Bold", fontSize=15, leading=17, alignment=TA_CENTER)
obh    = S("obh",    fontName="Helvetica-Bold", fontSize=9.3, leading=12, textColor=NAVY)
obb    = S("obb",    fontName="Helvetica", fontSize=9.3, leading=12.5, textColor=INK)


def band(text):
    t = Table([[Paragraph(text, bandst)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LINEBEFORE", (0, 0), (0, -1), 4, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([Spacer(1, 10), t, Spacer(1, 8)])


def quotebox(text):
    t = Table([[Paragraph(text, quote)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CYAN_SOFT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, CYAN),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 6)])


def bullets(items):
    return [Paragraph("&bull;&nbsp; " + it, bullet) for it in items]


story = []

# ───────── COVER ─────────
cover_inner = [
    Paragraph('<font color="#7FD8EC"><b>REBELLSYSTEM</b></font>',
              S("brand", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, spaceAfter=10)),
    Paragraph('<font color="white"><b>Akquise-Plattform</b></font>',
              S("ct", fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=colors.white, spaceAfter=10)),
    Paragraph('<font color="#C9D6E5">Produktüberblick &amp; Verkaufsleitfaden für den Vertrieb<br/>'
              'inkl. Telefonskript, Einwandbehandlung &amp; Preisen</font>',
              S("cs", fontName="Helvetica", fontSize=12.5, leading=18, textColor=colors.white)),
]
cov = Table([[cover_inner]], colWidths=[CONTENT_W])
cov.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), NAVY),
    ("LINEBELOW", (0, 0), (-1, -1), 5, ORANGE),
    ("LEFTPADDING", (0, 0), (-1, -1), 22), ("RIGHTPADDING", (0, 0), (-1, -1), 22),
    ("TOPPADDING", (0, 0), (-1, -1), 34), ("BOTTOMPADDING", (0, 0), (-1, -1), 30),
]))
story += [Spacer(1, 6), cov, Spacer(1, 16)]
story += [Paragraph('<b>Der persönliche B2B-Akquise-Agent:</b> findet passende Firmen, schreibt persönlich an '
                    'und betreut bis zum Termin ' + DASH + ' <b>vollautomatisch in der Arbeit, menschlich beim Senden.</b>', body)]
story += [Spacer(1, 4)]
story += bullets([
    "Signal-first: die wichtigste Zahl ist der <b>geprüfte Termin</b>, nicht die Lead-Masse.",
    "Human-gated: <b>kein</b> Versand ohne ausdrückliche Freigabe.",
    "Branchenunabhängig &amp; pro Kunde komplett isoliert.",
])
story += [Spacer(1, 14), Paragraph("Vertraulich " + DASH + " für den internen Vertriebseinsatz.", small)]
story += [PageBreak()]

# ───────── WAS IST DAS ─────────
story += [band("Was ist das? (in 30 Sekunden erklärt)")]
story += [Paragraph(
    "Ein zielgetriebener Akquise-Agent, der eine Kampagne eigenständig führt " + DASH + " und an den "
    "entscheidenden Stellen <b>immer den Menschen fragt</b>. Du gibst das Ziel vor (z. B. "
    + LO + "100 Handwerksbetriebe in NRW" + LC + "), das System sucht, qualifiziert, schreibt "
    "persönliche Erstkontakt-Mails, überwacht Antworten und meldet echte Terminchancen " + DASH + " "
    "senden tust du.", body)]

story += [band("Das Problem")]
story += [Paragraph(
    "Neukundengewinnung kostet Zeit, Konstanz und Nerven: recherchieren, texten, nachfassen, "
    "Antworten sortieren. Die meisten Tools liefern <b>Lead-Masse</b> " + DASH + " was wirklich zählt, "
    "sind <b>qualifizierte Gespräche</b>. Genau da setzt das System an.", body)]

story += [band("Die Lösung " + DASH + " so arbeitet das System")]
for i, t in enumerate([
    "<b>Ziel vorgeben</b> " + DASH + " in einem Satz, in normaler Sprache (Telegram oder Dashboard).",
    "<b>Suchen &amp; qualifizieren</b> " + DASH + " passende Firmen (Branche x Region), Telefon Pflicht, keine Dubletten; Lücken füllt der Agent selbst über angrenzende Regionen/Branchen.",
    "<b>Persönlich anschreiben</b> " + DASH + " Mails nach festem Verkaufsrahmen: erst die Situation des Kunden, dann die Lösung als Brücke (kein Werbe-Blabla).",
    "<b>Hartes Tor: Freigabe</b> " + DASH + " gesendet wird nichts ohne dein " + LO + "Ja" + LC + ". Du wählst sogar, wie viele Mails pro Freigabe rausgehen.",
    "<b>Antworten &amp; Termine</b> " + DASH + " Postfach wird automatisch geprüft (nur lesend), echte Termin-Signale erkannt, Fehlalarme aussortiert, Follow-ups gemeldet.",
], 1):
    story += [Paragraph('<font color="#FF7A1A"><b>' + str(i) + '.</b></font>&nbsp; ' + t, bullet)]

story += [band("Kernfunktionen")]
story += bullets([
    "<b>Signal-first Reporting</b> " + DASH + " Hero-Metrik: geprüfte Termine.",
    "<b>Human-gated Versand</b> " + DASH + " kein Auto-Send, volle Kontrolle.",
    "<b>Verkaufsstarke Erstkontakt-Mails</b> " + DASH + " Kundenrealität, Problem, Ursache, Wunsch, Lösung, weicher CTA.",
    "<b>Fehlalarm-Filter</b> " + DASH + " Absagen werden nicht als Termin gefeiert; Unklares kommt " + LO + "zur Prüfung" + LC + ".",
    "<b>Antwort- &amp; Follow-up-Management</b> " + DASH + " automatisch, rein lesend.",
    "<b>Telegram &amp; Dashboard</b> " + DASH + " natürliche Sprache statt Kommando-Syntax.",
    "<b>Live-Closer (optional)</b> " + DASH + " Echtzeit-Gesprächscoaching im Verkaufstelefonat.",
    "<b>Mandanten-Isolation</b> " + DASH + " jeder Kunde ein getrennter Agent, kein Datenvermischen.",
])

story += [band("Für wen &amp; welcher Nutzen")]
story += [Paragraph("<b>Für:</b> Dienstleister, Agenturen, Handwerk, IT, B2B-Anbieter " + DASH + " alle, die planbar an "
                    "Entscheider-Gespräche kommen wollen, ohne ein Vertriebsteam aufzubauen.", body)]
story += [Paragraph("<b>Nutzen:</b> weniger Zeit in der Kaltakquise, <b>mehr geprüfte Termine im Kalender</b> " + DASH + " "
                    "ein System, das rund um die Uhr dranbleibt, aber nie etwas ohne dich verschickt.", body)]
story += [PageBreak()]

# ───────── PREISE ─────────
story += [band("Preise")]
story += [Paragraph("Managed-Service, monatlich. Du betreibst nichts selbst " + DASH + " du bekommst Ergebnisse, "
                    "Reports und Termin-Chancen.", bodyG)]


def tier_cell(name, price, sub, feats, highlight=False):
    name_c = "white" if highlight else "#0B1F3A"
    price_c = "white" if highlight else "#0091B5"
    sub_c = "#D9ECF2" if highlight else "#5B6675"
    feat_c = "white" if highlight else "#1C2530"
    inner = [
        Paragraph('<font color="' + name_c + '"><b>' + name + '</b></font>',
                  S("tn", fontName="Helvetica-Bold", fontSize=12, leading=14, alignment=TA_CENTER)),
        Spacer(1, 3),
        Paragraph('<font color="' + price_c + '"><b>' + price + '</b></font>', tprice),
        Paragraph('<font color="' + sub_c + '">' + sub + '</font>',
                  S("ts", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)),
        Spacer(1, 6),
    ]
    for f in feats:
        inner.append(Paragraph('<font color="' + feat_c + '">&bull;&nbsp; ' + f + '</font>',
                               S("tf", fontName="Helvetica", fontSize=8.6, leading=12)))
    return inner


starter = tier_cell("Starter", "890 " + EUR, "/ Monat " + MID + " zzgl. MwSt", [
    "1 Zielgruppe / Region", "Lead-Suche + Qualitätsprüfung", "Persönliche Erstkontakt-Mails",
    "Freigabe-Workflow (kein Auto-Send)", "Basis-Reporting (Termine)",
])
wachstum = tier_cell("Wachstum", "1.890 " + EUR, "/ Monat " + MID + " zzgl. MwSt", [
    "Alles aus Starter", "Mehrere Zielgruppen / Regionen", "Höheres Sende-Volumen",
    "Antwort-Prüfung + Termin-Triage", "Follow-up-Management", "Dashboard + Telegram",
], highlight=True)
skal = tier_cell("Skalierung", "3.900 " + EUR, "/ Monat " + MID + " zzgl. MwSt", [
    "Alles aus Wachstum", "Maximales Volumen / Priorität", "Live-Closer (Gesprächscoaching)",
    "Mehrere Postfächer / Mandanten", "Persönlicher Ansprechpartner",
])

head = [Paragraph("STARTER", th), Paragraph("WACHSTUM " + MID + " EMPFOHLEN", th), Paragraph("SKALIERUNG", th)]
ptab = Table([head, [starter, wachstum, skal]], colWidths=[CONTENT_W / 3.0] * 3)
ptab.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (0, 0), GREY),
    ("BACKGROUND", (1, 0), (1, 0), ORANGE),
    ("BACKGROUND", (2, 0), (2, 0), GREY),
    ("BACKGROUND", (1, 1), (1, 1), NAVY),
    ("BACKGROUND", (0, 1), (0, 1), colors.white),
    ("BACKGROUND", (2, 1), (2, 1), colors.white),
    ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
    ("VALIGN", (0, 1), (-1, 1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ("LEFTPADDING", (0, 1), (-1, 1), 10), ("RIGHTPADDING", (0, 1), (-1, 1), 10),
    ("TOPPADDING", (0, 1), (-1, 1), 10), ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
]))
story += [ptab, Spacer(1, 8)]
story += [Paragraph("<b>Einrichtung einmalig 490 " + EUR + ".</b> &nbsp; Alternativ <b>Pay-per-Termin ab 120 " + EUR + "</b> "
                    "je qualifiziertem Termin. Alle Preise netto zzgl. MwSt, monatlich kündbar. "
                    "Volumen je nach Zielgruppe/Region.", small)]
story += [Spacer(1, 4)]
story += [Paragraph("<b>Verkaufsanker:</b> Schon <b>1&#8211;2 gewonnene Kunden</b> pro Monat zahlen das System meist "
                    "um ein Vielfaches zurück " + DASH + " der Rest ist planbarer Vorlauf statt Zufall.", body)]
story += [PageBreak()]

# ───────── TELEFONLEITFADEN ─────────
story += [band("Telefonleitfaden " + DASH + " Sympathieverkauf (Mitch-Rau-Modus)")]
story += [Paragraph("<b>Grundhaltung:</b> Menschen kaufen von Menschen, die sie mögen. Erst Sympathie, dann Verkauf. "
                    "Der Kunde ist der Held, du der ruhige, ehrliche Begleiter. Kein Druck, keine Tricks.", body)]
story += bullets([
    "Lächeln aufsetzen " + DASH + " man hört es. Stimme ruhig, warm, langsam.",
    "Ziel ist nicht " + LO + "verkaufen" + LC + ", sondern " + LO + "herausfinden, ob es passt" + LC + " " + DASH + " das nimmt Druck.",
    "Ein " + LO + "Nein" + LC + " ist ok. Entspannt wirkt sympathisch, klammern wirkt verzweifelt.",
])

story += [Paragraph("1. Sympathischer Einstieg " + DASH + " Rapport vor allem", h3)]
story += [quotebox(LO + "Schönen guten Tag, Herr/Frau [Name] " + DASH + " hier ist [Dein Name] von [Firma]. "
                   "Ich hoffe, ich erwische Sie nicht völlig im Stress?" + LC + " <i>(kurz warten, echt zuhören)</i>")]

story += [Paragraph("2. Der ehrliche Grund " + DASH + " kein Pitch", h3)]
story += [quotebox(LO + "Ich bin ehrlich mit Ihnen: Das ist ein geplanter Anruf " + DASH + " aber ein freundlicher. "
                   "Ich habe mir [Firma] angeschaut und hatte einen konkreten Gedanken dazu. "
                   "Darf ich Ihnen das in zwei Sätzen sagen " + DASH + " und Sie sagen mir, ob es für Sie Sinn macht?" + LC)]

story += [Paragraph("3. Fragen statt behaupten " + DASH + " den Kunden reden lassen (70 %)", h3)]
story += [quotebox(LO + "Wie läuft bei Ihnen aktuell die Neukundengewinnung " + DASH + " eher über Empfehlung oder aktiv?" + LC + "<br/>"
                   + LO + "Und ganz offen: Was nervt Sie daran am meisten?" + LC + "<br/>"
                   + LO + "Angenommen, das würde einfach laufen " + DASH + " was würde sich für Sie ändern?" + LC)]
story += [Paragraph("Aktiv zuhören &amp; spiegeln: " + LO + "Verstehe." + LC + " " + MID + " " + LO + "Das macht Sinn." + LC
                    + " " + MID + " " + LO + "Da sind Sie nicht allein." + LC, bodyG)]

story += [Paragraph("4. Die Brücke " + DASH + " Lösung als logische Folge", h3)]
story += [quotebox(LO + "Dann passt das, glaube ich, gut zu Ihnen. Wir helfen Unternehmen wie Ihrem, planbar an echte "
                   "Termine mit Entscheidern zu kommen " + DASH + " ohne stundenlanges Telefonieren oder eigenes Vertriebsteam. "
                   "Das System sucht, schreibt an und betreut " + DASH + " aber Sie behalten jederzeit die Hand drauf." + LC)]

story += [Paragraph("5. Weicher, klarer Abschluss " + DASH + " der Termin", h3)]
story += [quotebox(LO + "Ich schlage was Unkompliziertes vor: 15 Minuten, ich zeige Ihnen, wie das bei einem Betrieb wie "
                   "Ihrem aussähe. Passt " + DASH + " super; passt nicht " + DASH + " auch völlig in Ordnung. "
                   "Wäre Ihnen Anfang nächster Woche oder eher Ende der Woche lieber?" + LC)]
story += [Paragraph("Alternativfrage statt Ja/Nein. Der Termin ist der nächste Schritt " + DASH + " nicht der Verkauf am Telefon.", bodyG)]
story += [PageBreak()]

# ───────── EINWANDBEHANDLUNG ─────────
story += [band("Einwandbehandlung " + DASH + " sympathisch, nie dagegen")]
story += [Paragraph("Regel: erst verstehen/zustimmen, dann sanft weiterführen. Nie rechtfertigen, nie drängen.", bodyG)]

einwaende = [
    (LO + "Keine Zeit." + LC,
     "Total verständlich " + DASH + " deshalb will ich sie Ihnen nicht klauen. Genau dafür die 15 Minuten, zu einem "
     "Zeitpunkt, der <b>Ihnen</b> passt. Wann wäre es am wenigsten störend?"),
    (LO + "Kein Interesse." + LC,
     "Völlig fair " + DASH + " Sie wissen ja noch gar nicht, ob es taugt. Darf ich kurz fragen: Liegt es daran, dass "
     "gerade genug läuft, oder gab es mit sowas schon schlechte Erfahrung?"),
    (LO + "Schicken Sie was per Mail." + LC,
     "Mach ich gern. Damit es nicht untergeht: Soll ich Ihnen das <b>Konkrete für Ihren Fall</b> schicken? Dann "
     "brauche ich 2 Minuten Ihrer Einschätzung " + DASH + " passt jetzt kurz, oder wann?"),
    (LO + "Zu teuer / was kostet das?" + LC,
     "Verstehe, dass das wichtig ist. Lassen Sie uns kurz schauen, ob es überhaupt passt " + DASH + " sonst ist jeder "
     "Preis zu hoch. Wenn es passt, rechnet es sich meist über die ersten ein, zwei Termine."),
    (LO + "Haben wir schon." + LC,
     "Stark, dass Sie da dran sind! Dann ist die spannende Frage: Kommen genug <b>wirklich qualifizierte</b> "
     "Termine raus " + DASH + " oder viel Streuverlust?"),
]
rows = [[Paragraph("Einwand", th), Paragraph("Sympathie-Antwort", th)]]
for e, a in einwaende:
    rows.append([Paragraph(e, obh), Paragraph(a, obb)])
etab = Table(rows, colWidths=[CONTENT_W * 0.28, CONTENT_W * 0.72])
estyle = [
    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
]
for r in range(1, len(rows)):
    if r % 2 == 0:
        estyle.append(("BACKGROUND", (0, r), (-1, r), CYAN_SOFT))
etab.setStyle(TableStyle(estyle))
story += [etab, Spacer(1, 10)]

story += [band("Dos &amp; Don'ts")]
do_col = [Paragraph('<font color="#1E8E5A"><b>DO</b></font>', S("d", fontName="Helvetica-Bold", fontSize=10.5))]
do_col += bullets(["lächeln, langsam reden", "Pausen aushalten", "ehrlich sein, Namen nennen",
                   "fragen, zuhören, spiegeln", "Kontrolle abgeben"])
dont_col = [Paragraph('<font color="#B23B3B"><b>DON\'T</b></font>', S("d2", fontName="Helvetica-Bold", fontSize=10.5))]
dont_col += bullets(["Monolog halten", "Skript runterleiern", "Druck machen, übertreiben",
                     "rechtfertigen, " + LO + "kämpfen" + LC, "den Abschluss erzwingen"])
dos = Table([[do_col, dont_col]], colWidths=[CONTENT_W / 2.0, CONTENT_W / 2.0])
dos.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#EAF7F0")),
    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#FBECEC")),
    ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
]))
story += [dos]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 1.35 * cm, A4[0] - MARGIN, 1.35 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, 1.0 * cm, "Rebellsystem Akquise-Plattform  -  Produktüberblick & Verkaufsleitfaden")
    canvas.drawRightString(A4[0] - MARGIN, 1.0 * cm, "Seite %d" % doc.page)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                        topMargin=1.6 * cm, bottomMargin=1.7 * cm,
                        title="Rebellsystem Akquise-Plattform - Verkaufsleitfaden", author="Rebellsystem")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("PDF erstellt:", OUT)
