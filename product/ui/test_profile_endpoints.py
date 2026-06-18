"""HTTP-Integrationstest: Angebot-Profil-Endpoints (kein echter Versand, kein Netz).

Bootet den echten Server-Handler auf einem freien Port, authentifiziert per
Admin-Token und prüft den vollen Lebenszyklus: anlegen → aktiv setzen → PDF
hochladen → das aktive Profil landet als Env auf der echten Bridge.

Aufruf:  PYTHONUTF8=1 python -m product.ui.test_profile_endpoints
"""
from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from product.ui import server as srv
from product.profile import store as profil_store
from product.bridge.engine_bridge import EngineBridge

_TOKEN = "testtoken-profile"
_ROOT = Path(__file__).resolve().parents[2]


def _req(port: int, method: str, pfad: str, *, body=None, ctype="application/json") -> dict:
    url = f"http://127.0.0.1:{port}{pfad}"
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("X-Access-Token", _TOKEN)
    r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        # Store isolieren — echte product_profiles.json bleibt unberührt
        profil_store._PFAD = Path(d) / "profiles.json"
        profil_store._ASSET_DIR = Path(d) / "_assets"

        # Server-Globals setzen: Admin-Token + echte Bridge (für profil_setzen)
        srv._ui_token = _TOKEN
        srv._bridge = EngineBridge(_ROOT / "b2bbot")
        srv._bridge.profil_setzen({})

        httpd = HTTPServer(("127.0.0.1", 0), srv._Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            # 1) Liste: Default (ein leeres Profil)
            r = _req(port, "GET", "/api/admin/profile")
            assert r["ok"] and len(r["profile"]) == 1, r
            print("1 LIST DEFAULT OK")

            # 2) Auth: ohne Token → 403
            try:
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/admin/profile", method="GET"
                    ), timeout=10,
                )
                assert False, "ohne Token darf nicht 200 sein"
            except urllib.error.HTTPError as e:
                assert e.code in (401, 403), e.code
            print("2 AUTH-GATE OK")

            # 3) Profil anlegen (Kunde A — Termin-Akquise)
            r = _req(port, "POST", "/api/admin/profile", body={
                "id": "kunde_a", "name": "Kunde A Termine",
                "branche": "Steuerberater", "stadt": "Bonn", "lead_anzahl": 15,
                "betreff": "Termine für Ihre Kanzlei",
                "mailtext": "{anrede}\n\nich vereinbare Termine für {firma}.\n\nGruß",
            })
            assert r["ok"] and any(p["id"] == "kunde_a" for p in r["profile"]), r
            print("3 CREATE OK")

            # 4) Aktiv setzen → Env landet auf der Bridge
            r = _req(port, "POST", "/api/admin/profile/aktiv", body={"id": "kunde_a"})
            assert r["ok"] and r["aktiv"] == "kunde_a", r
            be = srv._bridge._profil_env
            assert be.get("PROFILE_FIRST_TOUCH_SUBJECT") == "Termine für Ihre Kanzlei", be
            assert "{firma}" in be.get("PROFILE_FIRST_TOUCH_BODY", ""), be
            assert "PROFILE_FIRST_TOUCH_PDF" not in be, "noch kein PDF"
            print("4 AKTIV → BRIDGE-ENV OK")

            # 5) PDF hochladen → Pfad im Profil + Env
            r = _req(port, "POST", "/api/admin/profile/pdf?id=kunde_a",
                     body=b"%PDF-1.4 fake", ctype="application/pdf")
            assert r["ok"] and r["pdf"].endswith("kunde_a.pdf"), r
            assert Path(r["pdf"]).exists()
            # erneut aktiv setzen, damit Env das PDF aufnimmt
            _req(port, "POST", "/api/admin/profile/aktiv", body={"id": "kunde_a"})
            assert srv._bridge._profil_env.get("PROFILE_FIRST_TOUCH_PDF", "").endswith("kunde_a.pdf")
            print("5 PDF-UPLOAD → ENV OK")

            # 6) Nicht-PDF wird abgelehnt
            r = _req(port, "POST", "/api/admin/profile/pdf?id=kunde_a",
                     body=b"hallo welt", ctype="application/pdf")
            assert not r["ok"], r
            print("6 NON-PDF REJECTED OK")

            # 7) Speichern ohne PDF im Body verliert den Anhang NICHT
            r = _req(port, "POST", "/api/admin/profile", body={
                "id": "kunde_a", "name": "Kunde A v2", "betreff": "Neu",
            })
            ka = next(p for p in r["profile"] if p["id"] == "kunde_a")
            assert ka["pdf"].endswith("kunde_a.pdf"), ka
            assert ka["name"] == "Kunde A v2"
            print("7 SAVE PRESERVES PDF OK")

            # 8) Löschen
            r = _req(port, "POST", "/api/admin/profile/loeschen", body={"id": "kunde_a"})
            assert r["ok"] and not any(p["id"] == "kunde_a" for p in r["profile"]), r
            print("8 DELETE OK")

            print("ALL_PROFILE_ENDPOINT_TESTS_OK")
            return 0
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    import urllib.error  # noqa: E402
    raise SystemExit(main())
