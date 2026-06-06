"""Sicherer Test des Freigabe-Limit-Clamps (Mini-Patch) — OHNE echten Versand.

Belegt:
  - Bridge clampt das Sende-Limit auf 1..50 (9999→50, 0→1, 7→7) und reicht den
    geclampten Wert als `--outreach-limit` an die Engine durch — der echte
    Subprozess (`_run`) wird abgefangen, es wird NICHTS gesendet.
  - Server-Endpoint /api/freigabe clampt ebenfalls auf 1..50 (Default 20) und
    übergibt den geclampten Wert an die Bridge — Bridge ist hier ein Fake,
    kein realer Versand.
  - UI: dashboard.html enthält das Dropdown (5/10/20/50) + die Clamp-Logik.

Aufruf: PYTHONUTF8=1 python product/bridge/test_freigabe_limit.py
"""
from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.bridge.engine_bridge import EngineBridge

_ENGINE_DIR = ROOT / "b2bbot"   # enthält mine.py (nur für Konstruktion nötig)

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


def _limit_aus_args(calls) -> int:
    """Holt den --outreach-limit-Wert aus dem ERSTEN abgefangenen _run-Aufruf."""
    args = calls[0][0]
    return int(args[args.index("--outreach-limit") + 1])


def _bridge_mit_abfang():
    """EngineBridge, deren echter Versand (_run) + status_lesen abgefangen sind."""
    b = EngineBridge(_ENGINE_DIR)
    calls = []

    def fake_run(args, timeout=120, extra_env=None):
        calls.append((args, extra_env))
        return (0, "OK (abgefangen, kein echter Aufruf)")

    b._run = fake_run                      # type: ignore[assignment]
    b.status_lesen = lambda: {"sent_total": 0}   # type: ignore[assignment]
    return b, calls


# ─── Bridge-Clamp (realer Code, kein Versand) ─────────────────────────────────

def t_bridge_clamp_oben():
    b, calls = _bridge_mit_abfang()
    erg = b.freigabe_ausfuehren(limit=9999, bestaetigt=True)
    assert erg.ok
    assert _limit_aus_args(calls) == 50, "9999 muss auf 50 geklemmt werden"


def t_bridge_clamp_unten():
    b, calls = _bridge_mit_abfang()
    b.freigabe_ausfuehren(limit=0, bestaetigt=True)
    assert _limit_aus_args(calls) == 1, "0 muss auf 1 geklemmt werden"


def t_bridge_gueltiger_wert_unveraendert():
    b, calls = _bridge_mit_abfang()
    b.freigabe_ausfuehren(limit=7, bestaetigt=True)
    assert _limit_aus_args(calls) == 7, "7 muss unverändert durchgehen"


def t_bridge_ohne_freigabe_kein_versand():
    """Hartes Tor bleibt: ohne bestaetigt=True wird NICHTS gesendet."""
    b, calls = _bridge_mit_abfang()
    erg = b.freigabe_ausfuehren(limit=20, bestaetigt=False)
    assert not erg.ok
    assert calls == [], "Ohne Freigabe darf kein _run (kein Versand) passieren"


# ─── Server-Clamp (/api/freigabe), Bridge gefakt — kein Versand ───────────────

def _server_freigabe(limit_body):
    """Ruft _handle_freigabe mit gegebenem Body auf; gibt das an die Bridge
    übergebene Limit zurück. Realer Versand ist durch die Fake-Bridge ausgeschlossen."""
    import json
    from product.ui import server

    erhalten = {}

    class FakeBridge:
        def freigabe_ausfuehren(self, limit, *, bestaetigt):
            erhalten["limit"] = limit
            erhalten["bestaetigt"] = bestaetigt
            return SimpleNamespace(ok=True, meldung="ok", leads_sauber=limit)

    alt = server._bridge
    server._bridge = FakeBridge()
    try:
        h = server._Handler.__new__(server._Handler)          # ohne Socket
        if limit_body is None:
            body = b""
        else:
            body = json.dumps({"limit": limit_body}).encode("utf-8")
        h.headers = {"Content-Length": str(len(body))}
        h.rfile = io.BytesIO(body)
        h._json = lambda daten: None                          # Antwort verschlucken
        h._handle_freigabe()
    finally:
        server._bridge = alt
    return erhalten["limit"]


def t_server_clamp_oben():
    assert _server_freigabe(9999) == 50


def t_server_clamp_unten():
    assert _server_freigabe(0) == 1


def t_server_default_ohne_body():
    assert _server_freigabe(None) == 20


def t_server_gueltiger_wert():
    assert _server_freigabe(10) == 10


# ─── UI: Dropdown + Clamp-Logik vorhanden ─────────────────────────────────────

def t_ui_dropdown_vorhanden():
    html = (ROOT / "product" / "ui" / "dashboard.html").read_text(encoding="utf-8")
    assert "freigabeLimitSelect" in html
    assert "onFreigabeLimitChange" in html
    for opt in ("[5, 10, 20, 50]", "5", "10", "20", "50"):
        assert opt in html
    assert "Math.min(val, _freigabeSendbar)" in html      # nie mehr als sendbar
    assert "Math.max(1, Math.min(val, 50))" in html       # UI-Clamp 1..50
    assert "zeigFreigabeModal(_freigabeLimitAktuell)" in html
    assert 'id="freigabeBtnNum"' in html                  # Button zeigt Zahl


if __name__ == "__main__":
    print("\n=== Freigabe-Limit Clamp (Mini-Patch) — kein echter Versand ===\n")

    print("── Bridge-Clamp (realer Code, _run abgefangen) ──")
    test("9999 → 50", t_bridge_clamp_oben)
    test("0 → 1", t_bridge_clamp_unten)
    test("7 → 7 (unverändert)", t_bridge_gueltiger_wert_unveraendert)
    test("ohne Freigabe → KEIN Versand", t_bridge_ohne_freigabe_kein_versand)

    print("\n── Server-Clamp /api/freigabe (Bridge gefakt) ──")
    test("9999 → 50", t_server_clamp_oben)
    test("0 → 1", t_server_clamp_unten)
    test("ohne Body → Default 20", t_server_default_ohne_body)
    test("10 → 10 (gültig)", t_server_gueltiger_wert)

    print("\n── UI-Patch (dashboard.html) ──")
    test("Dropdown 5/10/20/50 + Clamp-Logik vorhanden", t_ui_dropdown_vorhanden)

    print(f"\n{'=' * 56}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅  (keine Mail gesendet)")
