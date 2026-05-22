from __future__ import annotations

import time
from typing import Any

from buglens.monitoring.adapters.arms_client import ARMSClient
from buglens.monitoring.adapters.sls_client import SLSClient
from buglens.monitoring.schemas.common import AtomicFilterDSL, Envelope, MonitoringAdapterError


class AtomicMonitoringService:
    """Read-only atomic capabilities facade for RUM querying."""

    def __init__(self, *, sls_client: SLSClient, arms_client: ARMSClient) -> None:
        self._sls = sls_client
        self._arms = arms_client

    def sls_search_logs(
        self,
        *,
        project: str,
        logstore: str,
        time_from_ms: int,
        time_to_ms: int,
        page_token: str | None = None,
        page_size: int = 100,
        filters: AtomicFilterDSL | None = None,
        reverse: bool = False,
        extra_query: dict[str, Any] | None = None,
    ) -> Envelope:
        return self._wrap(
            lambda: self._sls.search_logs(
                project=project,
                logstore=logstore,
                time_from_ms=time_from_ms,
                time_to_ms=time_to_ms,
                page_token=page_token,
                page_size=page_size,
                filters=filters,
                reverse=reverse,
                extra_query=extra_query,
            )
        )

    def sls_get_log_context(
        self,
        *,
        project: str,
        logstore: str,
        pack_id: str,
        pack_meta: str,
        back_lines: int = 20,
        forward_lines: int = 20,
    ) -> Envelope:
        return self._wrap(
            lambda: self._sls.get_log_context(
                project=project,
                logstore=logstore,
                pack_id=pack_id,
                pack_meta=pack_meta,
                back_lines=back_lines,
                forward_lines=forward_lines,
            )
        )

    def sls_get_log_histogram(
        self,
        *,
        project: str,
        logstore: str,
        time_from_ms: int,
        time_to_ms: int,
        filters: AtomicFilterDSL | None = None,
        extra_query: dict[str, Any] | None = None,
    ) -> Envelope:
        return self._wrap(
            lambda: self._sls.get_log_histogram(
                project=project,
                logstore=logstore,
                time_from_ms=time_from_ms,
                time_to_ms=time_to_ms,
                filters=filters,
                extra_query=extra_query,
            )
        )

    def sls_list_projects(self, *, page_token: str | None = None, page_size: int = 100) -> Envelope:
        return self._wrap(lambda: self._sls.list_projects(page_token=page_token, page_size=page_size))

    def sls_list_logstores(
        self,
        *,
        project: str,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> Envelope:
        return self._wrap(
            lambda: self._sls.list_logstores(project=project, page_token=page_token, page_size=page_size)
        )

    def arms_list_rum_apps(
        self,
        *,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> Envelope:
        return self._wrap(
            lambda: self._arms.get_rum_apps(
                page_token=page_token,
                page_size=page_size,
            )
        )

    def _wrap(self, fn):
        started = time.perf_counter()
        try:
            result = fn()
            latency_ms = int((time.perf_counter() - started) * 1000)
            return Envelope(
                success=True,
                request_id=result.request_id,
                latency_ms=latency_ms,
                data=result.data,
                next_page_token=result.next_page_token,
                partial_success=result.partial_success,
            )
        except MonitoringAdapterError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return Envelope(
                success=False,
                request_id=exc.request_id,
                latency_ms=latency_ms,
                error=exc.to_error(),
            )
