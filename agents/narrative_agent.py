"""
Agent 3 — Narrative.

Rewrites the wording of the report at runtime, when the user clicks Generate. It
never touches generate_report.py, and it never produces a number.

The guarantee that makes an LLM safe to put in front of a client deliverable is
enforced here rather than merely requested in the prompt: every numeric token in
a rewritten passage must already appear in that section's `facts`, its baseline
text, or its tables. A passage that invents or re-rounds a figure is sent back
once with the offending tokens named, and if it still fails, the deterministic
baseline text is kept. So the worst case is the original wording, never a wrong
number.

Conclusions & Recommendations works differently. That section is generated rather
than reworded: it is given a digest of the entire report — every section's
figures, the data behind every chart, the final prose of the other sections, the
analyst's context — and decides for itself what the findings, the caveats and the
next actions are. The one rule that carries over is the arithmetic: it may only
state figures the pipeline computed, checked against the report-wide fact set
instead of one section's.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from report_core import AnalysisResult
from report_spec import Bullets, Prose, ReportSpec, Section, Table, build_digest

from .gemini_client import GeminiClient, GeminiError

SYSTEM_INSTRUCTION = """\
You are a senior performance-media analyst writing the narrative of a \
path-to-conversion report for an advertiser's marketing team.

You rewrite the wording of one section at a time. You are given the section's \
verified figures and its current draft text.

Absolute rules about numbers:
- Every figure you write must be copied character-for-character from the \
supplied facts or the current draft. "14.2%" stays "14.2%", never "14%", \
"0.142" or "about 14 percent".
- Never calculate, combine, re-round or infer a new number. If a figure is not \
supplied, describe the idea in words instead.
- Keep every figure the draft already states. The figures are the substance of \
this report, so reword around them; do not summarise them away or replace them \
with vague quantifiers like "significantly" or "the majority".
- Never introduce a platform, campaign, channel, date or currency that is not \
already present.

Rules about structure:
- Return exactly one entry per block you are given, with the same index.
- A "prose" block must come back as exactly one string: a single flowing \
paragraph.
- A "bullets" block must come back as a list of bullet strings, keeping every \
distinct point from the draft. Keep the count the same unless a merge is clearly \
better, and never drop a point.
- Where the draft opens a bullet with a bold lead-in (**Like this**: ...), keep a \
bold lead-in in the same position.
- Use **double asterisks** for bold. No other markdown, no headings, no bullet \
characters at the start of a bullet string.

Rules about voice:
- Plain, precise, confident business English. No filler, no hype, no \
"delve"/"leverage"/"unlock", no exclamation marks.
- Explain what a figure means for the advertiser's media plan, not just what it \
says.
- Keep the analytical honesty of the draft: where the draft hedges a small \
sample or a directional finding, keep hedging.
"""

NARRATIVE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'blocks': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'index': {'type': 'INTEGER',
                              'description': 'The block index you were given.'},
                    'lines': {
                        'type': 'ARRAY',
                        'items': {'type': 'STRING'},
                        'description': ('One string for a prose block; one string '
                                        'per bullet for a bullets block.'),
                    },
                },
                'required': ['index', 'lines'],
            },
        },
    },
    'required': ['blocks'],
}

GENERATIVE_INSTRUCTION = """\
You are a senior performance-media analyst. You have finished a \
path-to-conversion analysis for an advertiser and you are now writing the \
Conclusions & Recommendations section of the report.

You are given a digest of the whole report: the analysis window, every verified \
figure, the underlying data of every chart, pre-computed comparisons, the prose \
of the other sections, the data-quality flags the data triggered, and whatever \
background the analyst supplied.

This section is yours. Decide what the analysis actually shows, say it plainly, \
and tell this advertiser what to do next. Draw across sections: a finding that \
combines the platform breakdown with the assist lag or the transition flows is \
worth more than a restatement of one table. Caveat where the data deserves it \
and say so in your own words; the data-quality flags are there for you to use or \
ignore on judgement, not to be recited.

The only hard rule is arithmetic:
- Every figure you write must be copied character-for-character from the digest. \
"14.2%" stays "14.2%", never "14%", "0.142" or "about 14 percent".
- Never calculate, combine, re-round or infer a new number. The comparisons \
block already holds the ratios, shares and multiples you are likely to want; if \
a figure you want is genuinely not in the digest, make the point in words.
- Never introduce a platform, campaign, channel, date or currency that is not in \
the digest.

