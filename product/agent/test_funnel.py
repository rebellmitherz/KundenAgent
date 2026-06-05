"""Tests für Phase C — Kampagnen-Trichter (funnel.py + campaign.py + Runner).

Läuft OHNE Engine. Aufruf: PYTHONUTF8=1 python product/agent/test_funnel.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.agent.campaign import KampagnenSpeicher, _slug
from product.agent.funnel import STUFEN, funnel_aus_rohdaten, funnel_bericht, stufe_von
from product.agent.runner import AgentRunner


def _e(ek, gesendet=False, bereit=False, email=""):
    return {"entry_key": ek, "firma": ek, "ort": "X", "ansprechpartner": "Y",
            "gesendet": gesendet, "bereit": bereit, "email": email}


# ─── Runner-Mock-Bridge ──────────────────────────────────────────────────────


class MockBridge:
    def __init__(self, roh):
        self._roh = roh
        self.campaign = "nicht_gesetzt"

    def kampagne_rohdaten(self, campaign=None, limit=1000):
        self.campaign = campaign
        return self._roh


# ─── Runner ──────────────────────────────────────────────────────────────────

_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"  ✓  {name}")
        _ok += 1
    except Exception:
        print(f"  ✗  {name}")
        traceback.print_exc(limit=4)
        _fail += 1


# ─── stufe_von ───────────────────────────────────────────────────────────────

def t_stufe_termin(_d):
    assert stufe_von(_e("k1", gesendet=True), {"k1"}, {"k1"}) == "termin"


def t_stufe_geantwortet(_d):
    assert stufe_von(_e("k1", gesendet=True), {"k1"}, set()) == "geantwortet"


def t_stufe_angeschrieben(_d):
    assert stufe_von(_e("k1", gesendet=True), set(), set()) == "angeschrieben"


def t_stufe_bereit(_d):
    assert stufe_von(_e("k1", bereit=True), set(), set()) == "bereit"


def t_stufe_gefunden(_d):
    assert stufe_von(_e("k1"), set(), set()) == "gefunden"


def t_termin_vor_antwort(_d):
    """Termin schlägt geantwortet, auch wenn beide Keys passen."""
    assert stufe_von(_e("k1", gesendet=True), {"k1"}, {"k1"}) == "termin"


# ─── funnel_aus_rohdaten ─────────────────────────────────────────────────────

def t_funnel_zaehlt_alle_stufen(_d):
    roh = {
        "entries": [
            _e("a"),                      # gefunden
            _e("b", bereit=True),         # bereit
            _e("c", gesendet=True),       # angeschrieben
            _e("d", gesendet=True),       # geantwortet
            _e("e", gesendet=True),       # termin
        ],
        "antwort_keys": ["d", "e"],
        "termin_keys": ["e"],
    }
    f = funnel_aus_rohdaten(roh)
    assert f["gesamt"] == 5
    assert f["stufen"] == {"gefunden": 1, "bereit": 1, "angeschrieben": 1,
                           "geantwortet": 1, "termin": 1}


def t_funnel_lead_limit(_d):
    roh = {"entries": [_e(f"k{i}") for i in range(100)], "antwort_keys": [], "termin_keys": []}
    f = funnel_aus_rohdaten(roh, lead_limit=10)
    assert f["gesamt"] == 100              # Zählung vollständig
    assert len(f["leads"]) == 10           # Anzeige gekürzt


def t_funnel_leer(_d):
    f = funnel_aus_rohdaten({"entries": [], "antwort_keys": [], "termin_keys": []})
    assert f["gesamt"] == 0


# ─── F2: Domain-Fallback-Join + 'ohne Bezug' ────────────────────────────────

def t_stufe_domain_fallback_termin(_d):
    """Kein Key-Treffer, aber Domain-Treffer → termin."""
    e = _e("k1", gesendet=True, email="chef@alpha.de")
    s = stufe_von(e, set(), set(), {"alpha.de"}, {"alpha.de"})
    assert s == "termin"


def t_stufe_domain_fallback_geantwortet(_d):
    e = _e("k1", gesendet=True, email="chef@alpha.de")
    assert stufe_von(e, set(), set(), {"alpha.de"}, set()) == "geantwortet"


def t_stufe_key_schlaegt_immer_an(_d):
    """Key-Treffer reicht auch ohne Domain (Rückwärtskompatibilität)."""
    assert stufe_von(_e("k1", gesendet=True), {"k1"}, set()) == "geantwortet"


def t_funnel_domain_join_zaehlt(_d):
    roh = {
        "entries": [_e("a", gesendet=True, email="x@alpha.de")],
        "antwort_keys": [], "termin_keys": [],
        "antwort_domains": ["alpha.de"], "termin_domains": ["alpha.de"],
    }
    f = funnel_aus_rohdaten(roh)
    assert f["stufen"]["termin"] == 1


def t_bericht_zeigt_ohne_bezug(_d):
    f = {"gesamt": 2, "stufen": {"gefunden": 0, "bereit": 0, "angeschrieben": 2,
                                 "geantwortet": 0, "termin": 0},
         "antwort_ohne_bezug": 3, "termin_ohne_bezug": 1}
    t = funnel_bericht(f)
    assert "3 Antwort" in t and "ohne Bezug" in t
    assert "1 mit Termin-Signal" in t


# ─── funnel_bericht ──────────────────────────────────────────────────────────

def t_bericht_leer(_d):
    assert "Noch keine Leads" in funnel_bericht({"gesamt": 0, "stufen": {}})


def t_bericht_zeigt_alle_stufen(_d):
    f = {"gesamt": 5, "stufen": {"gefunden": 1, "bereit": 1, "angeschrieben": 1,
                                 "geantwortet": 1, "termin": 1}}
    t = funnel_bericht(f)
    for label in ("gefunden", "versandbereit", "angeschrieben", "geantwortet", "Termine"):
        assert label in t
    assert "🎯 1 Termin" in t


def t_bericht_trend_delta(_d):
    f = {"gesamt": 10, "stufen": {"gefunden": 2, "bereit": 2, "angeschrieben": 3,
                                  "geantwortet": 2, "termin": 1}}
    vorher = {"gefunden": 2, "bereit": 2, "angeschrieben": 1, "geantwortet": 0, "termin": 0}
    t = funnel_bericht(f, vorher=vorher)
    assert "(+2)" in t   # angeschrieben +2 oder geantwortet +2
    assert "(+1)" in t   # termin +1


# ─── KampagnenSpeicher ───────────────────────────────────────────────────────

def t_snapshot_und_verlauf(d):
    sp = KampagnenSpeicher(d)
    sp.snapshot_speichern("gesamt", {"gesamt": 5, "stufen": {"termin": 0}})
    sp.snapshot_speichern("gesamt", {"gesamt": 6, "stufen": {"termin": 1}})
    v = sp.verlauf("gesamt")
    assert len(v) == 2
    assert v[-1]["stufen"]["termin"] == 1
    assert sp.letzter("gesamt")["gesamt"] == 6


def t_snapshot_persistenz(d):
    KampagnenSpeicher(d).snapshot_speichern("cmp-x", {"gesamt": 3, "stufen": {}})
    # Neue Instanz (Neustart)
    assert len(KampagnenSpeicher(d).verlauf("cmp-x")) == 1


def t_verlauf_kappung(d):
    sp = KampagnenSpeicher(d, max_verlauf=5)
    for i in range(8):
        sp.snapshot_speichern("g", {"gesamt": i, "stufen": {}})
    v = sp.verlauf("g")
    assert len(v) == 5
    assert v[-1]["gesamt"] == 7          # neueste behalten

def t_slug_sicher(_d):
    assert _slug("cmp-2026/06 local!") == "cmp-2026_06_local"
    assert _slug("") == "gesamt"


def t_letzter_leer(d):
    assert KampagnenSpeicher(d).letzter("gibt_es_nicht") is None


# ─── Runner-Integration ──────────────────────────────────────────────────────

def t_runner_funnel(d):
    roh = {"entries": [_e("a", gesendet=True), _e("b", bereit=True)],
           "antwort_keys": [], "termin_keys": []}
    runner = AgentRunner(MockBridge(roh), data_dir=d)
    f = runner.funnel()
    assert f["stufen"]["angeschrieben"] == 1
    assert f["stufen"]["bereit"] == 1


def t_runner_snapshot_und_trend(d):
    roh1 = {"entries": [_e("a", gesendet=True)], "antwort_keys": [], "termin_keys": []}
    bridge = MockBridge(roh1)
    runner = AgentRunner(bridge, data_dir=d)
    runner.funnel_snapshot()                      # speichert ersten Stand
    # Zweiter Stand: a hat jetzt geantwortet
    bridge._roh = {"entries": [_e("a", gesendet=True)], "antwort_keys": ["a"], "termin_keys": []}
    bericht = runner.funnel_bericht()
    assert "(+1)" in bericht                      # geantwortet +1 ggü. Snapshot
    assert len(runner.funnel_verlauf()) == 1


def t_runner_campaign_durchgereicht(d):
    bridge = MockBridge({"entries": [], "antwort_keys": [], "termin_keys": []})
    runner = AgentRunner(bridge, data_dir=d)
    runner.funnel(campaign="cmp-123")
    assert bridge.campaign == "cmp-123"


def t_runner_ohne_bridge(d):
    runner = AgentRunner(None, data_dir=d)
    assert runner.funnel()["gesamt"] == 0
    assert "Noch keine Leads" in runner.funnel_bericht()


if __name__ == "__main__":
    print("\n=== Phase C — Kampagnen-Trichter ===\n")
    print("── stufe_von ──")
    test("Termin", t_stufe_termin)
    test("geantwortet", t_stufe_geantwortet)
    test("angeschrieben", t_stufe_angeschrieben)
    test("bereit", t_stufe_bereit)
    test("gefunden", t_stufe_gefunden)
    test("Termin vor geantwortet", t_termin_vor_antwort)

    print("\n── funnel_aus_rohdaten ──")
    test("zählt alle Stufen", t_funnel_zaehlt_alle_stufen)
    test("Lead-Limit (Zählung bleibt voll)", t_funnel_lead_limit)
    test("leer", t_funnel_leer)

    print("\n── F2: Domain-Join + ohne Bezug ──")
    test("stufe_von Domain-Fallback → termin", t_stufe_domain_fallback_termin)
    test("stufe_von Domain-Fallback → geantwortet", t_stufe_domain_fallback_geantwortet)
    test("stufe_von Key schlägt an (rückwärtskompatibel)", t_stufe_key_schlaegt_immer_an)
    test("funnel zählt Domain-Join", t_funnel_domain_join_zaehlt)
    test("Bericht zeigt 'ohne Bezug'", t_bericht_zeigt_ohne_bezug)

    print("\n── funnel_bericht ──")
    test("leer → Hinweis", t_bericht_leer)
    test("zeigt alle Stufen + Termin", t_bericht_zeigt_alle_stufen)
    test("Trend-Delta", t_bericht_trend_delta)

    print("\n── KampagnenSpeicher ──")
    test("Snapshot + Verlauf", t_snapshot_und_verlauf)
    test("Persistenz über Neustart", t_snapshot_persistenz)
    test("Verlauf-Kappung", t_verlauf_kappung)
    test("Slug sicher", t_slug_sicher)
    test("letzter leer → None", t_letzter_leer)

    print("\n── Runner-Integration ──")
    test("funnel()", t_runner_funnel)
    test("Snapshot + Trend im Bericht", t_runner_snapshot_und_trend)
    test("campaign durchgereicht", t_runner_campaign_durchgereicht)
    test("ohne Bridge → leer", t_runner_ohne_bridge)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
