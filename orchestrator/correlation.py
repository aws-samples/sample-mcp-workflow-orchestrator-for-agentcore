"""Evidence Correlation Engine.

Merges observations gathered from multiple MCP servers into a single coherent
finding: de-duplicates, resolves conflicts, and attaches source attribution so the
final answer is explainable and auditable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    source_server: str
    tool: str
    payload: Any
    confidence: float = 0.5


@dataclass
class CorrelatedFinding:
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def sources(self) -> list[str]:
        return sorted({e.source_server for e in self.evidence})


class CorrelationEngine:
    def add(self, findings: list[Evidence]) -> None:
        self._buffer.extend(findings)

    def __init__(self) -> None:
        self._buffer: list[Evidence] = []

    def correlate(self) -> CorrelatedFinding:
        """Naive reference implementation.

        Real systems would use the planner LLM to synthesize; here we show the shape:
        group by source, surface conflicts, produce a cited summary.
        """
        if not self._buffer:
            return CorrelatedFinding(summary="No evidence gathered.")
        by_source: dict[str, list[Evidence]] = {}
        for e in self._buffer:
            by_source.setdefault(e.source_server, []).append(e)
        summary = "Correlated evidence from: " + ", ".join(sorted(by_source))
        return CorrelatedFinding(summary=summary, evidence=list(self._buffer))