How to write it:
- verdict: one paragraph answering the advertiser's business question head-on. \
State the conclusion first, then the evidence for it. No preamble, no restating \
the brief.
- conclusions: each bullet one finding, with the figures that establish it inside \
the bullet. Open with a short **bold lead-in** followed by a colon. Findings, not \
descriptions of the data.
- recommendations: concrete actions this advertiser could brief next week — \
budget, platform mix, creative sequencing, measurement — each justified by the \
figures. Prioritise honestly: High only for actions the evidence genuinely \
supports. "Keep monitoring" is not a recommendation unless the data really \
supports nothing else. Put the exact figures you relied on in `evidence`.
- Plain, precise, confident business English. No filler, no hype, no \
"delve"/"leverage"/"unlock", no exclamation marks. Use **double asterisks** for \
bold and no other markdown.
"""

GENERATIVE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'verdict': {
            'type': 'STRING',
            'description': 'One paragraph answering the business question head-on.',
        },
        'conclusions': {
            'type': 'ARRAY',
            'items': {'type': 'STRING'},
            'description': 'Findings, 3-6 bullets, each with its evidence inside it.',
        },
        'recommendations': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'action': {'type': 'STRING',
                               'description': 'The action, stated imperatively and briefly.'},
                    'rationale': {'type': 'STRING',
                                  'description': 'Why, citing the figures that support it.'},
                    'evidence': {
                        'type': 'ARRAY',
                        'items': {'type': 'STRING'},
                        'description': ('The figures relied on, copied from the digest, '
                                        'each with what it measures.'),
                    },
                    'priority': {'type': 'STRING', 'enum': ['High', 'Medium', 'Low']},
                },
                'required': ['action', 'rationale', 'evidence', 'priority'],
            },
            'description': '2-5 prioritised actions.',
        },
    },
    'required': ['verdict', 'conclusions', 'recommendations'],
}

STYLES = {
    'Balanced': 'Match the length of the draft. Keep every point.',
    'Executive': ('Tighten noticeably. Lead each passage with the implication for the '
                  'media plan, then the supporting figure.'),
    'Detailed': ('You may expand slightly to explain mechanics and caveats for a reader '
                 'who is new to path-to-conversion data.'),
}
DEFAULT_STYLE = 'Balanced'

# Small integers appear in ordinary phrasing ("a day or more", "position 1",
# "the top 8 journeys") and are not factual claims about the data.
SAFE_NUMBERS = {str(i) for i in range(0, 13)}

NUMBER_RE = re.compile(r'\d[\d,]*(?:\.\d+)?%?')


def _normalize(token: str) -> str:
    return token.replace(',', '')


def _tokens(text: str) -> set[str]:
    return {_normalize(t) for t in NUMBER_RE.findall(text or '')}


def _license_bare_percentages(allowed: set[str]) -> set[str]:
    """A percentage in the facts licenses the bare number too, so "14.2% of paths"
    may legitimately be reworded as "14.2 percent"."""
    for token in list(allowed):
        if token.endswith('%'):
            allowed.add(token[:-1])
    return allowed


def allowed_numbers(section: Section) -> set[str]:
    """Every numeric token the section is allowed to state: its verified facts,
    its current draft, and the cells of its tables."""
    allowed: set[str] = set(SAFE_NUMBERS)

    for value in section.facts.values():
        allowed |= _tokens(str(value))
    allowed |= _tokens(section.baseline_text())

    for block in (section.baseline_blocks or section.blocks):
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row:
                    allowed |= _tokens(str(cell))
            for header in block.headers:
                allowed |= _tokens(str(header))

    return _license_bare_percentages(allowed)


def _walk_strings(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _walk_strings(value)
    elif node is not None:
        yield str(node)


def report_numbers(spec: ReportSpec, digest: dict) -> set[str]:
    """Every numeric token anywhere in the report. A generated section reasons
    across all of it, so a figure verified in one section is verified for it."""
    allowed: set[str] = set(SAFE_NUMBERS)
    for text in _walk_strings(digest):
        allowed |= _tokens(text)
    for section in spec.sections:
        allowed |= allowed_numbers(section)
    return _license_bare_percentages(allowed)


def find_violations(text: str, allowed: set[str]) -> list[str]:
    """Numbers stated in `text` that are not verified by `allowed`."""
    return sorted({t for t in _tokens(text) if t not in allowed})


# A rewrite is allowed to merge or restructure points, but the figures are the
# substance of the report; losing most of them turns analysis into assertion.
MIN_FIGURE_RETENTION = 0.6


def find_dropped_figures(baseline: str, text: str) -> list[str]:
    """Figures the draft stated that the rewrite left out, if it dropped enough of
    them to materially weaken the passage."""
    before = _tokens(baseline) - SAFE_NUMBERS
    if len(before) < 2:
        return []
    missing = before - _tokens(text)
    if len(missing) / len(before) <= (1 - MIN_FIGURE_RETENTION):
        return []
    return sorted(missing)


@dataclass
class SectionOutcome:
    section_id: str
    heading: str
    status: str                  # rewritten | generated | failed | skipped
    detail: str = ''
    violations: list[str] = field(default_factory=list)
    # Only set for generated sections, so the audit view can show the reasoning.
    verdict: str = ''
    conclusions: list[str] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)


@dataclass
class NarrativeResult:
    outcomes: list[SectionOutcome]

    @property
    def n_rewritten(self) -> int:
        return sum(1 for o in self.outcomes if o.status == 'rewritten')

    @property
    def n_generated(self) -> int:
        return sum(1 for o in self.outcomes if o.status == 'generated')

    @property
    def n_failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == 'failed')

    def outcome(self, section_id: str) -> SectionOutcome | None:
        return next((o for o in self.outcomes if o.section_id == section_id), None)


def _describe_blocks(section: Section) -> str:
    lines = []
    for idx, block in section.editable():
        if isinstance(block, Prose):
            lines.append(f"Block {idx} (prose, return exactly 1 string):")
            lines.append(f"  {block.baseline}")
        elif isinstance(block, Bullets):
            lines.append(f"Block {idx} (bullets, return {len(block.baseline)} strings):")
            lines.extend(f"  - {item}" for item in block.baseline)
        lines.append('')
    return '\n'.join(lines)


def build_prompt(spec: ReportSpec, section: Section, style: str,
                 retry_problems: dict[int, dict[str, list[str]]] | None = None) -> str:
    facts = '\n'.join(f"  {k} = {v}" for k, v in section.facts.items()) or '  (none)'

    parts = [
        f"Client / advertiser: {spec.client_name}",
        f"Report: {spec.title} — {spec.subtitle}",
        f"Section: {section.heading}",
        '',
        'Verified figures for this section (the only numbers you may state):',
        facts,
        '',
        f"Style: {STYLES.get(style, STYLES[DEFAULT_STYLE])}",
    ]

    if spec.context.strip():
        parts += [
            '',
            'Background on the client and this campaign, supplied by the analyst. '
            'Use it for framing, terminology and what matters to this advertiser. '
            'It must not override or add to the figures above:',
            spec.context.strip()[:8000],
        ]

    parts += ['', 'Current draft to rewrite:', '', _describe_blocks(section)]

    if retry_problems:
        notes = []
        for idx, problem in sorted(retry_problems.items()):
            if problem.get('invented'):
                notes.append(f"block {idx} stated numbers that are not verified: "
                             f"{', '.join(problem['invented'])}")
            if problem.get('dropped'):
                notes.append(f"block {idx} dropped figures that must be kept: "
                             f"{', '.join(problem['dropped'])}")
        parts += [
            '',
            'Your previous attempt was rejected. ' + '; '.join(notes) + '. '
            'Rewrite again, keeping every figure from the draft and copying each one '
            'exactly as written.',
        ]

    return '\n'.join(parts)


def _apply(section: Section, payload: dict) -> dict[int, str]:
    """Write the model's text onto the section. Returns {index: combined text} for
    validation, and leaves untouched any block the model omitted."""
    editable = dict(section.editable())
    applied: dict[int, str] = {}

    for entry in payload.get('blocks', []):
        try:
            idx = int(entry.get('index'))
        except (TypeError, ValueError):
            continue
        block = editable.get(idx)
        lines = [str(line).strip() for line in entry.get('lines', []) if str(line).strip()]
        if block is None or not lines:
            continue

        if isinstance(block, Prose):
            block.text = ' '.join(lines)
            applied[idx] = block.text
        elif isinstance(block, Bullets):
            block.items = lines
            applied[idx] = '\n'.join(lines)

    return applied


def _rewrite_section(client: GeminiClient, spec: ReportSpec, section: Section,
                     style: str) -> SectionOutcome:
    if not section.editable():
        section.status = 'baseline'
        return SectionOutcome(section.id, section.heading, 'skipped',
                              'No prose to rewrite.')

    allowed = allowed_numbers(section)
    baselines = {idx: (block.baseline if isinstance(block, Prose)
                       else '\n'.join(block.baseline))
                 for idx, block in section.editable()}
    problems: dict[int, dict[str, list[str]]] = {}

    for attempt in (1, 2):
        try:
            payload = client.generate_json(
                build_prompt(spec, section, style,
                             retry_problems=problems if attempt == 2 else None),
                NARRATIVE_SCHEMA,
                label=f'narrative:{section.id}',
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.35,
            )
        except GeminiError as exc:
            section.restore_baseline()
            section.status = 'failed'
            section.note = str(exc)
            return SectionOutcome(section.id, section.heading, 'failed', str(exc))

        applied = _apply(section, payload)
        if not applied:
            section.restore_baseline()
            section.status = 'failed'
            section.note = 'The model returned no usable blocks.'
            return SectionOutcome(section.id, section.heading, 'failed', section.note)

        problems = {}
        for idx, text in applied.items():
            invented = find_violations(text, allowed)
            dropped = find_dropped_figures(baselines.get(idx, ''), text)
            if invented or dropped:
                problems[idx] = {'invented': invented, 'dropped': dropped}

        if not problems:
            section.status = 'rewritten'
            section.note = ''
            return SectionOutcome(section.id, section.heading, 'rewritten')

        # Roll back before retrying so a partial rewrite cannot leak through.
        section.restore_baseline()

        if attempt == 2:
            invented = sorted({v for p in problems.values() for v in p['invented']})
            dropped = sorted({v for p in problems.values() for v in p['dropped']})
            reasons = []
            if invented:
                reasons.append(f"introduced unverified numbers ({', '.join(invented)})")
            if dropped:
                reasons.append(f"dropped verified figures ({', '.join(dropped)})")
            section.status = 'failed'
            section.note = ('Kept the verified wording: the rewrite '
                            + ' and '.join(reasons) + '.')
            return SectionOutcome(section.id, section.heading, 'failed',
                                  section.note, violations=invented + dropped)

    section.status = 'failed'
    return SectionOutcome(section.id, section.heading, 'failed', 'Unreachable.')


def build_generative_prompt(spec: ReportSpec, section: Section, digest: dict,
                            style: str,
                            rejected: list[str] | None = None) -> str:
    parts = [
        f"Client / advertiser: {spec.client_name}",
        f"Report: {spec.title} — {spec.subtitle}",
        f"Section to write: {section.heading}",
        '',
        f"Style: {STYLES.get(style, STYLES[DEFAULT_STYLE])}",
        '',
        'The full report, as data. Every number you may state appears somewhere in '
        'here; copy each one exactly as written:',
        '',
        json.dumps(digest, indent=1, default=str, ensure_ascii=False),
    ]

    if rejected:
        parts += [
            '',
            'Your previous attempt was rejected because it stated numbers that do not '
            f"appear in the digest: {', '.join(rejected)}. Write the section again. "
            'Use only figures that are in the digest above, copied character-for-'
            'character, and make any point you cannot support with a digest figure in '
            'words instead.',
        ]

    return '\n'.join(parts)


def _render_generated(payload: dict) -> list:
    """Turn the model's verdict / conclusions / recommendations into report blocks."""
    verdict = str(payload.get('verdict') or '').strip()
    conclusions = [str(c).strip() for c in payload.get('conclusions') or [] if str(c).strip()]
    recommendations = [r for r in payload.get('recommendations') or [] if isinstance(r, dict)]

    blocks: list = []
    if verdict:
        blocks.append(Prose(verdict))
    if conclusions:
        blocks.append(Bullets(conclusions))

    lines = []
    for rec in recommendations:
        action = str(rec.get('action') or '').strip().rstrip('.')
        rationale = str(rec.get('rationale') or '').strip()
        priority = str(rec.get('priority') or '').strip() or 'Medium'
        if not action:
            continue
        lines.append(f"**{priority} · {action}**"
                     + (f": {rationale}" if rationale else ''))
    if lines:
        blocks.append(Prose('**Recommended actions**'))
        blocks.append(Bullets(lines))

    return blocks


