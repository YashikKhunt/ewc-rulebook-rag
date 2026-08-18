"""Record types for the benchmark.

Two of them, and one rule.

``Measurement`` carries a mandatory ``basis`` — a sentence saying what the number
is computed over. A ``Measurement`` whose ``basis`` is empty **refuses to render
and refuses to serialise**. It may exist in memory (so a half-built metric is a
value you can inspect, not an exception at the wrong moment), but it cannot reach
``summary.json``, ``details.json`` or the console.

That refusal is the point. The ground truth here is 30 positive-only, partial
``must_include`` labels. ``P@8 = 0.19`` computed from them is not a score, it is
30 labels divided by 224 retrieved slots — a labelling artefact that reads as a
measurement of the system. Forcing every number to state its own denominator is
the structural defence against reporting that as if it meant something.

``QueryRecord`` is one query's full trace through the instrumented pipeline. It
deliberately does NOT reuse ``eval/run.py``'s ``Result``: a gate is boolean by
design, and the moment a score lives in the gate's record type someone writes a
must_pass as ``score >= threshold`` — and thresholds are tunable in a way
``all(passed_runs)`` is not.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


class MissingBasis(ValueError):
    """Raised when a Measurement without a basis is asked to render."""


@dataclass
class Measurement:
    """One number, plus everything needed to read it honestly.

    ``value``    the headline figure (the mean when ``per_run`` has more than one
                 entry; the single observation when it has one).
    ``per_run``  every observation behind ``value``. Never summarised away.
    ``n``        len(per_run), stored explicitly so a deserialised record still
                 knows whether it has a variance estimate.
    ``unit``     "ratio" | "count" | "seconds" | "usd" | "probability" | ...
    ``basis``    MANDATORY. What the number is computed over, including what the
                 denominator is and what is NOT counted.
    """

    name: str
    value: float | None
    per_run: list[float] = field(default_factory=list)
    n: int = 0
    unit: str = ""
    basis: str = ""

    def __post_init__(self) -> None:
        if self.n == 0 and self.per_run:
            self.n = len(self.per_run)
        if self.value is None and self.per_run:
            self.value = statistics.fmean(self.per_run)

    # -- the guard ---------------------------------------------------------

    def _require_basis(self) -> None:
        if not (self.basis or "").strip():
            raise MissingBasis(
                f"Measurement {self.name!r} has no basis. A number without a "
                "statement of what it is computed over is not a measurement. "
                "Set `basis` to name the denominator and what is excluded from it."
            )

    @property
    def stdev(self) -> float | None:
        """Sample stdev, or None when a single observation gives no estimate."""
        if self.n < 2:
            return None
        return statistics.stdev(self.per_run)

    def _format(self, number: float) -> str:
        if self.unit == "seconds":
            return f"{number:.4f}s"
        if self.unit == "usd":
            return f"${number:.6f}"
        if self.unit == "count":
            return f"{number:g}"
        return f"{number:.4f}"

    def render(self) -> str:
        """``0.71 ± 0.09 (n=3)`` / ``0.71 (n=1, no variance estimate)``.

        The stdev is formatted in the SAME unit as the value. A dollar figure
        whose spread prints as a bare `0.0001` reads as a ratio."""
        self._require_basis()
        body = "n/a" if self.value is None else self._format(self.value)
        sd = self.stdev
        if sd is not None:
            body += f" ± {self._format(sd)} (n={self.n})"
        elif self.n == 1:
            body += " (n=1, no variance estimate)"
        elif self.n == 0:
            body += " (n=0)"
        else:
            body += f" (n={self.n})"
        return body

    def to_dict(self) -> dict[str, Any]:
        self._require_basis()
        return {
            "name": self.name,
            "value": self.value,
            "per_run": list(self.per_run),
            "n": self.n,
            "stdev": self.stdev,
            "unit": self.unit,
            "basis": self.basis,
            "rendered": self.render(),
        }


@dataclass
class QueryRecord:
    """One query's trace through the instrumented node driver.

    ``docs``   is the AUTHORITY-ordered pool `graph.hybrid` returns, flattened to
               the metadata the metrics need. Position in this list is NOT the
               relevance rank.
    ``ranks``  chunk_id -> fused RELEVANCE rank, pre-authority-sort. Every
               rank-based metric reads this, never ``enumerate(docs)``.
    """

    case_id: str
    bucket: str
    question: str
    game: str | None = None            # scope actually searched
    routed: Any = "(forced)"           # router output, or "(forced)" when skipped
    route_branch: str = ""             # "forced" | "router" | "not_called"
    docs: list[dict] = field(default_factory=list)
    ranks: dict[str, int] = field(default_factory=dict)
    scope: str = ""
    conflicts: list[dict] = field(default_factory=list)
    note: str = ""
    accountable: list[str] = field(default_factory=list)
    top_findings: list[str] = field(default_factory=list)
    outcome: str = ""                  # generation tier only
    answer: str = ""                   # generation tier only
    citation_spans: list[dict] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)
    timings: dict[str, float | None] = field(default_factory=dict)
    cost_usd: float = 0.0
    error: str = ""

    @property
    def chunk_ids(self) -> list[str]:
        return [d["chunk_id"] for d in self.docs]

    def rank_of(self, chunk_id: str) -> int | None:
        """Relevance rank (1-based) or None. The only sanctioned way to ask."""
        return self.ranks.get(chunk_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "bucket": self.bucket,
            "question": self.question, "game": self.game, "routed": self.routed,
            "route_branch": self.route_branch,
            "docs": self.docs, "ranks": self.ranks, "scope": self.scope,
            "conflicts": self.conflicts, "note": self.note,
            "accountable": self.accountable, "top_findings": self.top_findings,
            "outcome": self.outcome, "answer": self.answer,
            "citation_spans": self.citation_spans, "usage": self.usage,
            "timings": self.timings, "cost_usd": self.cost_usd,
            "error": self.error,
        }
