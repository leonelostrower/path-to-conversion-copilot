"""
Agent 2 — Analysis.

Deliberately contains no LLM call. Every number and every chart in the report is
produced by the deterministic pipeline in report_core, so the report's arithmetic
is reproducible and auditable; the language models only handle naming (Agent 1)
and wording (Agent 3).

Its job is to run that pipeline against the approved taxonomy and hand back a
ReportSpec whose prose is the deterministic baseline, ready for Agent 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from report_core import AnalysisResult, ExportInfo, Taxonomy, run_analysis
from report_spec import ReportSpec, build_spec


@dataclass
class AnalysisAgentResult:
    analysis: AnalysisResult
    spec: ReportSpec


def run(info: ExportInfo, tax: Taxonomy, client_name: str, subtitle: str,
        context: str = '', steady_state_start: pd.Timestamp | None = None,
        trim_rampup: bool = True,
        progress: Callable[[str], None] | None = None) -> AnalysisAgentResult:
    analysis = run_analysis(
        info.path, tax, header_row=info.header_row,
        steady_state_start=steady_state_start, trim_rampup=trim_rampup,
        progress=progress,
    )
    spec = build_spec(analysis, client_name=client_name, subtitle=subtitle,
                      context=context)
    return AnalysisAgentResult(analysis=analysis, spec=spec)
