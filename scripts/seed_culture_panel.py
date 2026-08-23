"""Create (or update) the microbiology culture panels.

Culture panels render as the banded layout in report_layout.py -- title band,
optional free-form block, isolated-organism line, and antibiogram -- instead of
the standard ESTUDIO/RESULTADO/UNIDAD/REFERENCIA grid.

Antibiotics are ordinary `tests` rows (result_kind='select'), so ordering,
result entry and report snapshots all work unchanged, and they are shared across
panels -- CEFOTAXIMA is one test whether it appears on a vaginal or a wound
culture. Each panel's `culture_config` only describes how they are laid out.

The organisms searched are NOT tests: the tech types them into the free-form
two-column rows during result entry (stored in order_culture_data).

Usage:
    python scripts/seed_culture_panel.py [--db PATH] [--only CODE] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spdxlims.database import Database  # noqa: E402

SUSCEPTIBILITY_OPTIONS = ["Sensible", "Intermedio", "Resistente"]
CATEGORY = "Microbiología"

# Gram-positive battery (vaginal / uretral / faringeo-Staph / herida-Staph).
ANTIBIOTICS_POSITIVE = [
    ("ATB-AMP", "Ampicilina"),
    ("ATB-CEF", "Cefalotina"),
    ("ATB-CTX", "Cefotaxima"),
    ("ATB-CIP", "Ciprofloxacina"),
    ("ATB-CLI", "Clindamicina"),
    ("ATB-DIC", "Dicloxacilina"),
    ("ATB-ERI", "Eritromicina"),
    ("ATB-GEN", "Gentamicina"),
    ("ATB-PEN", "Penicilina"),
    ("ATB-TET", "Tetraciclina"),
    ("ATB-SXT", "Sulfametaxasol/Trimetroprim"),
    ("ATB-VAN", "Vancomicina"),
]

# Gram-negative battery (urocultivo / faringeo-Klebsiella / herida-E. coli).
ANTIBIOTICS_NEGATIVE = [
    ("ATB-AMK", "Amikacina"),
    ("ATB-AMP", "Ampicilina"),
    ("ATB-CARB", "Carbenicilina"),
    ("ATB-CEF", "Cefalotina"),
    ("ATB-CTX", "Cefotaxima"),
    ("ATB-CIP", "Ciprofloxacina"),
    ("ATB-CLO", "Cloranfenicol"),
    ("ATB-GEN", "Gentamicina"),
    ("ATB-NET", "Netilmicina"),
    ("ATB-NIT", "Nitrofurantoina"),
    ("ATB-NOR", "Norfloxacino"),
    ("ATB-SXT", "Sulfametaxasol/Trimetroprim"),
]

ANTIBIOTICS = ANTIBIOTICS_POSITIVE + [a for a in ANTIBIOTICS_NEGATIVE if a not in ANTIBIOTICS_POSITIVE]

# Disc load printed in the CONCENTRACION column.
CONCENTRATIONS = {
    "ATB-AMP": "10 µg", "ATB-CEF": "30 µg", "ATB-CTX": "30 µg", "ATB-CIP": "5 µg",
    "ATB-CLI": "30 µg", "ATB-DIC": "1 µg", "ATB-ERI": "15 µg", "ATB-GEN": "10 µg",
    "ATB-PEN": "10 U", "ATB-TET": "30 µg", "ATB-SXT": "25 µg", "ATB-VAN": "30 µg",
    "ATB-AMK": "30 µg", "ATB-CARB": "100 µg", "ATB-CLO": "30 µg", "ATB-NET": "30 µg",
    "ATB-NIT": "300 µg", "ATB-NOR": "10 µg",
}

ISOLATE = ("CULT-AGENTE", "Agente etiológico aislado")

METHOD_NOTE = "Método: CULTIVO BACTERIOLÓGICO EN MEDIOS ESPECÍFICOS."

# One entry per culture report. `top_heading` labels the free-form two-column
# block the tech fills in; leave it blank to omit that block entirely.
PANELS = [
    {
        "code": "CULT-VAG",
        "name": "CULTIVO DE EXUDADO VAGINAL",
        "title": "CULTIVO DE EXUDADO VAGINAL",
        "top_heading": "MICROORGANISMOS PATOGENOS BUSCADOS EN EL CULTIVO",
        "isolate_label": "AGENTE ETIOLOGICO AISLADO:",
        "susceptibility_heading": "Pruebas susceptibilidad antimicrobiana",
        "specimen": "Exudado vaginal",
        "method_note": "",
    },
    {
        "code": "CULT-URE",
        "name": "CULTIVO DE EXUDADO URETRAL",
        "title": "CULTIVO DE EXUDADO URETRAL",
        "top_heading": "MICROORGANISMOS PATOGENOS BUSCADOS EN EL CULTIVO",
        "isolate_label": "SE IDENTIFICÓ:",
        "susceptibility_heading": "ANTIBIOGRAMA",
        "specimen": "Exudado uretral",
        "method_note": METHOD_NOTE,
    },
    {
        "code": "CULT-FAR",
        "name": "CULTIVO DE EXUDADO FARINGEO",
        "title": "CULTIVO DE EXUDADO FARINGEO",
        # The faringeo report goes straight from the isolate to the antibiogram.
        "top_heading": "",
        "isolate_label": "AISLAMIENTO:",
        "susceptibility_heading": "ANTIBIOGRAMA",
        "specimen": "Exudado faríngeo",
        "method_note": METHOD_NOTE,
    },
    {
        "code": "CULT-HER",
        "name": "CULTIVO DE HERIDA",
        "title": "CULTIVO DE HERIDA",
        # The wound report's MICROSCOPIA block (GRAM:, LEUCOCITOS:, ERITROCITOS:)
        # is exactly the free-form two-column rows.
        "top_heading": "MICROSCOPIA",
        "isolate_label": "AISLAMIENTO:",
        "susceptibility_heading": "ANTIBIOGRAMA",
        "specimen": "Secreción de herida",
        "method_note": METHOD_NOTE,
    },
]


def ensure_test(db: Database, code: str, name: str, *, options: list[str] | None) -> int:
    existing = db.get_test_id_by_code(code)
    if existing is not None:
        return existing
    db.create_test(
        {
            "code": code, "name": name, "category_name": CATEGORY,
            "specimen_type": "", "method": "",
            "result_kind": "select" if options else "text",
            "select_options": options or None, "default_result_value": None,
            "price": 0, "result_multiplier": None, "formula": None,
        },
        [],
    )
    created = db.get_test_id_by_code(code)
    if created is None:
        raise RuntimeError(f"could not create test {code}")
    return created


def build_config(spec: dict) -> dict:
    return {
        "title": spec["title"],
        "pathogens_heading": spec["top_heading"],
        "isolate_label": spec["isolate_label"],
        "isolate_name": ISOLATE[1],
        "extra_names": [],
        "susceptibility_heading": spec["susceptibility_heading"],
        "gram_label_positive": "GRAM POSITIVOS:",
        "gram_label_negative": "GRAM NEGATIVOS:",
        "antibiotic_names_positive": [n for _c, n in ANTIBIOTICS_POSITIVE],
        "antibiotic_names_negative": [n for _c, n in ANTIBIOTICS_NEGATIVE],
        "antibiogram_col_1": "ANTIBIOTICO",
        "antibiogram_col_2": "INHIBICION",
        "antibiogram_col_3": "CONCENTRACION",
        "antibiotic_concentrations": {n: CONCENTRATIONS[c] for c, n in ANTIBIOTICS if c in CONCENTRATIONS},
        "method_note": spec["method_note"],
    }


def seed(db_path: Path, *, dry_run: bool = False, only: str = "") -> None:
    db = Database(db_path)
    db.initialize()

    test_ids = {ISOLATE[0]: ensure_test(db, ISOLATE[0], ISOLATE[1], options=None)}
    for code, name in ANTIBIOTICS:
        test_ids[code] = ensure_test(db, code, name, options=SUSCEPTIBILITY_OPTIONS)

    # Every panel carries the full antibiotic catalogue so the tech can fill in
    # whichever gram applies; culture_config decides which set prints.
    panel_items = [{"item_type": "test", "test_id": test_ids[ISOLATE[0]]}]
    panel_items += [{"item_type": "test", "test_id": test_ids[c]} for c, _n in ANTIBIOTICS]

    for spec in PANELS:
        if only and spec["code"] != only:
            continue
        existing_id = db.get_panel_id_by_code(spec["code"])
        if dry_run:
            print(f"[dry-run] would {'update' if existing_id else 'create'} {spec['code']} ({len(panel_items)} items)")
            continue
        if existing_id is None:
            db.create_panel(spec["code"], spec["name"], panel_items,
                            specimen_type=spec["specimen"],
                            method="Cultivo bacteriológico en medios específicos")
            panel_id = db.get_panel_id_by_code(spec["code"])
        else:
            panel_id = existing_id
            db.update_panel(panel_id, spec["code"], spec["name"], panel_items,
                            specimen_type=spec["specimen"],
                            method="Cultivo bacteriológico en medios específicos")
        db.set_panel_kind(panel_id, "cultivo", build_config(spec))
        print(f"  {spec['code']:<10} id={panel_id:<4} {spec['name']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "spdxlims.db"))
    parser.add_argument("--only", default="", help="seed just this panel code")
    parser.add_argument("--dry-run", action="store_true",
                        help="skip panel writes (schema migrations still run)")
    args = parser.parse_args()
    seed(Path(args.db), dry_run=args.dry_run, only=args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
