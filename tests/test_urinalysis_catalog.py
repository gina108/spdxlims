from __future__ import annotations

from spdxlims.database import Database


def test_initialize_adds_urinalysis_strip_tests_to_choices(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()

    labels_by_code = {
        label.rsplit("(", 1)[-1].rstrip(")"): label
        for _test_id, label in database.list_test_choices()
    }

    for code in ["EGO-LEU", "EGO-NIT", "EGO-URO", "EGO-PRO", "EGO-PH", "EGO-BLO", "EGO-SG", "EGO-KET", "EGO-BIL", "EGO-GLU"]:
        assert code in labels_by_code
