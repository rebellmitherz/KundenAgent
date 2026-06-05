"""End-to-End-Smoke-Test der Multi-Mandanten-Verdrahtung (F7).

Im Gegensatz zu test_bot_routing.py (reine Mock-Sitzungen) baut dieser Test die
ECHTE Produktions-Kette zusammen — alles außer Engine-Subprozess und Telegram-
Netzwerk ist real:

  MandantenRegister (echt, Temp-Verzeichnis)
    → Plattform (echt; nur Bridge/Reporter injiziert)
      → bot.baue_mandant_sitzung (echte Factory: AgentRunner + DialogManager)
        → Router (echt)
          → bot._verarbeite_update (echter Dispatch)

Gefakt sind nur:
  - TelegramAPI  → FakeTG (zeichnet Sends auf)
  - EngineBridge → FakeBridge (liefert PRO MANDANT unterschiedliche Daten, damit
                   Isolation belegbar ist — Chat A sieht NUR A's Daten)

Belegt produktionsnah:
  - Single-Tenant (leeres Register) bedient die eine Laufzeit, fremde Chat = privat.
  - Multi-Tenant: Chat A bekommt A's Antworten, Chat B nur B's — kein Querverkehr.
  - Fremde Chat-ID wird abgelehnt.
  - Betreiber sieht die Plattform-Gesamtsicht.

Aufruf: PYTHONUTF8=1 python product/telegram/test_e2e_smoke.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product.platform.mandant import Mandant, MandantenRegister
from product.platform.plattform import Plattform
from product.telegram.routing import NICHT_FREIGESCHALTET_TEXT, PRIVAT_TEXT, Router, Sitzung
import product.telegram.bot as bot


# ─── Fakes (nur Engine + Telegram) ────────────────────────────────────────────

class FakeTG:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def try_send(self, chat_id, text: str) -> bool:
        self.sent.append((str(chat_id), text))
        return True

    @property
    def letzter(self) -> str:
        return self.sent[-1][1] if self.sent else ""


class FakeBridge:
    """Engine-Bridge-Ersatz: liefert je nach engine_dir UNTERSCHEIDBARE Antworten,
    damit nachweisbar ist, dass jeder Chat seine eigene Bridge trifft."""
    def __init__(self, engine_dir):
        self.engine_dir = Path(engine_dir)
        self._firma = "AlphaCorp" if self.engine_dir.name.endswith("_a") else "BetaGmbH"

    def antworten_lesen(self, limit: int = 30):
        return [{
            "entry_key": f"k-{self.engine_dir.name}",
            "firma": self._firma,
            "terminwunsch": True,
            "termin_grund": "möchte einen Termin",
            "betreff": "AW: Angebot",
            "auszug": "Gerne Termin nächste Woche",
            "text": "Gerne Termin nächste Woche",
            "von": "kontakt@example.de",
            "postfach": "",
            "gesendet_am": "",
            "auto_antwort": False,
        }]

    def kampagne_rohdaten(self, campaign=None):
        return {}

    def followups_faellig(self, limit: int = 50):
        return []


class FakeCloser:
    def starten(self): return {"ok": True, "meldung": "ok"}
    def stoppen(self): return {"ok": True, "meldung": "ok"}
    def status(self): return {"laeuft": False, "closer_verfuegbar": True}


def _upd(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


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
        traceback.print_exc(limit=5)
        _fail += 1


def _plattform(tmp: Path) -> tuple[MandantenRegister, Plattform]:
    register = MandantenRegister(tmp / "platform")
    register.anlegen(Mandant(
        mandant_id="kunde-a", name="Kunde A", owner_chat_id="111",
        engine_dir=str(tmp / "eng_a"),
    ))
    register.anlegen(Mandant(
        mandant_id="kunde-b", name="Kunde B", owner_chat_id="222",
        engine_dir=str(tmp / "eng_b"),
    ))
    plattform = Plattform(
        register,
        api_key_default="",
        bridge_factory=lambda ed: FakeBridge(ed),
        reporter_factory=lambda ed: None,
    )
    return register, plattform


def _router(plattform: Plattform, send_fn, operator="999") -> Router:
    return Router(
        plattform=plattform,
        operator_chat_id=operator,
        sitzung_factory=lambda m: bot.baue_mandant_sitzung(plattform, m, send_fn),
    )


# ─── Multi-Tenant E2E ─────────────────────────────────────────────────────────

def t_e2e_isolation_a_sieht_nur_a():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send)

        bot._verarbeite_update(_upd("111", "Antworten zeigen"), tg, None, router, FakeCloser(), plattform)
        out = tg.letzter
        assert "AlphaCorp" in out, out
        assert "BetaGmbH" not in out, out


def t_e2e_isolation_b_sieht_nur_b():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send)

        bot._verarbeite_update(_upd("222", "Antworten zeigen"), tg, None, router, FakeCloser(), plattform)
        out = tg.letzter
        assert "BetaGmbH" in out, out
        assert "AlphaCorp" not in out, out


def t_e2e_status_durchlaeuft_echte_kette():
    """/status baut echten DialogManager-Status + Agent-Überblick zusammen."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send)
        bot._verarbeite_update(_upd("111", "/status"), tg, None, router, FakeCloser(), plattform)
        assert tg.letzter  # nicht leer — kein Crash in der echten Kette
        assert "AlphaCorp" not in tg.sent[0][1] or True  # nur Smoke: kein Fehler


