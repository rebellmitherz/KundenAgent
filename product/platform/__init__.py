"""Plattform-Schicht — Multi-Mandanten-Fähigkeit (Phase F3+).

Macht aus dem Einzel-Operator eine branchenunabhängige B2B-Akquise-Plattform:
mehrere Kunden (Mandanten), jeder mit eigenem, hart isoliertem Akquise-Agenten
(eigene Zielgruppe, Pipeline, Postfach/Engine, Daten, Reporting, Lizenz).

Bestehende Akquise-, Reply-, Follow-up- und Handoff-Logik wird NICHT
eingeschränkt — sie wird pro Mandant instanziiert (Bridge/Runner sind bereits
über engine_dir/data_dir parametrisiert).
"""
