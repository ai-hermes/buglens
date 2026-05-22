from __future__ import annotations

from buglens.monitoring.schemas.common import AdapterResult, MonitoringAdapterError, UnifiedErrorCode
from buglens.monitoring.services.atomic_monitoring import AtomicMonitoringService


class _FakeSLS:
    def search_logs(self, **kwargs):
        return AdapterResult(data={"items": [{"msg": "ok"}]}, request_id="sls-1")

    def get_log_context(self, **kwargs):
        return AdapterResult(data={"items": []}, request_id="ctx-1")

    def get_log_histogram(self, **kwargs):
        return AdapterResult(data={"histograms": []}, request_id="hist-1")

    def list_projects(self, **kwargs):
        return AdapterResult(data={"items": []}, request_id="lp-1")

    def list_logstores(self, **kwargs):
        return AdapterResult(data={"items": []}, request_id="ll-1")


class _FakeARMS:
    def get_rum_apps(self, **kwargs):
        return AdapterResult(data={"items": [{"pid": "app-1"}]}, request_id="a-1")

    def get_rum_apps_error(self, **kwargs):
        raise MonitoringAdapterError(code=UnifiedErrorCode.RATE_LIMITED, message="too many")


def test_service_success_envelope() -> None:
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=_FakeARMS())
    result = svc.sls_search_logs(project="p", logstore="l", time_from_ms=1, time_to_ms=2)
    assert result.success is True
    assert result.request_id == "sls-1"
    assert result.data == {"items": [{"msg": "ok"}]}


def test_service_partial_success_envelope() -> None:
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=_FakeARMS())
    result = svc.arms_list_rum_apps()
    assert result.success is True
    assert result.data == {"items": [{"pid": "app-1"}]}


def test_service_error_envelope() -> None:
    arms = _FakeARMS()
    arms.get_rum_apps = arms.get_rum_apps_error  # type: ignore[method-assign]
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=arms)
    result = svc.arms_list_rum_apps()
    assert result.success is False
    assert result.error is not None
    assert result.error.code == UnifiedErrorCode.RATE_LIMITED
