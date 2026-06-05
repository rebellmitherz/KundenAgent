"""Tests für product/packaging/ (Schritt 13).

Ausführen:
    PYTHONUTF8=1 python product/packaging/test_packaging.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from product.version import VERSION, MANIFEST, version_string, MIN_PYTHON
from product.packaging.check_install import (
    check_python, check_version, check_pflicht_dateien,
    check_engine, check_schreibrechte, installation_pruefen,
)
from product.packaging.package import (
    _ausgeschlossen, _erstelle_setup_md, _erstelle_requirements_txt,
    _erstelle_manifest, _erstelle_start_ui_bat,
)


# ── 1. Version ───────────────────────────────────────────────────────────────

class TestVersion(unittest.TestCase):

    def test_version_format(self):
        teile = VERSION.split(".")
        assert len(teile) == 3
        for t in teile:
            assert t.isdigit(), f"Kein Integer: {t}"

    def test_manifest_vollstaendig(self):
        assert "product" in MANIFEST
        assert "version" in MANIFEST
        assert "components" in MANIFEST
        assert MANIFEST["version"] == VERSION

    def test_version_string(self):
        s = version_string()
        assert VERSION in s
        assert "Rebellsystem" in s

    def test_min_python(self):
        assert len(MIN_PYTHON) == 2
        assert MIN_PYTHON[0] >= 3
        assert MIN_PYTHON[1] >= 10


# ── 2. check_install: einzelne Checks ────────────────────────────────────────

class TestCheckInstall(unittest.TestCase):

    def test_python_check_format(self):
        r = check_python()
        assert "ok" in r
        assert "detail" in r
        assert "hinweis" in r
        assert r["ok"] is True   # wir laufen auf 3.10+

    def test_version_check_ok(self):
        r = check_version()
        assert r["ok"] is True
        assert VERSION in r["detail"]

    def test_pflicht_dateien_check(self):
        r = check_pflicht_dateien()
        assert "ok" in r
        assert "/" in r["detail"]   # "X/Y vorhanden"

    def test_engine_check_format(self):
        r = check_engine()
        assert "ok" in r
        assert "b2bbot" in r["detail"].lower()

    def test_schreibrechte_check(self):
        r = check_schreibrechte()
        assert "ok" in r
        # Auf Entwicklerrechner sollte es klappen
        assert r["ok"] is True

    def test_installation_pruefen_struktur(self):
        bericht = installation_pruefen()
        assert "gesamt_ok" in bericht
        assert "startbereit" in bericht
        assert "checks" in bericht
        assert len(bericht["checks"]) >= 5

    def test_startbereit_ohne_config(self):
        """Ohne product_config.json sollte startbereit trotzdem True sein."""
        bericht = installation_pruefen()
        # startbereit = alle kritischen Checks OK (Config ist nicht kritisch)
        assert bericht["startbereit"] is True


# ── 3. Ausschluss-Logik ───────────────────────────────────────────────────────

class TestAusschlusssLogik(unittest.TestCase):

    def _pfad(self, name: str, ist_datei: bool = True) -> Path:
        """Erstellt einen temporären Pfad für Tests."""
        import tempfile, os
        tmp = Path(tempfile.mkdtemp())
        p = tmp / name
        if ist_datei:
            p.write_text("test")
        else:
            p.mkdir()
        return p, tmp

    def test_secret_ausgeschlossen(self):
        p, root = self._pfad("product_config.json")
        assert _ausgeschlossen(p, root) is True

    def test_smtp_secret_ausgeschlossen(self):
        p, root = self._pfad("product_smtp.json")
        assert _ausgeschlossen(p, root) is True

    def test_keygen_ausgeschlossen(self):
        p, root = self._pfad("keygen.py")
        assert _ausgeschlossen(p, root) is True

    def test_pyc_ausgeschlossen(self):
        p, root = self._pfad("module.pyc")
        assert _ausgeschlossen(p, root) is True

    def test_pycache_dir_ausgeschlossen(self):
        p, root = self._pfad("__pycache__", ist_datei=False)
        assert _ausgeschlossen(p, root) is True

    def test_git_dir_ausgeschlossen(self):
        p, root = self._pfad(".git", ist_datei=False)
        assert _ausgeschlossen(p, root) is True

    def test_normale_py_erlaubt(self):
        p, root = self._pfad("engine_bridge.py")
        assert _ausgeschlossen(p, root) is False

    def test_env_ausgeschlossen(self):
        p, root = self._pfad(".env")
        assert _ausgeschlossen(p, root) is True   # .env ist in _AUSSCHLUSS_NAMEN

    def test_test_dateien_in_product_ausgeschlossen(self):
        """test_*.py in product/ soll ausgeschlossen werden."""
        import tempfile
        root = Path(tempfile.mkdtemp())
        prod_dir = root / "product" / "setup"
        prod_dir.mkdir(parents=True)
        test_datei = prod_dir / "test_onboarding.py"
        test_datei.write_text("# test")
        assert _ausgeschlossen(test_datei, root) is True

    def test_setup_py_nicht_ausgeschlossen(self):
        """Normale .py in product/ (nicht test_*) bleibt drin."""
        import tempfile
        root = Path(tempfile.mkdtemp())
        prod_dir = root / "product" / "setup"
        prod_dir.mkdir(parents=True)
        datei = prod_dir / "onboarding.py"
        datei.write_text("# ok")
        assert _ausgeschlossen(datei, root) is False


# ── 4. Generierte Texte ───────────────────────────────────────────────────────

class TestGenerierteTexte(unittest.TestCase):

    def test_setup_md_enthaelt_version(self):
        md = _erstelle_setup_md("1.0.0")
        assert "1.0.0" in md
        assert "start_operator.bat" in md
        assert "Python" in md

    def test_setup_md_keine_secrets(self):
        md = _erstelle_setup_md("1.0.0")
        assert "password" not in md.lower()
        assert "api_key" not in md.lower()
        assert "token" not in md.lower() or "bot-token" in md.lower()

    def test_requirements_txt_format(self):
        req = _erstelle_requirements_txt()
        assert "requests" in req
        assert "python-dotenv" in req
        assert "anthropic" in req   # als Kommentar

    def test_start_ui_bat(self):
        bat = _erstelle_start_ui_bat()
        assert "8767" in bat
        assert "python" in bat.lower()
        assert "server.py" in bat

    def test_manifest_struktur(self):
        m = _erstelle_manifest("1.0.0", "hermes-v1", {"gesamt": 100, "uebersprungen": 10})
        assert m["version"] == "1.0.0"
        assert m["dateien_gesamt"] == 100
        assert "keygen.py" in str(m.get("nicht_enthalten", ""))


# ── 5. ZIP-Erstellung (Smoke-Test mit Temp-Verzeichnis) ──────────────────────

class TestZipErstellung(unittest.TestCase):

    def test_paket_erstellen_laeuft_durch(self):
        """Erstellt ein echtes ZIP in ein temporäres Verzeichnis."""
        with tempfile.TemporaryDirectory() as tmp:
            from product.packaging.package import paket_erstellen
            zip_pfad = paket_erstellen(Path(tmp))
            assert zip_pfad.exists()
            assert zip_pfad.suffix == ".zip"
            assert zip_pfad.stat().st_size > 0

    def test_zip_enthaelt_pflicht_dateien(self):
        """Prüft dass Schlüssel-Dateien im ZIP vorhanden sind."""
        with tempfile.TemporaryDirectory() as tmp:
            from product.packaging.package import paket_erstellen
            zip_pfad = paket_erstellen(Path(tmp))
            with zipfile.ZipFile(zip_pfad) as zf:
                namen = set(zf.namelist())
            # SETUP.md und requirements.txt müssen rein
            assert any("SETUP.md" in n for n in namen)
            assert any("requirements.txt" in n for n in namen)
            assert any("MANIFEST.json" in n for n in namen)
            assert any("start_ui.bat" in n for n in namen)

    def test_zip_enthaelt_keine_secrets(self):
        """product_config.json und keygen.py dürfen NICHT im ZIP sein."""
        with tempfile.TemporaryDirectory() as tmp:
            from product.packaging.package import paket_erstellen
            zip_pfad = paket_erstellen(Path(tmp))
            with zipfile.ZipFile(zip_pfad) as zf:
                namen = set(zf.namelist())
            assert not any("product_config.json" in n for n in namen)
            assert not any("product_smtp.json" in n for n in namen)
            assert not any("keygen.py" in n for n in namen)

    def test_zip_enthaelt_keine_pyc(self):
        """Keine .pyc-Dateien im ZIP."""
        with tempfile.TemporaryDirectory() as tmp:
            from product.packaging.package import paket_erstellen
            zip_pfad = paket_erstellen(Path(tmp))
            with zipfile.ZipFile(zip_pfad) as zf:
                namen = set(zf.namelist())
            assert not any(n.endswith(".pyc") for n in namen)
            assert not any("__pycache__" in n for n in namen)

    def test_manifest_im_zip_lesbar(self):
        """MANIFEST.json im ZIP muss valides JSON sein."""
        with tempfile.TemporaryDirectory() as tmp:
            from product.packaging.package import paket_erstellen
            zip_pfad = paket_erstellen(Path(tmp))
            with zipfile.ZipFile(zip_pfad) as zf:
                manifest_name = next(n for n in zf.namelist() if n.endswith("MANIFEST.json"))
                manifest = json.loads(zf.read(manifest_name))
            assert manifest["version"] == VERSION
            assert manifest["dateien_gesamt"] > 0


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 58)
    print("  Schritt 13 — Customer Package Tests")
    print("=" * 58)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestVersion, TestCheckInstall, TestAusschlusssLogik,
                TestGenerierteTexte, TestZipErstellung]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"  ALLE {result.testsRun} Tests GRUEN")
    else:
        print(f"  {len(result.failures)} Fehler, {len(result.errors)} Errors")
    sys.exit(0 if result.wasSuccessful() else 1)
