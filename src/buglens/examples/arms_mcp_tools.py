from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from buglens.config import SubAgentConfig, bootstrap_process_env_from_dotenv
from buglens.monitoring import ARMSClient, AtomicMonitoringService, SLSClient


def _load_env() -> None:
    # Prefer loading repo-root .env so this script works from any cwd.
    repo_root = Path(__file__).resolve().parents[3]
    bootstrap_process_env_from_dotenv(str(repo_root / ".env"))
    # Fallback to current working directory.
    bootstrap_process_env_from_dotenv()


def _build_monitoring_service() -> AtomicMonitoringService:
    _load_env()
    config = SubAgentConfig()
    if not config.enable_mcp_tools:
        raise RuntimeError("BUGLENS_ENABLE_MCP_TOOLS=false, monitoring tools are disabled.")
    if not config.has_monitoring_credentials():
        raise RuntimeError(
            "Missing monitoring credentials: BUGLENS_ALIBABA_ACCESS_KEY_ID/SECRET/REGION_ID."
        )
    sls = SLSClient(
        access_key_id=str(config.alibaba_access_key_id),
        access_key_secret=str(config.alibaba_access_key_secret),
        security_token=config.alibaba_security_token,
        region_id=str(config.alibaba_region_id),
        endpoint=config.sls_endpoint,
        max_retries=config.monitoring_max_retries,
        base_backoff_seconds=config.monitoring_base_backoff_seconds,
        max_backoff_seconds=config.monitoring_max_backoff_seconds,
        max_concurrency=config.monitoring_max_concurrency,
    )
    arms_kwargs: dict[str, Any] = {
        "access_key_id": str(config.alibaba_access_key_id),
        "access_key_secret": str(config.alibaba_access_key_secret),
        "security_token": config.alibaba_security_token,
        "region_id": str(config.alibaba_region_id),
        "max_retries": config.monitoring_max_retries,
        "base_backoff_seconds": config.monitoring_base_backoff_seconds,
        "max_backoff_seconds": config.monitoring_max_backoff_seconds,
        "max_concurrency": config.monitoring_max_concurrency,
    }
    if config.arms_endpoint:
        arms_kwargs["endpoint"] = config.arms_endpoint
    arms = ARMSClient(**arms_kwargs)
    return AtomicMonitoringService(sls_client=sls, arms_client=arms)


