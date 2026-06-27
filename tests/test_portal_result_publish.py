from __future__ import annotations

from pathlib import Path

from spdxlims.portal.result_service import PortalResultService
from spdxlims.portal.settings import PortalSettings, PortalStore


def _store(tmp_path: Path) -> PortalStore:
    return PortalStore(tmp_path)


def test_record_and_resolve_link(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_import_link("42", 7)
    assert store.portal_order_id_for("42") == 7
    assert store.portal_order_id_for(42) == 7  # int/str keys are equivalent
    assert store.portal_order_id_for("999") is None


def test_publish_not_linked_is_noop(tmp_path: Path) -> None:
    svc = PortalResultService(_store(tmp_path))
    assert svc.publish("123", b"%PDF-1.4") == "not_linked"


def test_publish_queues_when_unconfigured_then_retry_uploads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_import_link("42", 7)
    svc = PortalResultService(store)

    # No portal settings yet -> upload can't happen, PDF is stashed.
    assert svc.publish("42", b"%PDF-bytes") == "queued"
    pending = store.list_pending_results()
    assert pending == [("42", b"%PDF-bytes")]

    # Configure + stub the client so retry can deliver it.
    store.save_settings(PortalSettings(base_url="https://x.workers.dev", shared_secret="s"))
    uploaded: list[tuple[int, bytes]] = []

    class _StubClient:
        def __init__(self, *_a, **_k) -> None: ...

        def upload_result(self, order_id: int, pdf_bytes: bytes) -> dict:
            uploaded.append((order_id, pdf_bytes))
            return {"ok": True}

    import spdxlims.portal.result_service as mod

    original = mod.PortalClient
    mod.PortalClient = _StubClient  # type: ignore[assignment]
    try:
        assert svc.retry_pending() == 1
    finally:
        mod.PortalClient = original

    assert uploaded == [(7, b"%PDF-bytes")]
    assert store.list_pending_results() == []  # stash cleared after delivery


def test_retry_drops_orphaned_stash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_settings(PortalSettings(base_url="https://x.workers.dev", shared_secret="s"))
    store.stash_pending_result("777", b"%PDF")  # no link recorded for 777
    svc = PortalResultService(store)

    import spdxlims.portal.result_service as mod

    class _StubClient:
        def __init__(self, *_a, **_k) -> None: ...

        def upload_result(self, *_a, **_k) -> dict:  # pragma: no cover - must not be called
            raise AssertionError("orphaned stash should not be uploaded")

    original = mod.PortalClient
    mod.PortalClient = _StubClient  # type: ignore[assignment]
    try:
        assert svc.retry_pending() == 0
    finally:
        mod.PortalClient = original
    assert store.list_pending_results() == []  # orphan removed
