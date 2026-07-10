"""Structured, printable reasoning trace.

The decision log is the heart of the *explainability* differentiator: every planner
step records WHY a server/tool was chosen so the reasoning can be audited or displayed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DecisionStep:
    step: int
    action: str                     # e.g. "select_server", "invoke_tool", "correlate"
    server: str | None
    tool: str | None
    rationale: str                  # human-readable WHY
    inputs: dict[str, Any] = field(default_factory=dict)
    observation_summary: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DecisionLog:
    steps: list[DecisionStep] = field(default_factory=list)

    def record(self, **kwargs: Any) -> DecisionStep:
        step = DecisionStep(step=len(self.steps) + 1, **kwargs)
        self.steps.append(step)
        return step

    def to_markdown(self) -> str:
        lines = ["# Decision Log", ""]
        for s in self.steps:
            lines.append(f"## Step {s.step}: {s.action}")
            if s.server:
                lines.append(f"- **Server:** {s.server}")
            if s.tool:
                lines.append(f"- **Tool:** {s.tool}")
            lines.append(f"- **Why:** {s.rationale}")
            if s.observation_summary:
                lines.append(f"- **Observed:** {s.observation_summary}")
            lines.append("")
        return "\n".join(lines)
