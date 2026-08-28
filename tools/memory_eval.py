"""Run a deterministic, isolated replay of the feedback-memory loop.

The report is suitable for local verification or as a starting point for a
real-user evidence sheet. It never touches the production database and never
calls an upstream model.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import DemoEngine


def run_replay() -> dict[str, Any]:
    """Return measurable checks for one feedback-memory replay."""
    with tempfile.TemporaryDirectory(prefix="lingxi-memory-eval-") as temp_dir:
        engine = DemoEngine(Path(temp_dir) / "eval.db")
        device_id = "memory-eval-device"
        profile = engine.get_profile(device_id)

        baseline_text = "请帮我制定一个晚上两小时的复习计划，给出步骤和理由"
        baseline_started = time.perf_counter()
        baseline_memories = engine.search_feedback_memories(device_id, baseline_text)
        baseline_latency_ms = round((time.perf_counter() - baseline_started) * 1000, 2)

        interaction_id = engine.record_interaction(
            device_id,
            "assistant",
            baseline_text,
            "先列出科目，再安排每一科的复习时间。",
        )
        feedback = engine.record_feedback(
            device_id,
            interaction_id,
            -1,
            "复习计划先列重点科目",
        )
        rule = str(feedback["memory"]["rule"])

        similar_text = "请帮我制定明晚两小时的高数复习计划"
        recall_started = time.perf_counter()
        similar_memories = engine.search_feedback_memories(device_id, similar_text)
        recall_latency_ms = round((time.perf_counter() - recall_started) * 1000, 2)
        similar_prompt = engine.build_stepfun_messages(
            device_id,
            similar_text,
            "assistant",
            profile,
            feedback_memories=similar_memories,
        )

        unrelated_text = "明天天气如何"
        unrelated_memories = engine.search_feedback_memories(device_id, unrelated_text)
        metrics = engine.memory_metrics(device_id)
        prompt_text = str(similar_prompt[0].get("content", ""))

        checks = {
            "baseline_has_no_hit": not baseline_memories,
            "similar_task_recalled": any(item["rule"] == rule for item in similar_memories),
            "unrelated_task_not_recalled": not unrelated_memories,
            "rule_entered_model_prompt": rule in prompt_text,
            "recall_counter_incremented": metrics["recall_uses"] == 1,
        }
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "baseline": {
                "hits": len(baseline_memories),
                "latency_ms": baseline_latency_ms,
            },
            "similar_task": {
                "hits": len(similar_memories),
                "rules": [item["rule"] for item in similar_memories],
                "estimated_tokens": sum(
                    int(item["estimated_tokens"]) for item in similar_memories
                ),
                "latency_ms": recall_latency_ms,
            },
            "unrelated_task": {"hits": len(unrelated_memories)},
            "metrics": metrics,
        }


def main() -> int:
    report = run_replay()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
