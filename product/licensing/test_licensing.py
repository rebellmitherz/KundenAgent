"""Tests für product/licensing/ (Schritt 12).

Ausführen:
    PYTHONUTF8=1 python product/licensing/test_licensing.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from product.licensing.features import Feature, PAKETE, features_fuer_plan, ALLE_FEATURES
from product.licensing.license import (
    LizenzDaten, LizenzFehler,
    lizenz_pruefen, lizenz_laden, feature_erlaubt,
)
from product.licensing.keygen import schluessel_erzeugen


# ── 1. Features + Pakete ─────────────────────────────────────────────────────

class TestFeatures(unittest.TestCase):

    def test_starter_nur_suchen(self):
        f = features_fuer_plan("starter")
        assert Feature.SUCHEN in f
        assert Feature.CLOSER not in f
        assert Feature.FREIGABE not in f

    def test_pro_hat_freigabe(self):
        f = features_fuer_plan("pro")
        assert Feature.FREIGABE in f
        assert Feature.CLOSER not in f

    def test_enterprise_hat_closer(self):
        f = features_fuer_plan("enterprise")
        assert Feature.CLOSER in f
        assert Feature.FREIGABE in f

    def test_unbekannter_plan_fallback_starter(self):
        f = features_fuer_plan("unknown_xyz")
        assert Feature.SUCHEN in f
        assert Feature.CLOSER not in f

    def test_alle_features_vollstaendig(self):
        assert len(ALLE_FEATURES) == len(Feature)

    def test_pakete_aufsteigend(self):
        starter = set(features_fuer_plan("starter"))
        pro = set(features_fuer_plan("pro"))
        enterprise = set(features_fuer_plan("enterprise"))
        assert starter.issubset(pro)
        assert pro.issubset(enterprise)


# ── 2. Schlüssel erzeugen + prüfen ───────────────────────────────────────────

class TestLizenzRoundtrip(unittest.TestCase):

    def test_starter_roundtrip(self):
        key = schluessel_erzeugen("Test GmbH", "starter", 0)
        ld = lizenz_pruefen(key)
        assert ld.kunde == "Test GmbH"
        assert ld.plan == "starter"
        assert Feature.SUCHEN in ld.features
        assert ld.ablauf == 0

    def test_pro_roundtrip(self):
        key = schluessel_erzeugen("Muster AG", "pro", 365)
        ld = lizenz_pruefen(key)
        assert ld.plan == "pro"
        assert Feature.FREIGABE in ld.features
        assert ld.ablauf > 0

    def test_enterprise_roundtrip(self):
        key = schluessel_erzeugen("Big Corp", "enterprise", 0)
        ld = lizenz_pruefen(key)
        assert Feature.CLOSER in ld.features

    def test_zwei_schluessel_verschieden(self):
        k1 = schluessel_erzeugen("A", "starter", 0)
        k2 = schluessel_erzeugen("B", "starter", 0)
        assert k1 != k2

    def test_ablauf_berechnung(self):
        key = schluessel_erzeugen("X", "pro", 30)
        ld = lizenz_pruefen(key)
        tage = ld.tage_verbleibend()
        assert tage is not None
        assert 28 <= tage <= 30

    def test_unbegrenzt(self):
        key = schluessel_erzeugen("X", "pro", 0)
        ld = lizenz_pruefen(key)
        assert ld.tage_verbleibend() is None
        assert not ld.ist_abgelaufen()


# ── 3. Fehler-Cases ──────────────────────────────────────────────────────────

class TestLizenzFehler(unittest.TestCase):

    def test_leerer_key(self):
        with self.assertRaises(LizenzFehler):
            lizenz_pruefen("")

    def test_ungueltige_signatur(self):
        key = schluessel_erzeugen("X", "pro", 0)
        manipuliert = key[:-3] + "AAA"
        with self.assertRaises(LizenzFehler) as ctx:
            lizenz_pruefen(manipuliert)
        assert "signatur" in str(ctx.exception).lower()

    def test_abgelaufener_key(self):
        # Ablauf in der Vergangenheit: -1 Tag
        ablauf = int(time.time()) - 86400
        from product.licensing.license import _sign
        import base64
        payload = f"Alter Kunde|pro|{ablauf}"
        sig = _sign(payload)
        enc = base64.b32encode(payload.encode()).decode().rstrip("=")
        key = f"{enc}.{sig}"
        with self.assertRaises(LizenzFehler) as ctx:
            lizenz_pruefen(key)
        assert "abgelaufen" in str(ctx.exception).lower()

    def test_kaputtes_format(self):
        with self.assertRaises(LizenzFehler):
            lizenz_pruefen("kein-punkt-hier")

    def test_lizenz_laden_gibt_none_bei_leerem_key(self):
        assert lizenz_laden("") is None

    def test_lizenz_laden_gibt_none_bei_ungueltigem_key(self):
        assert lizenz_laden("AAAA.BBBB") is None


# ── 4. feature_erlaubt ───────────────────────────────────────────────────────

class TestFeatureErlaubt(unittest.TestCase):

    def test_keine_lizenz_alles_erlaubt(self):
        for f in Feature:
            assert feature_erlaubt(None, f) is True

    def test_starter_suchen_erlaubt(self):
        key = schluessel_erzeugen("X", "starter", 0)
        ld = lizenz_pruefen(key)
        assert feature_erlaubt(ld, Feature.SUCHEN) is True

    def test_starter_closer_nicht_erlaubt(self):
        key = schluessel_erzeugen("X", "starter", 0)
        ld = lizenz_pruefen(key)
        assert feature_erlaubt(ld, Feature.CLOSER) is False

    def test_enterprise_closer_erlaubt(self):
        key = schluessel_erzeugen("X", "enterprise", 0)
        ld = lizenz_pruefen(key)
        assert feature_erlaubt(ld, Feature.CLOSER) is True

    def test_hat_feature_methode(self):
        ld = LizenzDaten("X", "pro", features_fuer_plan("pro"))
        assert ld.hat_feature(Feature.FREIGABE) is True
        assert ld.hat_feature(Feature.CLOSER) is False


# ── 5. LizenzDaten.zusammenfassung ───────────────────────────────────────────

class TestZusammenfassung(unittest.TestCase):

    def test_keine_secrets_in_zusammenfassung(self):
        key = schluessel_erzeugen("Geheimkunde", "pro", 0)
        ld = lizenz_pruefen(key)
        z = ld.zusammenfassung()
        # Der Key selbst darf nicht auftauchen
        assert key not in z
        assert "Geheimkunde" in z
        assert "pro" in z.lower()

    def test_unbegrenzt_text(self):
        ld = LizenzDaten("X", "starter", features_fuer_plan("starter"), ablauf=0)
        assert "unbegrenzt" in ld.zusammenfassung()


# ── 6. Config lädt license_key ───────────────────────────────────────────────

class TestConfigLicenseKey(unittest.TestCase):

    def test_config_laedt_lizenz(self):
        import json, tempfile
        from pathlib import Path
        from product.telegram.config import laden

        key = schluessel_erzeugen("TestKunde", "pro", 0)
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "product_config.json"
            pfad.write_text(json.dumps({
                "bot_token": "tok",
                "owner_chat_id": "123",
                "engine_dir": ".",
                "data_dir": "data",
                "license_key": key,
            }), encoding="utf-8")
            cfg = laden(pfad)
        assert cfg.license_key == key
        assert cfg.lizenz is not None
        assert cfg.lizenz.plan == "pro"

    def test_config_ohne_key_lizenz_none(self):
        import json, tempfile
        from pathlib import Path
        from product.telegram.config import laden

        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "product_config.json"
            pfad.write_text(json.dumps({
                "bot_token": "tok",
                "owner_chat_id": "123",
                "engine_dir": ".",
                "data_dir": "data",
            }), encoding="utf-8")
            cfg = laden(pfad)
        assert cfg.lizenz is None


# ── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 58)
    print("  Schritt 12 — Lizenz & Feature-Flag Tests")
    print("=" * 58)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestFeatures, TestLizenzRoundtrip, TestLizenzFehler,
                TestFeatureErlaubt, TestZusammenfassung, TestConfigLicenseKey]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"  ALLE {result.testsRun} Tests GRUEN")
    else:
        print(f"  {len(result.failures)} Fehler, {len(result.errors)} Errors")
    sys.exit(0 if result.wasSuccessful() else 1)
