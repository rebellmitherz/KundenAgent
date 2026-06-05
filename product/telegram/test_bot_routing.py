"""Tests für das Multi-Mandanten-Routing im Live-Bot (F7a).

Läuft ohne echten Telegram-Bot, ohne Engine, ohne Netzwerk:
  - Mock-TelegramAPI (zeichnet Sends auf)
  - Mock-Runner + Mock-Dialog je Sitzung (zeichnet Aufrufe auf)
  - echte Router-Logik + echtes _verarbeite_update aus bot.py

Belegt:
  1. Leeres Register → Single-Tenant-Verhalten UNVERÄNDERT (Owner-Lock,
     Owner-Registrierung, Befehle auf der einen Laufzeit).
  2. Zwei Mandanten → Nachricht von Chat A trifft NUR Runner A (kein Querverkehr).
  3. Fremde Chat-ID → wird NICHT bedient (höfliche Ablehnung).
  4. Betreiber-Chat → /plattform liefert die Gesamtsicht; sonst Betreiber-Hinweis.

Aufruf: PYTHONUTF8=1 python product/telegram/test_bot_routing.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.platform.mandant import Mandant
from product.telegram.routing import (
    IN_EINRICHTUNG_TEXT,
    NICHT_FREIGESCHALTET_TEXT,
    PRIVAT_TEXT,
    Router,
    Sitzung,
)
import product.telegram.bot as bot


# ─── Mocks ────────────────────────────────────────────────────────────────────

class FakeTG:
    """Minimal-TelegramAPI: zeichnet alle Sends auf."""
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def try_send(self, chat_id, text: str) -> bool:
        self.sent.append((str(chat_id), text))
        return True

    @property
    def letzter(self) -> str:
        return self.sent[-1][1] if self.sent else ""


class FakeRunner:
    """Agent-Runner-Mock: zeichnet auf, welche Methoden aufgerufen wurden, und
    liefert namensmarkierte Rückgaben, damit Routing belegbar ist."""
    def __init__(self, name: str):
        self.name = name
        self.calls: list[str] = []

    def _rec(self, m: str) -> None:
        self.calls.append(m)

    # vom Dispatch genutzt
    def funnel_bericht(self, campaign=None): self._rec("funnel_bericht"); return f"[funnel:{self.name}]"
    def laeufe(self): self._rec("laeufe"); return []
    def termin_signale(self, limit=30): self._rec("termin_signale"); return []
    def pruef_termine(self, limit=30): self._rec("pruef_termine"); return []
    def termin_abschliessen(self, x): self._rec("termin_abschliessen"); return {"ok": True, "meldung": f"[abschluss:{self.name}]"}
    def antworten_abrufen(self): self._rec("antworten_abrufen"); return {"ok": True, "meldung": "ok"}
    def antworten_bericht(self, limit=30): self._rec("antworten_bericht"); return f"[antworten:{self.name}]"
    def antworten(self, limit=30): self._rec("antworten"); return []
    def nachfass_faellig(self, limit=50): self._rec("nachfass_faellig"); return []
    # von reporting.mandant_report genutzt
    def funnel(self, campaign=None): self._rec("funnel"); return {}


class FakeMgr:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[tuple] = []

    def verarbeite(self, chat_id, text): self.calls.append(("verarbeite", str(chat_id), text))
    def status_text(self, chat_id): return f"[status:{self.name}]"


class FakeCloser:
    def starten(self): return {"ok": True, "meldung": "ok"}
    def stoppen(self): return {"ok": True, "meldung": "ok"}
    def status(self): return {"laeuft": False, "closer_verfuegbar": True}


# --- Multi-Tenant-Plattform-Mock (nur was Router/Reporting wirklich nutzen) ---

class FakeRegister:
    def __init__(self, mandanten): self._m = list(mandanten)
    def alle(self, nur_aktive=False): return list(self._m)


class FakePlattform:
    def __init__(self, mandanten, runners: dict):
        self._owner = {m.owner_chat_id: m for m in mandanten if m.owner_chat_id}
        self._runners = runners            # mandant_id -> FakeRunner
        self.register = FakeRegister(mandanten)

    def mandant_fuer_chat(self, chat_id):
        return self._owner.get(str(chat_id))

    def runner_oder_none(self, mandant_id):
        return self._runners.get(mandant_id)


def _upd(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def _dispatch(tg, router, upd, plattform=None, closer=None):
    bot._verarbeite_update(upd, tg, None, router, closer or FakeCloser(), plattform)


# ─── Test-Runner ──────────────────────────────────────────────────────────────

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


# ─── 1. Single-Tenant (leeres Register) — unverändert ─────────────────────────

def _single_router(operator="100", reg_cb=None):
    runner = FakeRunner("single")
    mgr = FakeMgr("single")
    sitzung = Sitzung(runner=runner, mgr=mgr, name="single")
    router = Router(single_sitzung=sitzung, operator_chat_id=operator,
                    owner_registrieren=reg_cb)
    return router, runner, mgr


def t_single_befehl_auf_einziger_laufzeit():
    tg = FakeTG()
    router, runner, mgr = _single_router(operator="100")
    _dispatch(tg, router, _upd("100", "Antworten zeigen"))
    assert "antworten_bericht" in runner.calls
    assert tg.letzter == "[antworten:single]"


def t_single_status_unveraendert():
    tg = FakeTG()
    router, runner, mgr = _single_router(operator="100")
    _dispatch(tg, router, _upd("100", "/status"))
    # Dialog-Status + Agent-Überblick zusammengesetzt
    assert "[status:single]" in tg.letzter
    assert "[funnel:single]" in tg.letzter


def t_single_owner_lock_fremder_chat():
    tg = FakeTG()
    router, runner, mgr = _single_router(operator="100")
    _dispatch(tg, router, _upd("999", "Antworten zeigen"))
    assert tg.letzter == PRIVAT_TEXT
    assert runner.calls == []           # fremder Chat erreicht den Runner NIE


def t_single_owner_registrierung_beim_ersten_chat():
    """Kein Owner gesetzt → erster Chat wird registriert UND bedient; danach
    ist der Bot für andere privat (Verhalten wie vor F7)."""
    tg = FakeTG()
    registriert: list[str] = []
    router, runner, mgr = _single_router(operator="", reg_cb=registriert.append)

    _dispatch(tg, router, _upd("555", "Antworten zeigen"))
    assert registriert == ["555"]
    assert tg.letzter == "[antworten:single]"

    # Jetzt ist 555 Owner → 777 wird abgelehnt
    _dispatch(tg, router, _upd("777", "Antworten zeigen"))
    assert tg.letzter == PRIVAT_TEXT


def t_single_dialog_fallback():
    """Normaler Text ohne Befehl → Dialog-Manager der einen Laufzeit."""
    tg = FakeTG()
    router, runner, mgr = _single_router(operator="100")
    _dispatch(tg, router, _upd("100", "Such 100 Handwerker in NRW"))
    assert ("verarbeite", "100", "Such 100 Handwerker in NRW") in mgr.calls


# ─── 2. Multi-Tenant — Isolation ──────────────────────────────────────────────

def _multi_fixture(operator="OP"):
    mA = Mandant(mandant_id="a", name="Kunde A", owner_chat_id="A", engine_dir="x")
    mB = Mandant(mandant_id="b", name="Kunde B", owner_chat_id="B", engine_dir="y")
    rA, rB = FakeRunner("a"), FakeRunner("b")
    mgrA, mgrB = FakeMgr("a"), FakeMgr("b")
    plattform = FakePlattform([mA, mB], {"a": rA, "b": rB})

    sitz = {
        "a": Sitzung(runner=rA, mgr=mgrA, name="Kunde A"),
        "b": Sitzung(runner=rB, mgr=mgrB, name="Kunde B"),
    }
    router = Router(plattform=plattform, operator_chat_id=operator,
                    sitzung_factory=lambda m: sitz[m.mandant_id])
    return router, plattform, rA, rB, mgrA, mgrB


def t_multi_chat_a_trifft_nur_runner_a():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture()
    _dispatch(tg, router, _upd("A", "Antworten zeigen"), plattform=plattform)
    assert "antworten_bericht" in rA.calls
    assert rB.calls == []                       # KEIN Querverkehr
    assert tg.letzter == "[antworten:a]"


def t_multi_chat_b_trifft_nur_runner_b():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture()
    _dispatch(tg, router, _upd("B", "Antworten zeigen"), plattform=plattform)
    assert "antworten_bericht" in rB.calls
    assert rA.calls == []
    assert tg.letzter == "[antworten:b]"


def t_multi_dialog_routet_zum_richtigen_mgr():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture()
    _dispatch(tg, router, _upd("A", "Such mir 50 Kanzleien"), plattform=plattform)
    assert ("verarbeite", "A", "Such mir 50 Kanzleien") in mgrA.calls
    assert mgrB.calls == []


def t_multi_fremde_chat_id_wird_nicht_bedient():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture()
    _dispatch(tg, router, _upd("FREMD", "Antworten zeigen"), plattform=plattform)
    assert tg.letzter == NICHT_FREIGESCHALTET_TEXT
    assert rA.calls == [] and rB.calls == []
    assert mgrA.calls == [] and mgrB.calls == []


def t_multi_nicht_eingerichteter_mandant():
    """Mandant existiert, aber Laufzeit nicht baubar → höflicher Einricht-Hinweis,
    kein Runner-Zugriff."""
    tg = FakeTG()
    mA = Mandant(mandant_id="a", name="Kunde A", owner_chat_id="A")  # ohne engine_dir
    plattform = FakePlattform([mA], {})
    router = Router(
        plattform=plattform, operator_chat_id="OP",
        sitzung_factory=lambda m: Sitzung(name=m.name, betriebsbereit=False),
    )
    _dispatch(tg, router, _upd("A", "Antworten zeigen"), plattform=plattform)
    assert tg.letzter == IN_EINRICHTUNG_TEXT


# ─── 3. Betreiber-Sicht ───────────────────────────────────────────────────────

def t_operator_plattform_gesamtsicht():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture(operator="OP")
    _dispatch(tg, router, _upd("OP", "/plattform"), plattform=plattform)
    txt = tg.letzter
    assert "Plattform-Übersicht" in txt
    assert "Kunde A" in txt and "Kunde B" in txt


def t_operator_ohne_befehl_bekommt_hinweis():
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture(operator="OP")
    _dispatch(tg, router, _upd("OP", "hallo"), plattform=plattform)
    assert "Betreiber-Modus" in tg.letzter
    assert rA.calls == [] and rB.calls == []


def t_operator_der_auch_mandant_ist_wird_bedient():
    """Ist der Betreiber-Chat zugleich Mandant, läuft normale Bedienung; /plattform
    bleibt zusätzlich verfügbar."""
    tg = FakeTG()
    # Operator == owner_chat_id von Kunde A
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture(operator="A")
    _dispatch(tg, router, _upd("A", "Antworten zeigen"), plattform=plattform)
    assert tg.letzter == "[antworten:a]"
    _dispatch(tg, router, _upd("A", "/plattform"), plattform=plattform)
    assert "Plattform-Übersicht" in tg.letzter


def t_nicht_operator_kein_plattform_zugriff():
    """Ein Mandant (nicht Betreiber) bekommt mit /plattform KEINE Gesamtsicht."""
    tg = FakeTG()
    router, plattform, rA, rB, mgrA, mgrB = _multi_fixture(operator="OP")
    _dispatch(tg, router, _upd("A", "/plattform"), plattform=plattform)
    # /plattform ist für A kein Operator-Befehl → fällt in den Dialog der Sitzung A
    assert "Plattform-Übersicht" not in tg.letzter


# ─── 4. Router-Einheit (Grenzfälle) ───────────────────────────────────────────

def t_router_braucht_modus():
    fehler = False
    try:
        Router()
    except ValueError:
        fehler = True
    assert fehler


if __name__ == "__main__":
    print("\n=== F7a — Multi-Mandanten-Routing (bot.py) ===\n")

    print("── Single-Tenant (leeres Register, unverändert) ──")
    test("Befehl läuft auf der einzigen Laufzeit", t_single_befehl_auf_einziger_laufzeit)
    test("/status unverändert (Dialog + Agent-Überblick)", t_single_status_unveraendert)
    test("Owner-Lock: fremder Chat → privat", t_single_owner_lock_fremder_chat)
    test("Owner-Registrierung beim ersten Chat", t_single_owner_registrierung_beim_ersten_chat)
    test("Normaler Text → Dialog-Manager", t_single_dialog_fallback)

    print("\n── Multi-Tenant (Isolation) ──")
    test("Chat A trifft NUR Runner A", t_multi_chat_a_trifft_nur_runner_a)
    test("Chat B trifft NUR Runner B", t_multi_chat_b_trifft_nur_runner_b)
    test("Dialog routet zum richtigen Manager", t_multi_dialog_routet_zum_richtigen_mgr)
    test("Fremde Chat-ID wird nicht bedient", t_multi_fremde_chat_id_wird_nicht_bedient)
    test("Nicht eingerichteter Mandant → Hinweis", t_multi_nicht_eingerichteter_mandant)

    print("\n── Betreiber-Sicht ──")
    test("/plattform → Gesamtsicht (Operator)", t_operator_plattform_gesamtsicht)
    test("Operator ohne Befehl → Hinweis", t_operator_ohne_befehl_bekommt_hinweis)
    test("Operator der auch Mandant ist → bedient + /plattform", t_operator_der_auch_mandant_ist_wird_bedient)
    test("Nicht-Operator: kein /plattform-Zugriff", t_nicht_operator_kein_plattform_zugriff)

    print("\n── Router-Einheit ──")
    test("Router ohne Modus → ValueError", t_router_braucht_modus)

    print(f"\n{'=' * 44}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
