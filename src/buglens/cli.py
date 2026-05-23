from __future__ import annotations

import asyncio
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .agent import SubAgent
from .config import bootstrap_process_env_from_dotenv
from .models import InvokeRequest
from .rpc import build_error, dispatch_request
from .skills import export_skill

logger = logging.getLogger(__name__)


def _write_json(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    # Keep transport logs quiet so REPL/invoke diagnostics stay readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _run_stdio_loop() -> int:
    agent = SubAgent()
    while True:
        raw_line = sys.stdin.readline()
        if not raw_line:
            break
        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_json(
                build_error(
                    request_id=None,
                    code=-32700,
                    message="Parse error",
                    data={"detail": str(exc)},
                )
            )
            continue

        if not isinstance(payload, dict):
            _write_json(build_error(None, -32600, "Invalid Request"))
            continue

        response = await dispatch_request(agent, payload)
        if response is not None:
            _write_json(response)

    return 0


async def _run_invoke_once(
    task: str,
    context: dict[str, Any],
    mock_response: str | None,
    stream: bool,
) -> int:
    agent = SubAgent()
    init_overrides = {"mock_response": mock_response} if mock_response is not None else {}
    logger.info("invoke mode initialize")
    await agent.initialize(init_overrides)
    logger.info("invoke started task_length=%s stream=%s", len(task), stream)
    started_at = time.monotonic()
    streamed_chars = 0

    def _on_text(text: str) -> None:
        nonlocal streamed_chars
        streamed_chars += len(text)
        sys.stdout.write(text)
        sys.stdout.flush()

    try:
        response = await agent.invoke(
            InvokeRequest(task=task, context=context),
            on_text=_on_text if stream else None,
        )
        if stream:
            if streamed_chars == 0:
                print(response.output)
            elif not response.output.endswith("\n"):
                print()
        else:
            print(response.output)
        logger.info(
            "invoke finished duration_ms=%d streamed_chars=%d",
            int((time.monotonic() - started_at) * 1000),
            streamed_chars,
        )
        return 0
    except Exception as exc:
        if logger.isEnabledFor(logging.DEBUG):
            logger.exception("invoke failed")
        else:
            logger.error("invoke failed: %s", exc)
        print(f"invoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        logger.info("invoke mode shutdown")
        await agent.shutdown()


async def _run_repl(mock_response: str | None, stream: bool) -> int:
    agent = SubAgent()
    init_overrides = {"mock_response": mock_response} if mock_response is not None else {}
    logger.info("repl initialize stream=%s", stream)
    await agent.initialize(init_overrides)
    print("buglens repl commands: health | invoke <text> | shutdown")
    print("tip: type plain text directly to invoke (same as: invoke <text>)")
    while True:
        try:
            line = input("buglens> ").strip()
        except EOFError:
            print(json.dumps(await agent.shutdown(), ensure_ascii=False))
            return 0
        if not line:
            continue
        if line == "health":
            print(json.dumps(await agent.health(), ensure_ascii=False))
            continue

        if line in {"help", "?"}:
            print("commands: health | invoke <text> | shutdown")
            print("tip: plain text triggers invoke directly")
            continue

        if line in {"shutdown", "exit", "quit"}:
            print(json.dumps(await agent.shutdown(), ensure_ascii=False))
            return 0

        task: str | None = None
        if line.startswith("invoke "):
            task = line[len("invoke ") :].strip()
        elif line == "invoke":
            task = ""
        else:
            task = line

        if task is not None:
            if not task:
                print("missing task text")
                continue
            print("invoking...")
            logger.info("repl invoke started task_length=%s", len(task))
            started_at = time.monotonic()
            streamed_chars = 0

            def _on_text(text: str) -> None:
                nonlocal streamed_chars
                streamed_chars += len(text)
                sys.stdout.write(text)
                sys.stdout.flush()

            try:
                result = await agent.invoke(
                    InvokeRequest(task=task),
                    on_text=_on_text if stream else None,
                )
                if stream:
                    if streamed_chars == 0:
                        print(result.output)
                    elif not result.output.endswith("\n"):
                        print()
                else:
                    print(result.output)
                logger.info(
                    "repl invoke finished duration_ms=%d streamed_chars=%d",
                    int((time.monotonic() - started_at) * 1000),
                    streamed_chars,
                )
            except Exception as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.exception("repl invoke failed")
                else:
                    logger.error("repl invoke failed: %s", exc)
                print(f"invoke failed: {exc}")
            continue

        print("unknown command")


def main() -> None:
    bootstrap_process_env_from_dotenv()
    parser = argparse.ArgumentParser(description="buglens agent runtime")
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging level (logs write to stderr)",
    )
    sub = parser.add_subparsers(dest="mode")

    invoke_parser = sub.add_parser("invoke", help="one-shot invoke for quick debugging")
    invoke_parser.add_argument("--task", required=True, help="task content")
    invoke_parser.add_argument(
        "--context-json",
        default="{}",
        help='context JSON object, e.g. \'{"ticket":"123"}\'',
    )
    invoke_parser.add_argument("--mock-response", default=None)
    invoke_parser.add_argument(
        "--stream",
        action="store_true",
        help="stream assistant text to stdout while invoking",
    )

    repl_parser = sub.add_parser("repl", help="interactive debug shell")
    repl_parser.add_argument("--mock-response", default=None)
    repl_parser.add_argument(
        "--stream",
        action="store_true",
        help="stream assistant text output in REPL invoke",
    )

    skills_parser = sub.add_parser("skills", help="skill packaging helpers")
    skills_sub = skills_parser.add_subparsers(dest="skills_mode")
    skills_export_parser = skills_sub.add_parser(
        "export",
        help="export packaged skill templates for local distribution",
    )
    skills_export_parser.add_argument(
        "--output",
        default="./dist/openclaw-skills",
        help="target directory for exported buglens skill",
    )
    skills_export_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing target skill directories",
    )

    args = parser.parse_args()
    _configure_logging(args.log_level)
    if args.mode == "invoke":
        try:
            context = json.loads(args.context_json)
            if not isinstance(context, dict):
                raise ValueError("context must be a JSON object")
        except Exception as exc:
            raise SystemExit(f"invalid --context-json: {exc}") from exc
        raise SystemExit(
            asyncio.run(
                _run_invoke_once(args.task, context, args.mock_response, args.stream)
            )
        )
    if args.mode == "repl":
        raise SystemExit(asyncio.run(_run_repl(args.mock_response, args.stream)))
    if args.mode == "skills":
        if args.skills_mode != "export":
            raise SystemExit("missing skills subcommand, expected: export")
        try:
            result = export_skill(
                output_dir=Path(args.output),
                overwrite=args.overwrite,
            )
        except Exception as exc:
            raise SystemExit(f"skills export failed: {exc}") from exc

        print(f"exported skill: {result.exported_skill}")
        print(f"output dir: {result.output_dir}")
        print(f"openclaw skills install {result.output_dir / result.exported_skill}")
        raise SystemExit(0)
    raise SystemExit(asyncio.run(_run_stdio_loop()))


if __name__ == "__main__":
    main()
