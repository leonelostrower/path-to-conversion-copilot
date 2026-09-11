"""
The orchestrator.

Runs the three agents in order and reports progress as it goes:

    1. mapping_agent    Gemini infers the campaign/site taxonomy
       (the user approves or edits it)
    2. analysis_agent   deterministic metrics and charts -> ReportSpec
    3. narrative_agent  Gemini rewrites the prose and writes the conclusions,
       both grounded in those numbers

Mapping is split out from stages 2-3 because the user gets to approve the
taxonomy in between: a wrong channel assignment would silently distort every
number downstream, and it is far cheaper to fix it before the analysis runs than
to explain a wrong report afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from docx_builder import build_docx
from report_core import AnalysisResult, ExportInfo, Taxonomy, output_paths
from report_spec import ReportSpec

from . import analysis_agent, mapping_agent, narrative_agent
from .gemini_client import GeminiClient
from .mapping_agent import MappingResult
from .narrative_agent import NarrativeResult

Progress = Callable[[str, str], None]
"""Called as progress(stage, message); stage is 'mapping' | 'analysis' | 'narrative'."""


@dataclass
class ReportRun:
    """Everything the final screen needs."""
    spec: ReportSpec
    analysis: AnalysisResult
    narrative: NarrativeResult
    docx_path: str
    taxonomy: Taxonomy
    warnings: list[str] = field(default_factory=list)

    @property
    def metrics(self):
        return self.analysis.metrics


def run_mapping(info: ExportInfo, client_name: str, client: GeminiClient | None,
                context: str = '',
                progress: Progress | None = None) -> MappingResult:
    """Stage 1 on its own, so the UI can show the taxonomy for approval."""
    say = progress or (lambda _s, _m: None)
    say('mapping', 'Reading campaigns and sites from the export')
    result = mapping_agent.run(info, client_name, client, context)
    source = 'Gemini' if result.source == 'gemini' else 'naming patterns'
    say('mapping', f'Taxonomy ready from {source}: '
                   f'{len(result.taxonomy.channel_map)} campaigns, '
                   f'{len(result.taxonomy.platform_map)} sites')
    return result


def run_report(info: ExportInfo, tax: Taxonomy, client_name: str, subtitle: str,
               client: GeminiClient | None, context: str = '',
               style: str = narrative_agent.DEFAULT_STYLE,
               steady_state_start: pd.Timestamp | None = None,
               trim_rampup: bool = True,
               rewrite_narrative: bool = True,
               progress: Progress | None = None) -> ReportRun:
    """Stages 2 and 3, plus the .docx render, against an approved taxonomy."""
    say = progress or (lambda _s, _m: None)

    say('analysis', 'Running the deterministic pipeline')
    analysis_result = analysis_agent.run(
        info, tax, client_name=client_name, subtitle=subtitle, context=context,
        steady_state_start=steady_state_start, trim_rampup=trim_rampup,
        progress=lambda msg: say('analysis', msg),
    )
    spec = analysis_result.spec
    analysis = analysis_result.analysis

    if rewrite_narrative and client is not None:
        say('narrative', 'Rewriting the narrative with Gemini')
        narrative = narrative_agent.run(
            spec, client, analysis=analysis, style=style,
            progress=lambda msg: say('narrative', msg))
        say('narrative',
            f'{narrative.n_rewritten} sections rewritten'
            + (f', {narrative.n_generated} written from the full report'
               if narrative.n_generated else '')
            + (f', {narrative.n_failed} kept verified wording' if narrative.n_failed else ''))
    else:
        narrative = narrative_agent.run(spec, None)
        say('narrative', 'Narrative rewriting skipped; using the verified baseline')

    say('narrative', 'Building the Word document')
    _, docx_path = output_paths(analysis.metrics.date_min, analysis.metrics.date_max)
    build_docx(spec, docx_path)

    return ReportRun(spec=spec, analysis=analysis, narrative=narrative,
                     docx_path=docx_path, taxonomy=tax,
                     warnings=list(analysis.warnings))