def _generated_text(payload: dict) -> str:
    """Everything the model asserted, including the evidence it cites but does not
    print, so validation covers the reasoning as well as the prose."""
    parts = [str(payload.get('verdict') or '')]
    parts += [str(c) for c in payload.get('conclusions') or []]
    for rec in payload.get('recommendations') or []:
        if not isinstance(rec, dict):
            continue
        parts += [str(rec.get('action') or ''), str(rec.get('rationale') or '')]
        parts += [str(e) for e in rec.get('evidence') or []]
    return '\n'.join(parts)


def _generate_section(client: GeminiClient, spec: ReportSpec, section: Section,
                      digest: dict, style: str) -> SectionOutcome:
    """Write a section from the whole report rather than rewording its draft.

    Content, judgement and caveats are the model's; the figures are still the
    pipeline's, checked against every number the report computed.
    """
    allowed = report_numbers(spec, digest)
    rejected: list[str] = []

    for attempt in (1, 2):
        try:
            payload = client.generate_json(
                build_generative_prompt(spec, section, digest, style,
                                        rejected=rejected if attempt == 2 else None),
                GENERATIVE_SCHEMA,
                label=f'conclusions:{section.id}',
                system_instruction=GENERATIVE_INSTRUCTION,
                temperature=0.6,
            )
        except GeminiError as exc:
            section.restore_baseline()
            section.status = 'failed'
            section.note = str(exc)
            return SectionOutcome(section.id, section.heading, 'failed', str(exc))

        blocks = _render_generated(payload)
        if not blocks:
            section.restore_baseline()
            section.status = 'failed'
            section.note = 'The model returned no usable conclusions.'
            return SectionOutcome(section.id, section.heading, 'failed', section.note)

        # No figure-retention check here: there is no draft to retain, and the
        # baseline bullets are caveats this section is free to drop.
        rejected = find_violations(_generated_text(payload), allowed)
        if not rejected:
            section.blocks = blocks
            section.status = 'generated'
            section.note = ''
            return SectionOutcome(
                section.id, section.heading, 'generated',
                detail='Written from the full report.',
                verdict=str(payload.get('verdict') or '').strip(),
                conclusions=[str(c).strip() for c in payload.get('conclusions') or []],
                recommendations=[r for r in payload.get('recommendations') or []
                                 if isinstance(r, dict)],
            )

        if attempt == 2:
            section.restore_baseline()
            section.status = 'failed'
            section.note = ('Kept the verified caveats: the generated conclusions stated '
                            f"unverified numbers ({', '.join(rejected)}).")
            return SectionOutcome(section.id, section.heading, 'failed',
                                  section.note, violations=rejected)

    section.status = 'failed'
    return SectionOutcome(section.id, section.heading, 'failed', 'Unreachable.')


