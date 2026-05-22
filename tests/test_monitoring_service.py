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
    def search_traces(self, **kwargs):
        return AdapterResult(data={"items": []}, request_id="a-1")

    def get_trace(self, **kwargs):
        return AdapterResult(data={"trace": {}}, request_id="a-2")

    def get_multiple_traces(self, **kwargs):
        return AdapterResult(data={"items": [], "failures": [{}]}, request_id="a-3", partial_success=True)

    def query_metric_by_page(self, **kwargs):
        return AdapterResult(data={"items": []}, request_id="a-4")

    def list_insights_events(self, **kwargs):
        raise MonitoringAdapterError(code=UnifiedErrorCode.RATE_LIMITED, message="too many")


def test_service_success_envelope() -> None:
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=_FakeARMS())
    result = svc.sls_search_logs(project="p", logstore="l", time_from_ms=1, time_to_ms=2)
    assert result.success is True
    assert result.request_id == "sls-1"
    assert result.data == {"items": [{"msg": "ok"}]}


def test_service_partial_success_envelope() -> None:
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=_FakeARMS())
    result = svc.arms_get_multiple_traces(trace_ids=["a", "b"])
    assert result.success is True
    assert result.partial_success is True


def test_service_error_envelope() -> None:
    svc = AtomicMonitoringService(sls_client=_FakeSLS(), arms_client=_FakeARMS())
    result = svc.arms_list_insights_events(time_from_ms=1, time_to_ms=2)
    assert result.success is False
    assert result.error is not None
    assert result.error.code == UnifiedErrorCode.RATE_LIMITED
