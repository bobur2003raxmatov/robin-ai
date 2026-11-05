"""Task Planner: splits a big goal into steps with dependencies (independent steps run in parallel)."""
from __future__ import annotations

from backend.ai import prompts
from backend.ai.brain import Brain


async def make_plan(brain: Brain, goal: str, context: str = "") -> dict:
    text = f"VAZIFA:\n{goal}\n\nKONTEKST:\n{context[:4000]}" if context else f"VAZIFA:\n{goal}"
    try:
        plan = await brain.ask_json(prompts.PLANNER_PROMPT, text, fast=False, max_tokens=2000)
    except Exception:
        plan = {}
    steps = plan.get("steps") or []
    clean = []
    for i, s in enumerate(steps[:8], 1):
        clean.append({"id": int(s.get("id", i)), "agent": s.get("agent") if s.get("agent") in prompts.SPECIALISTS
                      else "assistant", "action": str(s.get("action", ""))[:1500],
                      "expected": str(s.get("expected", ""))[:500],
                      "depends_on": [int(d) for d in s.get("depends_on", []) if str(d).isdigit()],
                      "status": "pending"})
    if not clean:
        clean = [{"id": 1, "agent": "assistant", "action": goal, "expected": "Vazifa bajarilgan", "depends_on": [],
                  "status": "pending"}]
    return {"title": plan.get("title") or goal[:80], "steps": clean,
            "deliverable": plan.get("deliverable", "Natija va qisqa izoh")}


def ready_steps(steps: list[dict]) -> list[dict]:
    done = {s["id"] for s in steps if s["status"] == "done"}
    return [s for s in steps if s["status"] == "pending" and all(d in done for d in s["depends_on"])]
