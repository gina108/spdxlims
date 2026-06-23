import base64

from spdxlims.database import Database
from spdxlims.report_layout import build_report_html


# A 1x1 PNG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_image_result_end_to_end(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = database.create_patient(
        {
            "first_name": "Ana",
            "last_name": "Lopez",
            "middle_name": "",
            "sex": "F",
            "date_of_birth": "",
            "age_value": 40,
            "age_unit": "years",
            "phone": "",
        }
    )
    database.create_test(
        {
            "code": "SMEAR",
            "name": "Frotis de Sangre Periferica",
            "category_name": "Hematology",
            "specimen_type": "Sangre",
            "method": "",
            "result_kind": "image",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("SMEAR")
    order_id = database.create_order(
        None, None, None, patient_id, None, None,
        [{"item_type": "test", "test_id": test_id, "label": "Frotis", "source": ""}],
        "draft", "",
    )

    entry = database.get_order_result_entries(order_id)[0]
    assert entry.result_kind == "image"

    img1 = database.add_result_image(entry.order_test_id, _PNG, mime_type="image/png", caption="Campo 1")
    database.add_result_image(entry.order_test_id, _PNG, mime_type="image/png", caption="Campo 2")
    images = database.list_result_images(entry.order_test_id, include_data=True)
    assert len(images) == 2
    assert images[0]["caption"] == "Campo 1"

    # Summary written back into the result value.
    refreshed = database.get_order_result_entries(order_id)[0]
    assert refreshed.result_value and "2" in refreshed.result_value

    # Live preview carries base64 image data on the image item.
    live = database.get_live_report_preview(order_id)
    image_items = [i for i in live["items"] if i.get("result_kind") == "image"]
    assert image_items and len(image_items[0]["images"]) == 2
    assert image_items[0]["images"][0]["data"]

    html = build_report_html({**database.get_report_layout_settings(), **live})
    assert "data:image/png;base64," in html
    assert "Campo 1" in html

    # Reorder + delete.
    ids = [im["id"] for im in images]
    database.reorder_result_images(entry.order_test_id, [ids[1], ids[0]])
    reordered = database.list_result_images(entry.order_test_id)
    assert reordered[0]["caption"] == "Campo 2"
    database.delete_result_image(img1)
    assert len(database.list_result_images(entry.order_test_id)) == 1

    # Finalize snapshots the (now single) image; saved preview renders from snapshot.
    database.finalize_report(order_id)
    saved = database.get_saved_report_preview(order_id)
    saved_image_items = [i for i in saved["items"] if i.get("result_kind") == "image"]
    assert saved_image_items and len(saved_image_items[0]["images"]) == 1

    # Deleting the live image after finalize must not change the finalized snapshot.
    remaining = database.list_result_images(entry.order_test_id)
    database.delete_result_image(remaining[0]["id"])
    saved_again = database.get_saved_report_preview(order_id)
    saved_image_items2 = [i for i in saved_again["items"] if i.get("result_kind") == "image"]
    assert saved_image_items2 and len(saved_image_items2[0]["images"]) == 1