def _compact_kwargs(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _add_common_project_logstore_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", help="SLS project; falls back to BUGLENS_RUM_SLS_PROJECT")
    parser.add_argument("--logstore", help="SLS logstore; falls back to BUGLENS_RUM_SLS_LOGSTORE")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run buglens ARMS/RUM MCP tools independently from local environment."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_list = subparsers.add_parser("list-apps", help="Call arms_rum_list_apps")
    p_list.add_argument("--page-size", type=int, default=100)
    p_list.add_argument("--page-token")

    p_search = subparsers.add_parser("search-errors", help="Call arms_rum_search_errors")
    _add_common_project_logstore_flags(p_search)
    p_search.add_argument("--time-from-ms", type=int)
    p_search.add_argument("--time-to-ms", type=int)
    p_search.add_argument("--query", default="*")
    p_search.add_argument("--page-token")
    p_search.add_argument("--page-size", type=int, default=50)
    p_search.add_argument("--reverse", dest="reverse", action="store_true")
    p_search.add_argument("--no-reverse", dest="reverse", action="store_false")
    p_search.set_defaults(reverse=True)

    p_ctx = subparsers.add_parser("get-error-context", help="Call arms_rum_get_error_context")
    _add_common_project_logstore_flags(p_ctx)
    p_ctx.add_argument("--pack-id", required=True)
    p_ctx.add_argument("--pack-meta", required=True)
    p_ctx.add_argument("--back-lines", type=int, default=30)
    p_ctx.add_argument("--forward-lines", type=int, default=30)

    p_detail = subparsers.add_parser("get-error-detail", help="Call arms_get_error_detail")
    _add_common_project_logstore_flags(p_detail)
    p_detail.add_argument("--time-from-ms", type=int)
    p_detail.add_argument("--time-to-ms", type=int)
    p_detail.add_argument("--app")
    p_detail.add_argument("--page")
    p_detail.add_argument("--version")
    p_detail.add_argument("--error-message")
    p_detail.add_argument("--query")
    p_detail.add_argument("--page-size", type=int, default=20)

    return parser


def _resolve_time_range(from_ms: int | None, to_ms: int | None) -> tuple[int, int]:
    if from_ms is not None and to_ms is not None:
        return from_ms, to_ms
    now_ms = int(time.time() * 1000)
    default_from = now_ms - 60 * 60 * 1000
    return from_ms or default_from, to_ms or now_ms


def _resolve_rum_sls_target(
    *,
    project: str | None,
    logstore: str | None,
    config: SubAgentConfig,
) -> tuple[str, str]:
    final_project = project or config.rum_sls_project
    final_logstore = logstore or config.rum_sls_logstore
    if not final_project or not final_logstore:
        raise ValueError(
            "RUM queries require project/logstore (set --project/--logstore or BUGLENS_RUM_SLS_PROJECT/BUGLENS_RUM_SLS_LOGSTORE)."
        )
    return str(final_project), str(final_logstore)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _load_env()
    config = SubAgentConfig()
    monitoring = _build_monitoring_service()

    if args.command == "list-apps":
        kwargs = _compact_kwargs(
            {
                "page_size": args.page_size,
                "page_token": args.page_token,
            }
        )
        result = monitoring.arms_list_rum_apps(**kwargs)
        _print_json(result.model_dump(mode="json", exclude_none=True))
        return

    if args.command == "search-errors":
        time_from_ms, time_to_ms = _resolve_time_range(args.time_from_ms, args.time_to_ms)
        project, logstore = _resolve_rum_sls_target(
            project=args.project,
            logstore=args.logstore,
            config=config,
        )
        kwargs = _compact_kwargs(
            {
                "project": project,
                "logstore": logstore,
                "time_from_ms": time_from_ms,
                "time_to_ms": time_to_ms,
                "page_token": args.page_token,
                "page_size": args.page_size,
                "reverse": args.reverse,
                "extra_query": {"query": args.query},
            }
        )
        result = monitoring.sls_search_logs(**kwargs)
        _print_json(result.model_dump(mode="json", exclude_none=True))
        return

    if args.command == "get-error-context":
        project, logstore = _resolve_rum_sls_target(
            project=args.project,
            logstore=args.logstore,
            config=config,
        )
        kwargs = _compact_kwargs(
            {
                "project": project,
                "logstore": logstore,
                "pack_id": args.pack_id,
                "pack_meta": args.pack_meta,
                "back_lines": args.back_lines,
                "forward_lines": args.forward_lines,
            }
        )
        result = monitoring.sls_get_log_context(**kwargs)
        _print_json(result.model_dump(mode="json", exclude_none=True))
        return

    if args.command == "get-error-detail":
        time_from_ms, time_to_ms = _resolve_time_range(args.time_from_ms, args.time_to_ms)
        project, logstore = _resolve_rum_sls_target(
            project=args.project,
            logstore=args.logstore,
            config=config,
        )
        query_parts: list[str] = []
        for value in (args.app, args.page, args.version, args.error_message):
            if value:
                query_parts.append(str(value))
        if args.query:
            query_parts.append(str(args.query))
        query = " and ".join(query_parts) if query_parts else "*"
        kwargs = {
            "project": project,
            "logstore": logstore,
            "time_from_ms": time_from_ms,
            "time_to_ms": time_to_ms,
            "page_size": args.page_size,
            "reverse": True,
            "extra_query": {"query": query},
        }
        result = monitoring.sls_search_logs(**kwargs)
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["query"] = query
        _print_json(payload)
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
