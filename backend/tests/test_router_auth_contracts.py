import inspect

from fastapi.params import Depends

from app.routers import lab_profile, operations, orders, panels, patients, providers, reports, results, tests
from app.routers.common import actor_from_header


def _depends_on_actor(function, parameter_name: str = "actor") -> bool:
    dependency = inspect.signature(function).parameters[parameter_name].default
    return isinstance(dependency, Depends) and dependency.dependency is actor_from_header


def test_patient_shared_workflow_endpoints_require_authenticated_actor():
    assert _depends_on_actor(patients.list_patients, "_actor")
    assert _depends_on_actor(patients.get_patient, "_actor")
    assert _depends_on_actor(patients.create_patient)
    assert _depends_on_actor(patients.update_patient)
    assert _depends_on_actor(patients.archive_patient)
    assert _depends_on_actor(patients.unarchive_patient)


def test_order_write_endpoints_require_authenticated_actor():
    assert _depends_on_actor(orders.create_order)
    assert _depends_on_actor(orders.update_order)
    assert _depends_on_actor(orders.search_orders, "_actor")


def test_result_entry_endpoints_require_authenticated_actor():
    assert _depends_on_actor(results.get_order_entries, "_actor")
    assert _depends_on_actor(results.save_order_item_result)
    assert _depends_on_actor(results.import_instrument_results)


def test_lab_profile_endpoints_require_authentication():
    assert _depends_on_actor(lab_profile.get_lab_profile, "_actor")
    save_dependency = inspect.signature(lab_profile.save_lab_profile).parameters["actor"].default
    assert isinstance(save_dependency, Depends)


def test_report_endpoints_require_authenticated_actor():
    assert _depends_on_actor(reports.list_report_order_choices, "_actor")
    assert _depends_on_actor(reports.get_live_report_preview, "_actor")
    assert _depends_on_actor(reports.get_saved_report_preview, "_actor")
    assert _depends_on_actor(reports.finalize_report)


def test_catalog_endpoints_require_authenticated_actor():
    assert _depends_on_actor(tests.list_tests, "_actor")
    assert _depends_on_actor(tests.get_test, "_actor")
    assert _depends_on_actor(tests.create_test)
    assert _depends_on_actor(tests.update_test)
    assert _depends_on_actor(tests.archive_test)
    assert _depends_on_actor(tests.unarchive_test)
    assert _depends_on_actor(panels.list_panels, "_actor")
    assert _depends_on_actor(panels.get_panel, "_actor")
    assert _depends_on_actor(panels.create_panel)
    assert _depends_on_actor(panels.update_panel)
    assert _depends_on_actor(panels.archive_panel)
    assert _depends_on_actor(panels.unarchive_panel)


def test_provider_write_endpoints_require_authenticated_actor():
    assert _depends_on_actor(providers.create_provider)
    assert _depends_on_actor(providers.update_provider)
    assert _depends_on_actor(providers.archive_provider)
    assert _depends_on_actor(providers.unarchive_provider)


def test_operations_backup_status_endpoints_require_roles():
    get_dependency = inspect.signature(operations.get_backup_status).parameters["_actor"].default
    update_dependency = inspect.signature(operations.update_backup_status).parameters["actor"].default
    assert isinstance(get_dependency, Depends)
    assert isinstance(update_dependency, Depends)
