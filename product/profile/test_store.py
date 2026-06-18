"""Unit-Test für den Angebot-Profil-Store (kein Netz, kein I/O ans echte File).

Aufruf:  PYTHONUTF8=1 python -m product.profile.test_store
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from product.profile import store


def _isoliere(tmp: Path) -> None:
    """Store auf ein Wegwerf-Verzeichnis umbiegen (kein Eingriff in echte Daten)."""
    store._PFAD = tmp / "product_profiles.json"
    store._ASSET_DIR = tmp / "_assets"


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        _isoliere(Path(d))

        # 1) Erststart: Default-Struktur, ein leeres Profil → Engine-Default
        data = store.laden()
        assert len(data["profile"]) == 1, data
        assert data["aktiv"] == data["profile"][0]["id"]
        assert store.aktives_profil_env() == {}, "leeres Profil darf keine Env setzen"
        print("1 DEFAULT OK")

        # 2) Profil mit Override speichern + aktiv setzen → Env korrekt
        store.profil_speichern({
            "id": "kunde_a", "name": "Kunde A Termine",
            "branche": "Steuerberater", "stadt": "Bonn", "lead_anzahl": 15,
            "betreff": "Termine für Ihre Kanzlei",
            "mailtext": "{anrede}\n\nich vereinbare Termine für {firma}.\n\nGruß",
            "pdf": "",
        })
        store.aktiv_setzen("kunde_a")
        env = store.aktives_profil_env()
        assert env["PROFILE_FIRST_TOUCH_SUBJECT"] == "Termine für Ihre Kanzlei", env
        assert "{firma}" in env["PROFILE_FIRST_TOUCH_BODY"], env
        assert "PROFILE_FIRST_TOUCH_PDF" not in env, "leeres PDF darf nicht gesetzt sein"
        assert store.aktives_profil()["lead_anzahl"] == 15
        print("2 OVERRIDE + AKTIV OK")

        # 3) Upsert: gleiche ID ersetzt, keine Dublette
        store.profil_speichern({"id": "kunde_a", "name": "Kunde A v2", "betreff": "Neu"})
        data = store.laden()
        ka = [p for p in data["profile"] if p["id"] == "kunde_a"]
        assert len(ka) == 1 and ka[0]["name"] == "Kunde A v2", data
        print("3 UPSERT OK")

        # 4) Slug: krummer Name → sichere ID
        store.profil_speichern({"name": "Kunde B – Ärzte & Co!"})
        ids = {p["id"] for p in store.laden()["profile"]}
        assert any(re_ok(i) for i in ids), ids
        print("4 SLUG OK:", ids)

        # 5) Löschen: aktives Profil löschen → aktiv wandert mit; letztes bleibt
        store.aktiv_setzen("kunde_a")
        store.profil_loeschen("kunde_a")
        data = store.laden()
        assert "kunde_a" not in {p["id"] for p in data["profile"]}
        assert data["aktiv"] in {p["id"] for p in data["profile"]}
        print("5 DELETE OK")

        # letztes Profil kann nicht gelöscht werden
        while len(store.laden()["profile"]) > 1:
            store.profil_loeschen(store.laden()["profile"][0]["id"])
        rest_id = store.laden()["profile"][0]["id"]
        store.profil_loeschen(rest_id)
        assert len(store.laden()["profile"]) == 1, "letztes Profil darf nicht weg"
        print("6 LAST-PROFILE-GUARD OK")

        # 7) PDF speichern → absoluter Pfad
        pfad = store.pdf_speichern("kunde_x", b"%PDF-1.4 x")
        assert Path(pfad).exists() and Path(pfad).is_absolute()
        print("7 PDF-ASSET OK")

    print("ALL_STORE_TESTS_OK")
    return 0


def re_ok(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[a-z0-9_]+", s))


if __name__ == "__main__":
    raise SystemExit(main())
