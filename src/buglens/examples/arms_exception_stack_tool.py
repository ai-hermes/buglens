from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from buglens.config import SubAgentConfig, bootstrap_process_env_from_dotenv
from buglens.monitoring import ARMSClient, AtomicMonitoringService, SLSClient


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    bootstrap_process_env_from_dotenv(str(repo_root / ".env"))
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve ARMS RUM exception stack.")
    parser.add_argument("--pid", required=True, help="RUM app id")
    parser.add_argument("--line", required=True, type=int, help="Source line number")
    parser.add_argument("--column", required=True, type=int, help="Source column number")
    parser.add_argument("--sourcemap-type", default="js")
    parser.add_argument("--exception-binary-images")
    args = parser.parse_args()

    service = _build_monitoring_service()
    result = service.arms_resolve_exception_stack(
        pid=args.pid,
        line=args.line,
        column=args.column,
        sourcemap_type=args.sourcemap_type,
        exception_binary_images=args.exception_binary_images,
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["exception_stack"] = f"{args.line},{args.column},20"
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
