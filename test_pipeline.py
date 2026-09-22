"""End-to-end check of the three-agent pipeline against the real RDC export."""

import sys
import time

from pypdf import PdfReader

import report_core as rc
from agents import orchestrator
from agents.gemini_client import GeminiClient
from agents.narrative_agent import allowed_numbers, find_violations, report_numbers
from report_spec import build_digest

CSV = '2026-08-17_path_to_conversion_2751751_RDC (1).csv'
CONTEXT = """\
Rates.ca is a Canadian rate-comparison marketplace for insurance and mortgages.
The 2026 mid-funnel test put Reddit, StackAdapt, Facebook and TikTok in market to
build consideration ahead of high-intent search. The client's open question for
this QBR is whether mid-funnel spend is defensible or whether budget should move
back into paid search. The team cares most about auto insurance leads.
"""


def _pdf_lines(path: str) -> list[str]:
    reader = PdfReader(path)
    lines = []
    for page in reader.pages:
        text = page.extract_text() or ''
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def audit_pdf(run) -> int:
    """Re-read the finished PDF and confirm every number in its prose traces
    back to the deterministic pipeline.

    This checks the artifact the client actually receives, rather than trusting
    that the in-memory validation was applied correctly on the way out.
    """
    # Only agent-written prose is audited. The cover block precedes the first
    # heading and is rendered straight from the spec, so it is skipped.
    # A generated section reasons across the whole report, so it is audited
    # against every figure the report computed rather than its own facts.
    wide = report_numbers(run.spec, build_digest(run.spec, run.analysis))
    allowed_by_heading = {
        s.heading: (wide if s.mode == 'generate' else allowed_numbers(s))
        for s in run.spec.sections}

    current = None
    checked = 0
    bad = 0
    lines = _pdf_lines(run.pdf_path)
    i = 0
    # Headings can wrap across lines in the PDF, so match the longest join of
    # consecutive lines that equals a section heading before treating text as prose.
    while i < len(lines):
        matched = None
        max_span = min(4, len(lines) - i)
        for span in range(max_span, 0, -1):
            joined = ' '.join(lines[i:i + span])
            if joined in allowed_by_heading:
                matched = (joined, span)
                break
        if matched:
            current, span = matched
            i += span
            continue
        text = lines[i]
        i += 1
        allowed = allowed_by_heading.get(current)
        if allowed is None:
            continue
        checked += 1
        if (violations := find_violations(text, allowed)):
            bad += 1
            print(f'  UNVERIFIED in "{current}": {violations}')
            print(f'    {text[:160]}')

    print(f'  checked {checked} prose lines in the PDF, {bad} with unverified figures')
    return bad


def main():
    started = time.time()
    print('== Inspecting export ==')
    info = rc.inspect_export(CSV)
    print(f'  {info.n_rows:,} rows, {info.n_slots} slots, header row {info.header_row}')
    print(f'  campaigns: {info.campaigns}')
    print(f'  sites: {info.sites}')

    client = GeminiClient.create()
    print(f'\n== Gemini connectivity ==\n  answered by: {client.check()}')

    def progress(stage, msg):
        print(f'  [{stage}] {msg}')

    print('\n== Agent 1: mapping ==')
    mapping = orchestrator.run_mapping(info, 'Rates.ca', client, CONTEXT, progress)
    tax = mapping.taxonomy
    print(f'  source: {mapping.source}')
    print(f'  channel_map: {tax.channel_map}')
    print(f'  platform_map: {tax.platform_map}')
    print(f'  search: {tax.search_platforms}')
    print(f'  mid-funnel: {tax.mid_funnel_platforms}')
    print(f'  notes: {mapping.notes}')
    for w in mapping.warnings:
        print(f'  WARNING: {w}')

    print('\n== Agents 2 + 3: analysis and narrative ==')
    run = orchestrator.run_report(
        info, tax, client_name='Rates.ca',
        subtitle='2026 Q3: Quarterly Business Review',
        client=client, context=CONTEXT, progress=progress)

    print('\n== Narrative outcomes ==')
    for o in run.narrative.outcomes:
        line = f'  {o.status:10s} {o.heading}'
        if o.detail:
            line += f'  -- {o.detail}'
        print(line)

    print('\n== Rewritten Summary section ==')
    for block in run.spec.section('summary').blocks:
        if hasattr(block, 'text'):
            print(f'\n  PROSE: {block.text}')
        elif hasattr(block, 'items'):
            for item in block.items:
                print(f'\n  BULLET: {item}')

    print('\n== Generated Conclusions & Recommendations ==')
    conclusions = run.spec.section('conclusions')
    outcome = run.narrative.outcome('conclusions')
    print(f'  status: {conclusions.status}'
          + (f'  -- {conclusions.note}' if conclusions.note else ''))
    if outcome and outcome.verdict:
        print(f'\n  VERDICT: {outcome.verdict}')
    for item in (outcome.conclusions if outcome else []):
        print(f'\n  CONCLUSION: {item}')
    for rec in (outcome.recommendations if outcome else []):
        print(f"\n  [{rec.get('priority')}] {rec.get('action')}")
        print(f"      why: {rec.get('rationale')}")
        for ev in rec.get('evidence') or []:
            print(f"      evidence: {ev}")

    print('\n== Auditing the generated PDF ==')
    bad = audit_pdf(run)

    print(f'\n== Output ==\n  pdf: {run.pdf_path}')
    print(f'  charts: {len(run.analysis.charts)} in {run.analysis.charts_dir}')
    for w in run.warnings:
        print(f'  WARNING: {w}')
    print(f'\n  gemini calls: {len(client.calls)}, '
          f'tokens: {client.total_tokens():,}')
    print(f'  models used: {sorted({c.model for c in client.calls})}')
    print(f'  wall clock: {time.time() - started:.1f}s')

    failures = []
    if bad:
        failures.append('the document contains figures that are not in the '
                        'deterministic facts')
    if conclusions.status != 'generated':
        failures.append('the conclusions section fell back to the caveat bullets '
                        f'(status {conclusions.status})')
    elif not (outcome and outcome.recommendations):
        failures.append('the conclusions section produced no recommendations')

    if failures:
        print('\nFAILED: ' + '; '.join(failures) + '.')
        return 1
    print('\nPASSED: every figure in the document traces back to the pipeline, and '
          'the conclusions were written from the full report.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
