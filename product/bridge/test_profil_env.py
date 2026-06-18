"""Test: Profil-Env-Injektion in der Bridge (kein mine.py-Start, kein Netz).

Verifiziert, dass engine_bridge.profil_setzen() die PROFILE_FIRST_TOUCH_*-Env in
JEDEN Subprozess einspeist UND dass call-spezifische extra_env (Safety-Flags)
bei Schlüssel-Kollision GEWINNT.

Aufruf:  PYTHONUTF8=1 python -m product.bridge.test_profil_env
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from product.bridge import engine_bridge as eb

_ENGINE_DIR = Path(__file__).resolve().parents[2] / "b2bbot"


class _FakeProc:
    returncode = 0
    stdout = "ok"
    stderr = ""


def _bridge_mit_capture(captured: dict):
    bridge = eb.EngineBridge(_ENGINE_DIR)

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeProc()

    eb.subprocess.run = fake_run  # type: ignore[assignment]
    return bridge


def main() -> int:
    orig = subprocess.run
    captured: dict = {}
    try:
        bridge = _bridge_mit_capture(captured)

        # 1) Ohne Profil + ohne extra_env → env bleibt None (unverändert)
        bridge.profil_setzen(None)
        bridge._run(["--version"])
        assert captured["env"] is None, "ohne alles darf env None bleiben"
        print("1 NO-ENV OK")

        # 2) Profil-Env wird eingespeist
        bridge.profil_setzen({"PROFILE_FIRST_TOUCH_SUBJECT": "Termine A"})
        bridge._run(["--version"])
        env = captured["env"]
        assert env is not None and env["PROFILE_FIRST_TOUCH_SUBJECT"] == "Termine A"
        print("2 PROFILE-INJECT OK")

        # 3) Profil + call-spezifische extra_env koexistieren
        bridge.profil_setzen({"PROFILE_FIRST_TOUCH_BODY": "txt"})
        bridge._run(["--outreach", "send"], extra_env={"OUTREACH_SEND_CONFIRMED": "true"})
        env = captured["env"]
        assert env["PROFILE_FIRST_TOUCH_BODY"] == "txt"
        assert env["OUTREACH_SEND_CONFIRMED"] == "true"
        print("3 COEXIST OK")

        # 4) Kollision: extra_env GEWINNT (Safety-Flag darf nie vom Profil fallen)
        bridge.profil_setzen({"OUTREACH_SEND_CONFIRMED": "false"})
        bridge._run(["x"], extra_env={"OUTREACH_SEND_CONFIRMED": "true"})
        assert captured["env"]["OUTREACH_SEND_CONFIRMED"] == "true", "extra_env muss gewinnen"
        print("4 EXTRA-ENV-WINS OK")

        # 5) Profil-Reset entfernt den Override wieder
        bridge.profil_setzen({})
        bridge._run(["--version"])
        assert captured["env"] is None
        print("5 RESET OK")

        print("ALL_PROFIL_ENV_TESTS_OK")
        return 0
    finally:
        eb.subprocess.run = orig  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
