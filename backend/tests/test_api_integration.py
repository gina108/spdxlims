from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.models import AppUser, AuditEvent, TestCatalog as CatalogModel


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BACKEND_INTEGRATION") != "1",
    reason="set RUN_BACKEND_INTEGRATION=1 and TEST_DATABASE_URL to run backend API integration tests",
)


@pytest.fixture()
def api_client():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for backend integration tests")

    engine = create_engine(database_url, future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        user = AppUser(
            email="integration-admin@example.test",
            full_name="Integration Admin",
            role="admin",
            password_hash=hash_password("Admin#12345"),
            is_active=True,
        )
        test = CatalogModel(
            code=f"CBC-{uuid.uuid4().hex[:8]}",
            name="Complete Blood Count",
            result_kind="numeric",
            price=100,
            unit="g/dL",
            active=True,
        )
        db.add_all([user, test])
        db.commit()

    try:
        yield TestClient(app), TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": "integration-admin@example.test", "password": "Admin#12345"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_patient_order_result_report_happy_path(api_client):
    api_client, testing_session_local = api_client
    headers = _login(api_client)

    patient_response = api_client.post(
        "/api/patients",
        headers=headers,
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "sex": "F",
            "age_value": 36,
            "age_unit": "years",
            "is_active": True,
        },
    )
    assert patient_response.status_code == 200, patient_response.text
    patient_id = patient_response.json()["id"]

    tests_response = api_client.get("/api/tests", headers=headers)
    assert tests_response.status_code == 200, tests_response.text
    test_id = tests_response.json()[0]["id"]

    order_response = api_client.post(
        "/api/orders",
        headers=headers,
        json={"patient_id": patient_id, "test_ids": [test_id], "status": "registered"},
    )
    assert order_response.status_code == 200, order_response.text
    order_id = order_response.json()["id"]

    entries_response = api_client.get(f"/api/results/orders/{order_id}/entries", headers=headers)
    assert entries_response.status_code == 200, entries_response.text
    entries = entries_response.json()
    assert len([entry for entry in entries if entry["item_type"] == "test"]) == 1
    order_item_id = entries[0]["order_test_id"]

    result_response = api_client.post(
        f"/api/results/order-items/{order_item_id}",
        headers=headers,
        json={
            "result_value": "13.5",
            "unit": "g/dL",
            "lower_value": "12",
            "upper_value": "16",
            "reference_text": "",
            "comments": "Looks good",
            "result_kind": "numeric",
        },
    )
    assert result_response.status_code == 200, result_response.text
    assert result_response.json()["flag"] == "normal"

    preview_response = api_client.get(f"/api/reports/orders/{order_id}/live-preview", headers=headers)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["patient_name"] == "Ada Lovelace"
    assert preview["items"][0]["result_value"] == "13.5"

    finalize_response = api_client.post(f"/api/reports/orders/{order_id}/finalize", headers=headers, json={})
    assert finalize_response.status_code == 200, finalize_response.text
    assert finalize_response.json()["status"] == "final"

    saved_response = api_client.get(f"/api/reports/orders/{order_id}/saved-preview", headers=headers)
    assert saved_response.status_code == 200, saved_response.text
    assert saved_response.json()["source"] == "saved"

    workflow_response = api_client.get("/api/reports/results-workflow", headers=headers)
    assert workflow_response.status_code == 200, workflow_response.text
    workflow_row = next((row for row in workflow_response.json() if row["id"] == order_id), None)
    assert workflow_row is not None, "finalized order missing from results-workflow list"
    assert workflow_row["patient_name"] == "Ada Lovelace"
    assert workflow_row["result_count"] == 1
    assert workflow_row["completed_result_count"] == 1
    assert workflow_row["report_version"] == 1

    with testing_session_local() as db:
        actions = [row.action for row in db.query(AuditEvent).order_by(AuditEvent.id).all()]
    assert "create" in actions
    assert "save" in actions
    assert "finalize" in actions
