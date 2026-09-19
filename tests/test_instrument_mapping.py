from __future__ import annotations

from dataclasses import dataclass

import pytest

from spdxlims.database import Database
from spdxlims.instrument_mapping import resolve_payload

PROFILE = "mindray-bc30s"


@dataclass
class FakeEntry:
    """An order's test as the backend returns it: UUID id, code in the name."""

    test_id: str
    test_name: str
    specimen_type: str = ""
    source_label: str = ""


@pytest.fixture()
def database(tmp_path):
    database = Database(tmp_path / "spdxlims.db")
    database.initialize()
    return database


def _add_test(database: Database, code: str, name: str, *, result_kind: str = "numeric") -> int:
    database.create_test(
        {
            "code": code,
            "name": name,
            "category_name": "Hematologia",
            "result_kind": result_kind,
            "price": 0,
        },
        [],
    )
    return next(test.id for test in database.list_tests() if test.code == code)


def _capture(profile_id: str = PROFILE, device_id: str = "") -> dict:
    return {"id": "cap_1", "profile_id": profile_id, "device_id": device_id}


def _result(observations: list[dict]) -> dict:
    return {"capture_id": "cap_1", "message": {"source_profile_id": PROFILE, "observations": observations}}


def _first(payload: dict) -> dict:
    return payload["message"]["observations"][0]


def test_loinc_code_is_rewritten_to_the_lab_catalog_code(database):
    test_id = _add_test(database, "WBC", "Leucocitos")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE, device_id="", raw_code="6690-2", raw_name="WBC", test_id=test_id
    )

    resolved = resolve_payload(
        database, _capture(), _result([{"instrument_test_code": "6690-2", "value_raw": "7.7"}])
    )

    assert _first(resolved)["mapped_lis_test_id"] == "WBC"
    assert _first(resolved)["value_raw"] == "7.7"


def test_the_mapping_formula_is_applied_to_every_value_field(database):
    test_id = _add_test(database, "PLT", "Plaquetas")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE,
        device_id="",
        raw_code="777-3",
        raw_name="PLT",
        test_id=test_id,
        value_formula="*1000",
    )

    observation = {"instrument_test_code": "777-3", "value_raw": "245", "value_numeric": 245.0}
    resolved = _first(resolve_payload(database, _capture(), _result([observation])))

    assert resolved["mapped_lis_test_id"] == "PLT"
    assert resolved["value_raw"] == "245000"
    assert resolved["value_numeric"] == 245000.0


def test_a_mapping_scoped_to_a_specimen_resolves_through_the_order(database):
    test_id = _add_test(database, "TPT", "Tiempo de tromboplastina")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE,
        device_id="",
        raw_code="2",
        raw_name="APTT",
        test_id=test_id,
        specimen_type="plasma citratado 2 ml",
        panel_hint="tp y ttp",
    )
    observation = {"instrument_test_code": "2", "value_raw": "23.6"}

    # The analyzer reports no specimen, so the mapping only resolves once the
    # order's own tests are offered as candidates.
    without_order = _first(resolve_payload(database, _capture(), _result([observation])))
    assert without_order.get("mapped_lis_test_id") is None

    entries = [FakeEntry("11111111-2222-3333-4444-555555555555", "Tromboplastina (TPT)", "plasma citratado 2 ml", "tp y ttp")]
    with_order = _first(resolve_payload(database, _capture(), _result([observation]), entries))
    assert with_order["mapped_lis_test_id"] == "TPT"


def test_a_mapping_scoped_to_a_panel_this_database_does_not_use_still_resolves(database):
    test_id = _add_test(database, "TPT", "Tiempo de tromboplastina")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE,
        device_id="",
        raw_code="2",
        raw_name="APTT",
        test_id=test_id,
        specimen_type="plasma citratado 2 ml",
        panel_hint="tp y ttp",
    )
    # The server calls the same panel something else, so no scoped lookup can
    # match; the test being in the order is what makes the mapping acceptable.
    entries = [FakeEntry("11111111-2222-3333-4444-555555555555", "Tromboplastina (TPT)", "Plasma citratado 2 ml", "TIEMPO DE PROTROMBINA Y TROMBOPLASTINA")]

    resolved = _first(resolve_payload(database, _capture(), _result([{"instrument_test_code": "2", "value_raw": "23.6"}]), entries))

    assert resolved["mapped_lis_test_id"] == "TPT"


def test_a_scoped_mapping_is_not_used_when_its_test_is_not_in_the_order(database):
    test_id = _add_test(database, "TPT", "Tiempo de tromboplastina")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE,
        device_id="",
        raw_code="2",
        raw_name="APTT",
        test_id=test_id,
        specimen_type="plasma citratado 2 ml",
        panel_hint="tp y ttp",
    )
    entries = [FakeEntry("11111111-2222-3333-4444-555555555555", "Glucosa (GLU)", "suero", "QUIMICA")]

    resolved = _first(resolve_payload(database, _capture(), _result([{"instrument_test_code": "2", "value_raw": "23.6"}]), entries))

    assert resolved.get("mapped_lis_test_id") is None


def test_an_unmapped_observation_is_passed_through_untouched(database):
    observation = {"instrument_test_code": "GLU", "mapped_lis_test_id": "GLUO", "value_raw": "105.7"}

    resolved = _first(resolve_payload(database, _capture(), _result([observation])))

    assert resolved == observation


def test_a_character_range_that_empties_the_value_is_ignored(database):
    test_id = _add_test(database, "LEU", "Leucocitos en orina", result_kind="text")
    database.save_instrument_result_mapping(
        instrument_profile=PROFILE,
        device_id="",
        raw_code="LEU",
        raw_name="LEU",
        test_id=test_id,
        value_slice_start=0,
        value_slice_end=3,
    )

    resolved = _first(
        resolve_payload(database, _capture(), _result([{"instrument_test_code": "LEU", "value_raw": "Negativo"}]))
    )

    assert resolved["mapped_lis_test_id"] == "LEU"
    assert resolved["value_raw"] == "Negativo"
