"""Tests für Phase F1 — Signalqualität / Termin-Triage.

Läuft OHNE Engine, ohne Telegram, ohne API-Key.
Aufruf: PYTHONUTF8=1 python product/agent/test_signalqualitaet.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.signalqualitaet import (
    BESTAETIGT,
    KEIN,
    PRUEFEN,
    enthaelt_absage,
    termin_status,
    triage,
)
from product.agent.replies import termine, pruef_termine, antworten_bericht
from product.agent.notifier import meldungen_ermitteln


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _antwort(firma, termin=False, auszug="...", betreff="AW", auto=False,
             grund="", erledigt=False, ek=None):
    return {
        "firma": firma, "betreff": betreff, "auszug": auszug,
        "terminwunsch": termin, "termin_grund": grund,
        "auto_antwort": auto, "erledigt": erledigt,
        "entry_key": ek or firma,
    }


# Der reale Fehlalarm aus b2bbot/output/latest/reply_queue.json (artundweise):
# vom Motor als positive/appointment_ready markiert, Text ist aber eine Absage.
def _artundweise():
    return _antwort(
        "art und weise GmbH",
        termin=True,
        grund="positive_reply",
        betreff="Re: mehr qualifizierte Kundengespraeche?",
        auszug=("Hallo Frau Menges, vielen Dank für Ihre Nachricht. Für die "
                "Terminfindung setzen wir inhouse auf unser eigenes Team. Daher "
                "haben wir aktuell keinen Bedarf – behalten Sie uns aber gerne "
                "im Hinterkopf."),
    )


# ─── Test-Runner ─────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    try:
        fn()
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── enthaelt_absage ─────────────────────────────────────────────────────────


def t_absage_erkennt_kein_bedarf():
    assert enthaelt_absage("Daher haben wir aktuell keinen Bedarf.")
    assert enthaelt_absage("Aktuell kein Interesse, danke.")
    assert enthaelt_absage("Bitte austragen.")


def t_absage_case_insensitive():
    assert enthaelt_absage("WIR HABEN KEINEN BEDARF")


def t_absage_false_bei_echtem_termin():
    assert not enthaelt_absage("Gerne, wann hätten Sie Zeit für ein Gespräch?")
    assert not enthaelt_absage("")


# ─── termin_status ───────────────────────────────────────────────────────────


def t_status_kein_ohne_terminwunsch():
    assert termin_status(_antwort("X", termin=False)) == KEIN


def t_status_pruefen_bei_auto():
    assert termin_status(_antwort("X", termin=True, auto=True)) == PRUEFEN


def t_status_pruefen_bei_absage():
    assert termin_status(_artundweise()) == PRUEFEN


def t_status_bestaetigt_bei_echtem_termin():
    a = _antwort("Y", termin=True, auszug="Sehr gerne, schlagen Sie einen Termin vor.")
    assert termin_status(a) == BESTAETIGT


def t_llm_nein_stuft_herab():
    a = _antwort("Z", termin=True, auszug="freundlicher unklarer Text")
    assert termin_status(a, llm_fn=lambda s, u: "NEIN") == PRUEFEN


def t_llm_ja_bestaetigt():
    a = _antwort("Z", termin=True, auszug="freundlicher unklarer Text")
    assert termin_status(a, llm_fn=lambda s, u: "JA, klar ein Termin") == BESTAETIGT


def t_llm_fehler_faellt_auf_bestaetigt_zurueck():
    def kaputt(s, u):
        raise RuntimeError("API down")
    a = _antwort("Z", termin=True, auszug="freundlicher Text ohne Absage")
    assert termin_status(a, llm_fn=kaputt) == BESTAETIGT


# ─── triage ──────────────────────────────────────────────────────────────────


def t_triage_teilt_korrekt():
    ant = [
        _antwort("Echt", termin=True, auszug="Gerne ein Gespräch nächste Woche."),
        _artundweise(),
        _antwort("Auto", termin=True, auto=True),
        _antwort("KeinTermin", termin=False),
    ]
    s = triage(ant)
    assert [a["firma"] for a in s["bestaetigt"]] == ["Echt"]
    assert {a["firma"] for a in s["pruefen"]} == {"art und weise GmbH", "Auto"}


def t_triage_ignoriert_erledigte():
    ant = [_antwort("Erl", termin=True, auszug="Gerne!", erledigt=True)]
    s = triage(ant)
    assert s["bestaetigt"] == [] and s["pruefen"] == []


def t_triage_schreibt_status_ins_objekt():
    a = _artundweise()
    triage([a])
    assert a["termin_status"] == PRUEFEN


# ─── Integration: replies + notifier ─────────────────────────────────────────


def t_termine_filtert_fehlalarm_raus():
    ant = [_artundweise(), _antwort("Echt", termin=True, auszug="Gerne, Termin?")]
    best = termine(ant)
    pruef = pruef_termine(ant)
    assert [a["firma"] for a in best] == ["Echt"]
    assert [a["firma"] for a in pruef] == ["art und weise GmbH"]


def t_bericht_meldet_fehlalarm_als_pruefung_nicht_als_termin():
    t = antworten_bericht([_artundweise()])
    assert "Termin-Signal" not in t      # kein Fehlalarm
    assert "prüfen" in t.lower()         # ehrlich zur Prüfung


def t_notifier_kein_termin_prio1_bei_fehlalarm():
    m = meldungen_ermitteln([], [_artundweise()], [], set())
    # Es darf KEINE Prio-1-Termin-Meldung geben, sondern eine Prüf-Meldung (Prio 2)
    assert all(x.prioritaet != 1 for x in m)
    assert any("Prüfung" in x.text for x in m)


def t_notifier_echter_termin_bleibt_prio1():
    ant = [_antwort("Echt", termin=True, auszug="Gerne, wann passt ein Termin?")]
    m = meldungen_ermitteln([], ant, [], set())
    assert len(m) == 1 and m[0].prioritaet == 1
    assert "Termin" in m[0].text


if __name__ == "__main__":
    print("\n=== Phase F1 — Signalqualität / Termin-Triage ===\n")
    print("── enthaelt_absage ──")
    test("erkennt 'keinen Bedarf' / 'kein Interesse' / 'austragen'", t_absage_erkennt_kein_bedarf)
    test("case-insensitive", t_absage_case_insensitive)
    test("kein Fehlalarm bei echtem Termin", t_absage_false_bei_echtem_termin)

    print("\n── termin_status ──")
    test("ohne Terminwunsch → KEIN", t_status_kein_ohne_terminwunsch)
    test("Auto-Antwort → PRUEFEN", t_status_pruefen_bei_auto)
    test("Absage-Text → PRUEFEN (artundweise)", t_status_pruefen_bei_absage)
    test("echter Termin → BESTAETIGT", t_status_bestaetigt_bei_echtem_termin)
    test("LLM 'NEIN' stuft herab", t_llm_nein_stuft_herab)
    test("LLM 'JA' bestätigt", t_llm_ja_bestaetigt)
    test("LLM-Fehler → Fallback BESTAETIGT", t_llm_fehler_faellt_auf_bestaetigt_zurueck)

    print("\n── triage ──")
    test("teilt bestätigt/prüfen korrekt", t_triage_teilt_korrekt)
    test("ignoriert erledigte", t_triage_ignoriert_erledigte)
    test("schreibt termin_status ins Objekt", t_triage_schreibt_status_ins_objekt)

    print("\n── Integration replies + notifier ──")
    test("termine() filtert Fehlalarm raus", t_termine_filtert_fehlalarm_raus)
    test("Bericht: Fehlalarm als Prüfung, nicht Termin", t_bericht_meldet_fehlalarm_als_pruefung_nicht_als_termin)
    test("Notifier: kein Prio-1-Termin bei Fehlalarm", t_notifier_kein_termin_prio1_bei_fehlalarm)
    test("Notifier: echter Termin bleibt Prio 1", t_notifier_echter_termin_bleibt_prio1)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