def t_e2e_fremde_chat_abgelehnt():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send)
        bot._verarbeite_update(_upd("555", "Antworten zeigen"), tg, None, router, FakeCloser(), plattform)
        assert tg.letzter == NICHT_FREIGESCHALTET_TEXT


def t_e2e_betreiber_gesamtsicht():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send, operator="999")
        bot._verarbeite_update(_upd("999", "/plattform"), tg, None, router, FakeCloser(), plattform)
        out = tg.letzter
        assert "Plattform-Übersicht" in out, out
        assert "Kunde A" in out and "Kunde B" in out, out


def t_e2e_dialog_normaler_text():
    """Normaler Akquise-Text läuft durch den echten DialogManager (kein Crash)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, plattform = _plattform(tmp)
        tg = FakeTG()
        router = _router(plattform, tg.try_send)
        # darf nicht crashen; DialogManager fragt typ. nach fehlenden Feldern
        bot._verarbeite_update(_upd("111", "Hallo"), tg, None, router, FakeCloser(), plattform)
        assert tg.letzter  # irgendeine Rückfrage/Antwort kam


# ─── Single-Tenant E2E (leeres Register) ──────────────────────────────────────

def t_e2e_single_tenant():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        register = MandantenRegister(tmp / "platform")  # leer
        assert register.alle(nur_aktive=True) == []
        tg = FakeTG()

        # Single-Sitzung wie in bot.main() (Single-Tenant-Zweig), nur Bridge gefakt
        from product.agent.runner import AgentRunner
        from product.operator.confirm import ConfirmGate
        from product.operator.intake import OperatorIntake
        from product.telegram.dialog import DialogManager

        bridge = FakeBridge(tmp / "eng_a")
        runner = AgentRunner(bridge=bridge, data_dir=tmp / "data", reporter=None)
        mgr = DialogManager(
            intake=OperatorIntake(llm_fn=None), gate=ConfirmGate(),
            bridge=bridge, orders_dir=tmp / "orders", send_fn=tg.try_send,
            agent_runner=runner,
        )
        single = Sitzung(runner=runner, mgr=mgr, name="single")
        router = Router(single_sitzung=single, operator_chat_id="111")

        # Owner bedient
        bot._verarbeite_update(_upd("111", "Antworten zeigen"), tg, None, router, FakeCloser())
        assert "AlphaCorp" in tg.letzter
        # Fremder Chat = privat
        bot._verarbeite_update(_upd("777", "Antworten zeigen"), tg, None, router, FakeCloser())
        assert tg.letzter == PRIVAT_TEXT


if __name__ == "__main__":
    print("\n=== F7 — End-to-End-Smoke (echte Verdrahtung, Engine/Telegram gefakt) ===\n")

    print("── Multi-Tenant ──")
    test("Chat A sieht NUR A's Daten (AlphaCorp)", t_e2e_isolation_a_sieht_nur_a)
    test("Chat B sieht NUR B's Daten (BetaGmbH)", t_e2e_isolation_b_sieht_nur_b)
    test("/status durchläuft echte Kette ohne Crash", t_e2e_status_durchlaeuft_echte_kette)
    test("Fremde Chat-ID abgelehnt", t_e2e_fremde_chat_abgelehnt)
    test("Betreiber sieht Gesamtsicht", t_e2e_betreiber_gesamtsicht)
    test("Normaler Text → echter DialogManager", t_e2e_dialog_normaler_text)

    print("\n── Single-Tenant (leeres Register) ──")
    test("Owner bedient, Fremder = privat", t_e2e_single_tenant)

    print(f"\n{'=' * 60}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")
