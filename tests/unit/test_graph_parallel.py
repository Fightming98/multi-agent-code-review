"""Stage 2.3 并行执行证明：固定延迟 Fake Agent（AC-2-03 / TC-2-03）。

测试不使用毫秒级绝对阈值：四个 Worker 的固定延迟为 0.30～0.36 秒，
断言四个时间窗口存在公共重叠区间，且图总耗时小于串行耗时之和的 0.75 倍。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from code_review.graph import build_review_graph
from tests.stage2_helpers import make_graph_dependencies, make_review_state

DELAYS: dict[str, float] = {
    "security": 0.30,
    "quality": 0.32,
    "performance": 0.34,
    "testing": 0.36,
}

AGENT_BY_DIMENSION: dict[str, str] = {
    "security": "SecurityAgent",
    "quality": "QualityAgent",
    "performance": "PerformanceAgent",
    "testing": "TestingAgent",
}

# Windows 的事件循环计时器可能比请求的延迟略早唤醒（实测偏差约 5ms），
# 因此对单个 Worker 的耗时只断言宽松下界，不做毫秒级绝对断言。
MIN_EXPECTED_DURATION = 0.25
SLOWEST_LOWER_BOUND = 0.35


def run_timed(
    tmp_path: Path,
    delays: dict[str, float],
) -> tuple[dict, float]:
    graph = build_review_graph(make_graph_dependencies(delays=delays))
    state = make_review_state(tmp_path.resolve())
    started = time.perf_counter()
    output = asyncio.run(graph.ainvoke(state))
    return output, time.perf_counter() - started


def test_four_worker_windows_overlap_and_beat_serial_sum(
    tmp_path: Path,
) -> None:
    output, elapsed = run_timed(tmp_path, DELAYS)
    timings = output["worker_timings"]

    assert len(timings) == 4
    assert {timing.agent_name for timing in timings} == set(
        AGENT_BY_DIMENSION.values()
    )
    assert all(
        output["agent_results"][dimension].status == "completed"
        for dimension in DELAYS
    )

    serial_sum = sum(timing.duration_seconds for timing in timings)
    # 每个窗口都真实等待了固定延迟；Windows 计时器可能略微提前唤醒，
    # 因此使用宽松下界，不做毫秒级绝对断言。
    assert serial_sum >= 4 * MIN_EXPECTED_DURATION
    for timing in timings:
        assert timing.duration_seconds >= MIN_EXPECTED_DURATION

    latest_start = max(timing.started_at for timing in timings)
    earliest_finish = min(timing.finished_at for timing in timings)
    assert latest_start < earliest_finish, (
        "four worker windows do not overlap"
    )

    assert elapsed < 0.75 * serial_sum, (
        f"graph took {elapsed:.3f}s against serial sum {serial_sum:.3f}s"
    )


def test_fan_in_waits_for_the_slowest_worker(tmp_path: Path) -> None:
    delays = {
        "security": 0.05,
        "quality": 0.05,
        "performance": 0.05,
        "testing": 0.40,
    }
    output, _elapsed = run_timed(tmp_path, delays)

    timings = output["worker_timings"]
    testing_timing = next(
        timing
        for timing in timings
        if timing.agent_name == "TestingAgent"
    )
    assert testing_timing.duration_seconds >= SLOWEST_LOWER_BOUND
    assert testing_timing.finished_at == max(
        timing.finished_at for timing in timings
    )

    # Fan-in 必须等到最慢的 Testing Worker 完成；否则该维度会被 Manager
    # 合成为 failed，而不是真实的 completed 结果。
    assert output["agent_results"]["testing"].status == "completed"
    assert output["execution_summary"].completed_tasks == 4
    assert output["execution_summary"].failed_tasks == 0
    assert (
        output["execution_summary"].duration_seconds >= SLOWEST_LOWER_BOUND
    )
    assert output["review_statistics"]["aggregated_dimensions"] == sorted(
        delays
    )