def run(spec: ReportSpec, client: GeminiClient | None,
        analysis: AnalysisResult | None = None, style: str = DEFAULT_STYLE,
        max_workers: int = 3,
        progress: Callable[[str], None] | None = None) -> NarrativeResult:
    """Rewrite the template sections' prose, then write the generative ones.

    Template sections are independent, so a few run concurrently. The generative
    sections come last and one at a time, because they read the final narrative of
    everything before them. The deterministic baseline survives any failure.
    """
    say = progress or (lambda _msg: None)

    if client is None:
        for section in spec.sections:
            section.status = 'baseline'
        return NarrativeResult([
            SectionOutcome(s.id, s.heading, 'skipped', 'Gemini not configured.')
            for s in spec.sections])

    # Without the analysis there is no chart data to reason over, so a generative
    # section degrades to a rewrite of its baseline rather than failing.
    generative = [s for s in spec.sections
                  if s.mode == 'generate'] if analysis is not None else []
    generative_ids = {s.id for s in generative}
    rewrite = [s for s in spec.sections
               if s.id not in generative_ids and s.editable()]

    outcomes: list[SectionOutcome] = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_rewrite_section, client, spec, s, style): s
                   for s in rewrite}
        for future in as_completed(futures):
            section = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # a bug in rewriting must not lose the report
                section.restore_baseline()
                section.status = 'failed'
                section.note = f'{type(exc).__name__}: {exc}'
                outcome = SectionOutcome(section.id, section.heading, 'failed',
                                         section.note)
            outcomes.append(outcome)
            done += 1
            say(f'Rewrote {done}/{len(rewrite)} sections ({section.heading})')

    for section in generative:
        say(f'Writing {section.heading} from the full report')
        digest = build_digest(spec, analysis, exclude_section=section.id)
        try:
            outcome = _generate_section(client, spec, section, digest, style)
        except Exception as exc:
            section.restore_baseline()
            section.status = 'failed'
            section.note = f'{type(exc).__name__}: {exc}'
            outcome = SectionOutcome(section.id, section.heading, 'failed', section.note)
        outcomes.append(outcome)

    order = {s.id: i for i, s in enumerate(spec.sections)}
    outcomes.sort(key=lambda o: order.get(o.section_id, 0))
    return NarrativeResult(outcomes)
