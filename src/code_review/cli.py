"""代码审查命令行入口（Stage 1 / Stage 2）。

CLI 只负责参数解析、调用 ``ReviewService`` 与展示结果，不实现任何审查业务
逻辑。默认走 Stage 2 多 Agent 工作流；``--json`` 输出机器可读摘要（不包含
日志、密钥或宿主机绝对路径）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from code_review.services.review_service import (
    ReviewOutcome,
    ReviewRequest,
    ReviewService,
    ReviewServiceError,
)
from config.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code_review.cli",
        description="代码审查 CLI（阶段 2 默认多 Agent 工作流）。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    review_parser = subparsers.add_parser(
        "review",
        help="审查一个 GitHub 仓库",
        description=(
            "获取 GitHub 仓库、固定 Commit SHA 并在进程内执行多 Agent "
            "审查，生成五件报告产物。"
        ),
    )
    review_parser.add_argument(
        "repository_url",
        help="GitHub 仓库 URL，例如 https://github.com/pallets/itsdangerous",
    )
    review_parser.add_argument(
        "--branch",
        default=None,
        help="目标分支（可选）",
    )
    review_parser.add_argument(
        "--commit-sha",
        default=None,
        help="目标完整 40 位 Commit SHA（可选；与 --branch 同时提供时以 SHA 为准）",
    )
    review_parser.add_argument(
        "--output-dir",
        default=None,
        help="报告输出根目录（默认读取 REVIEW_OUTPUT_ROOT，缺省为 reports）",
    )
    review_parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出执行摘要",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "review":
        parser.error("a command is required")

    settings = Settings()
    service = ReviewService(settings)
    try:
        outcome = service.review(
            ReviewRequest(
                repository_url=args.repository_url,
                branch=args.branch,
                commit_sha=args.commit_sha,
                output_root=args.output_dir,
            )
        )
    except ReviewServiceError as exc:
        _print_error(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI 不输出 traceback 或敏感信息
        print(f"error: review failed unexpectedly ({type(exc).__name__})", file=sys.stderr)
        return 1
    finally:
        service.close()

    if args.json:
        print(json.dumps(_outcome_payload(outcome), ensure_ascii=False, indent=2))
    else:
        _print_human(outcome)
    return 0


def _outcome_payload(outcome: ReviewOutcome) -> dict[str, object]:
    return {
        "review_id": outcome.review_id,
        "review_stage": outcome.review_stage,
        "review_status": outcome.review_status,
        "overall_verdict": outcome.overall_verdict,
        "overall_score": outcome.overall_score,
        "dimension_scores": dict(outcome.dimension_scores),
        "repository_name": outcome.repository_name,
        "commit_sha": outcome.commit_sha,
        "report_dir": str(outcome.report_dir),
        "report_json_path": (
            str(outcome.report_json_path)
            if outcome.report_json_path is not None
            else None
        ),
        "artifacts": [str(path) for path in outcome.artifact_paths],
        "finding_count": outcome.finding_count,
        "severity_counts": outcome.severity_counts,
        "test_status": outcome.test_status,
        "llm_status": outcome.llm_status,
        "warnings": list(outcome.warnings),
        "duration_seconds": outcome.duration_seconds,
    }


def _print_human(outcome: ReviewOutcome) -> None:
    if outcome.review_stage == "stage_2":
        print("阶段 2 审查完成")
    else:
        print("阶段 1 审查完成")
    print(f"review_id      : {outcome.review_id}")
    print(f"审查状态       : {outcome.review_status}")
    print(f"仓库           : {outcome.repository_name}")
    print(f"Commit SHA     : {outcome.commit_sha or '未提供（可信 Fixture）'}")
    if outcome.overall_verdict is not None:
        print(f"审查结论       : {outcome.overall_verdict}")
    if outcome.overall_score is not None:
        print(f"综合分         : {outcome.overall_score:.1f}")
    if outcome.dimension_scores:
        print(
            "维度评分       : "
            + ", ".join(
                f"{name}="
                + ("N/A" if score is None else f"{score:.1f}")
                for name, score in outcome.dimension_scores.items()
            )
        )
    print(f"Finding 数量   : {outcome.finding_count}")
    if outcome.severity_counts:
        print(
            "严重度分布     : "
            + ", ".join(
                f"{key}={value}"
                for key, value in sorted(outcome.severity_counts.items())
            )
        )
    print(f"测试状态       : {outcome.test_status}")
    print(f"LLM 分析状态   : {outcome.llm_status}")
    print(f"耗时           : {outcome.duration_seconds:.2f} 秒")
    print(f"报告目录       : {outcome.report_dir}")
    for path in outcome.artifact_paths:
        print(f"  - {path.name}")
    if outcome.warnings:
        print("警告：")
        for warning in outcome.warnings:
            print(f"  - {warning}")


def _print_error(exc: ReviewServiceError) -> None:
    prefix = f"error[{exc.stage}]"
    message = f"{prefix}: {exc}"
    if exc.review_id:
        message += f" (review_id={exc.review_id})"
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
