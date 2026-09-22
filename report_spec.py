"""
The report as data.

generate_report.py wrote its narrative as f-strings interleaved with docx calls,
which meant the prose could only be changed by editing Python. Here the same
report becomes a ReportSpec: an ordered list of sections, each holding blocks of
prose, bullets, figures and tables, plus the `facts` (pre-formatted numbers) that
its prose is allowed to cite.

That split is what lets the narrative agent rewrite wording at runtime while the
numbers stay exactly as the deterministic pipeline computed them: the agent may
only replace the text of Prose and Bullets blocks, never a figure, a table cell,
or a value in `facts`.

Renderers (pdf_builder, the Streamlit report view) consume a ReportSpec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd

from report_core import (
    AnalysisResult, CHANNEL_MID_FUNNEL, CHANNEL_SEARCH, Metrics,
)

# ----------------------------------------------------------------------------
# Formatting helpers — every number reaching the narrative is formatted here, so
# the same string appears in the prose, the facts block and the rendered tables.
# ----------------------------------------------------------------------------

MISSING = 'n/a'


def _is_missing(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def num(v) -> str:
    """1032 -> '1,032'"""
    if _is_missing(v):
        return MISSING
    return f"{int(round(float(v))):,}"


def pct(v, dp: int = 1) -> str:
    """0.1417 -> '14.2%'"""
    if _is_missing(v):
        return MISSING
    return f"{float(v) * 100:.{dp}f}%"


def dec(v, dp: int = 1) -> str:
    """4.6906 -> '4.7'"""
    if _is_missing(v):
        return MISSING
    return f"{float(v):.{dp}f}"


def date(v, fmt: str = '%b %d, %Y') -> str:
    if _is_missing(v):
        return MISSING
    return pd.Timestamp(v).strftime(fmt)


def _ratio(a, b) -> float:
    if _is_missing(a) or _is_missing(b) or not float(b):
        return float('nan')
    return float(a) / float(b)


def join_list(items) -> str:
    """'a', 'a and b', 'a, b and c'."""
    items = [str(i) for i in items]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    return ', '.join(items[:-1]) + ' and ' + items[-1]


BOLD_RE = re.compile(r'\*\*(.+?)\*\*')


def parse_inline_bold(text: str) -> list[tuple[str, bool]]:
    """'**Lead-in**: rest' -> [('Lead-in', True), (': rest', False)].

    Narrative text is carried as markdown-lite so a single string round-trips
    through the LLM and still renders with bold lead-ins in both PDF and
    Streamlit.
    """
    segments: list[tuple[str, bool]] = []
    pos = 0
    for match in BOLD_RE.finditer(text):
        if match.start() > pos:
            segments.append((text[pos:match.start()], False))
        segments.append((match.group(1), True))
        pos = match.end()
    if pos < len(text):
        segments.append((text[pos:], False))
    return segments or [(text, False)]


# ----------------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------------

@dataclass
class Prose:
    text: str
    baseline: str = ''

    def __post_init__(self):
        if not self.baseline:
            self.baseline = self.text

    @property
    def is_rewritten(self) -> bool:
        return self.text.strip() != self.baseline.strip()


@dataclass
class Bullets:
    items: list[str]
    baseline: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.baseline:
            self.baseline = list(self.items)

    @property
    def is_rewritten(self) -> bool:
        return [i.strip() for i in self.items] != [i.strip() for i in self.baseline]


@dataclass
class Figure:
    path: str | None
    caption: str


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    widths: list[float] | None = None


Block = Prose | Bullets | Figure | Table
EDITABLE = (Prose, Bullets)


@dataclass
class Section:
    id: str
    heading: str
    blocks: list[Block] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    page_break_after: bool = False
    # 'rewrite': the agent may reword the blocks below. 'generate': the agent
    # writes the section itself from the whole report and replaces the blocks.
    mode: str = 'rewrite'
    # Set by the narrative agent for UI reporting.
    status: str = 'baseline'   # baseline | rewritten | generated | failed
    note: str = ''
    baseline_blocks: list[Block] = field(default_factory=list, repr=False)

    def __post_init__(self):
        # A generated section replaces its block list wholesale, so the baseline
        # has to be the list itself, not just the text inside each block.
        if not self.baseline_blocks:
            self.baseline_blocks = list(self.blocks)

    def editable(self) -> list[tuple[int, Block]]:
        return [(i, b) for i, b in enumerate(self.blocks) if isinstance(b, EDITABLE)]

    def figures(self) -> list[Figure]:
        return [b for b in self.blocks if isinstance(b, Figure) and b.path]

    def all_text(self) -> str:
        parts = []
        for b in self.blocks:
            if isinstance(b, Prose):
                parts.append(b.text)
            elif isinstance(b, Bullets):
                parts.extend(b.items)
        return '\n'.join(parts)

    def baseline_text(self) -> str:
        parts = []
        for b in (self.baseline_blocks or self.blocks):
            if isinstance(b, Prose):
                parts.append(b.baseline)
            elif isinstance(b, Bullets):
                parts.extend(b.baseline)
        return '\n'.join(parts)

    def restore_baseline(self) -> None:
        if self.baseline_blocks:
            self.blocks = list(self.baseline_blocks)
        for b in self.blocks:
            if isinstance(b, Prose):
                b.text = b.baseline
            elif isinstance(b, Bullets):
                b.items = list(b.baseline)


@dataclass
class KPI:
    label: str
    value: str
    help: str = ''


@dataclass
class ReportSpec:
    client_name: str
    title: str
    subtitle: str
    cover_lines: list[str]
    sections: list[Section]
    kpis: list[KPI] = field(default_factory=list)
    context: str = ''

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def iter_editable(self) -> Iterator[tuple[Section, int, Block]]:
        for section in self.sections:
            for idx, block in section.editable():
                yield section, idx, block

    def restore_baseline(self) -> None:
        for section in self.sections:
            section.restore_baseline()
            section.status = 'baseline'
            section.note = ''


# ----------------------------------------------------------------------------
# Spec construction
# ----------------------------------------------------------------------------

def _summary_bullets(m: Metrics) -> list[str]:
    ranked = m.platform_volume.sort_values('conversions_influenced', ascending=False) \
        if not m.platform_volume.empty else m.platform_volume
    reach = [f"{p} ({num(r.conversions_influenced)}, {pct(r.pct_of_all_conversions)} of conversions)"
             for p, r in ranked.iterrows()]

    bullets = [
        f"**Mid-funnel touch**: {pct(m.pct_mf_touched)} of conversions in this window "
        f"({num(m.n_mf_touched)} of {num(m.n_conversions)}) were touched by a mid-funnel platform "
        f"at least once; the remaining {pct(m.pct_untouched)} were Search-only. Of the touched "
        f"paths, {pct(m.pct_mf_impr_only, 0)} ({num(m.n_mf_impr_only)}) were view-through only "
        f"(impression, no click), showing mid-funnel is mostly assisting the journey rather than "
        f"being clicked directly.",

        f"**Path mix**: {pct(m.pct_search_only)} of conversions are Search-only, "
        f"{pct(m.pct_mixed)} are Mixed (touched by both Search and mid-funnel), and "
        f"{pct(m.pct_mf_only)} are Mid-funnel-only (view-through, no search touch at all).",

        f"The hypothesis is partially supported: {pct(m.pct_classic)} of Mixed paths "
        f"({num(m.n_classic)} of {num(m.n_mixed_paths)}) follow the classic pattern of mid-funnel "
        f"first touch converting via Search. Among these, the median time between the first "
        f"mid-funnel exposure and the converting Search click is {dec(m.lag_median)} days, with "
        f"{pct(m.pct_multi_day)} taking a day or more.",
    ]

    if 'Mixed' in m.by_type.index and 'Search-only' in m.by_type.index:
        bullets.append(
            f"Mixed paths take meaningfully longer to convert (avg. "
            f"{dec(m.by_type.loc['Mixed', 'avg_days_to_convert'])} days, "
            f"{dec(m.by_type.loc['Mixed', 'avg_path_length'])} touches) than Search-only paths "
            f"(avg. {dec(m.by_type.loc['Search-only', 'avg_days_to_convert'])} days, "
            f"{dec(m.by_type.loc['Search-only', 'avg_path_length'])} touches), consistent with "
            f"mid-funnel nurturing demand rather than capturing existing intent.")

    if reach:
        bullets.append(
            f"**Platform reach**: {reach[0]} leads among mid-funnel platforms"
            + (f", ahead of {join_list(reach[1:])}." if len(reach) > 1 else "."))

    bullets.append(
        f"**Attribution coverage**: the export contains {num(m.n_export_conversions)} conversions "
        f"for this activity, of which {num(m.n_conversions)} ({pct(m.pct_attributed)}) carry at "
        f"least one CM360 interaction. The {num(m.n_unattributed)} unattributed conversions (path "
        f"length 0) have no touch data and are excluded from every path metric in this report.")
    return bullets


def _transition_bullets(transition_matrix: pd.DataFrame, m: Metrics) -> list[str]:
    if transition_matrix.empty:
        return ["No consecutive touch pairs were available, so no transition probabilities "
                "could be computed for this window."]

    present = [p for p in transition_matrix.index if transition_matrix.loc[p].sum() > 0]
    self_loop = {p: transition_matrix.loc[p, p] for p in present}
    search = [p for p in present if p in m.search_present]
    mid = [p for p in present if p in m.mid_funnel_present]

    out: list[str] = []
    if search:
        parts = ', '.join(f"{p} ({pct(self_loop[p], 0)})" for p in search)
        out.append(f"**Search persistence**: {parts} show high continuity, users return to the "
                   f"same search engine for their next touch.")
    if mid:
        stayers = sorted(mid, key=lambda p: self_loop[p], reverse=True)
        parts = ', '.join(f"{p} ({pct(self_loop[p], 0)} stay)" for p in stayers)
        out.append(f"**Social platform loyalty**: {parts}. Platforms with lower self-transition "
                   f"rates are handing users off rather than holding them.")
        lowest = stayers[-1]
        row = transition_matrix.loc[lowest].drop(lowest)
        if not row.empty:
            dest = row.idxmax()
            if row[dest] > 0:
                out.append(
                    f"**{lowest} as an awareness play**: only {pct(self_loop[lowest], 0)} of "
                    f"{lowest} interactions lead to another {lowest} touch; {pct(row[dest], 0)} "
                    f"transition to {dest}, suggesting it functions as an upper-funnel driver "
                    f"rather than a closer.")
    return out or ["Transition volumes were too thin to draw a platform-loyalty conclusion."]


def quality_signals(m: Metrics) -> dict[str, Any]:
    """The caveats the data itself triggers: platforms that were not live for the
    whole window, platforms too small to conclude on, and the Mixed sample size.

    Shared by the baseline caveat bullets and the digest, so the generative agent
    sees exactly the same signals and can decide for itself whether to caveat.
    """
    partial, low_volume = [], []
    for platform in m.mid_funnel_present:
        w = m.live_windows.loc[platform]
        late = (w['first_touch'] - m.date_min).days > 3
        early_stop = (m.date_max - w['last_touch']).days > 7
        if late or early_stop:
            partial.append(f"{platform} ran {date(w['first_touch'], '%b %d')} to "
                           f"{date(w['last_touch'], '%b %d')}")
        if platform in m.platform_volume.index and \
                m.platform_volume.loc[platform, 'pct_of_all_conversions'] < 0.01:
            low_volume.append(
                f"{platform} ({num(m.platform_volume.loc[platform, 'conversions_influenced'])} "
                f"conversions influenced)")

    return {
        'partial_window_platforms': partial,
        'sub_1pct_platforms': low_volume,
        'mixed_sample_size': f"n={num(m.n_mixed_paths)} ({pct(m.pct_mixed)} of conversions)",
        'export_type': ('Path-to-conversion / last-touch-adjacent export, not a full '
                        'multi-touch attribution model.'),
    }


def derived_comparisons(m: Metrics) -> dict[str, Any]:
    """Comparisons the agent would otherwise have to calculate itself.

    Pre-computing them here is what lets the conclusions make comparative claims
    ("Reddit influenced 45.0x the conversions TikTok did") while the ban on
    invented arithmetic still holds.
    """
    ranked = m.platform_volume.sort_values('conversions_influenced', ascending=False) \
        if not m.platform_volume.empty else m.platform_volume

    platforms: list[dict[str, str]] = []
    leader = ranked.index[0] if len(ranked) else None
    leader_conv = float(ranked.iloc[0]['conversions_influenced']) if len(ranked) else 0.0

    for platform, row in ranked.iterrows():
        conv = float(row['conversions_influenced'])
        platforms.append({
            'platform': str(platform),
            'touches': num(row['touches']),
            'conversions_influenced': num(conv),
            'share_of_all_conversions': pct(row['pct_of_all_conversions']),
            'share_of_mid_funnel_touched': pct(_ratio(conv, m.n_mf_touched)),
            'ratio_vs_leader': (f"{dec(_ratio(leader_conv, conv))}x"
                                if conv and platform != leader else
                                ('leader' if platform == leader else MISSING)),
        })

    out: dict[str, Any] = {
        'leading_mid_funnel_platform': str(leader) if leader is not None else MISSING,
        'mid_funnel_touched_conversions': num(m.n_mf_touched),
        'per_platform': platforms,
        'note_on_shares': ('Shares of mid-funnel-touched conversions are computed against '
                           f"the {num(m.n_mf_touched)} conversions touched by any mid-funnel "
                           'platform; a conversion can be touched by more than one platform, '
                           'so these shares need not sum to 100%.'),
        'touched_vs_untouched': {
            'path_length_multiple': f"{dec(_ratio(m.touched_apl, m.untouched_apl))}x",
            'days_to_convert_multiple': f"{dec(_ratio(m.touched_days, m.untouched_days))}x",
            'extra_days': dec(m.touched_days - m.untouched_days),
            'touched_avg_touches': dec(m.touched_apl),
            'untouched_avg_touches': dec(m.untouched_apl),
            'touched_avg_days': dec(m.touched_days),
            'untouched_avg_days': dec(m.untouched_days),
        },
        'view_through_share_of_touched': pct(m.pct_mf_impr_only, 0),
        'classic_pattern_share_of_mixed': pct(m.pct_classic),
    }

    if 'Mixed' in m.by_type.index and 'Search-only' in m.by_type.index:
        mixed_days = float(m.by_type.loc['Mixed', 'avg_days_to_convert'])
        search_days = float(m.by_type.loc['Search-only', 'avg_days_to_convert'])
        out['mixed_vs_search_only'] = {
            'days_multiple': f"{dec(_ratio(mixed_days, search_days))}x",
            'extra_days': dec(mixed_days - search_days),
        }
    return out


def _conclusion_bullets(m: Metrics) -> list[str]:
    bullets = [
        f"**Analysis window**: this report covers conversions from {date(m.date_min)} to "
        f"{date(m.date_max)}, the period in which the mid-funnel platforms were live and tagged. "
        f"Pre-activation weeks are excluded so the numbers are not diluted by weeks in which "
        f"mid-funnel could not appear.",
    ]

    signals = quality_signals(m)
    partial = signals['partial_window_platforms']
    low_volume = signals['sub_1pct_platforms']

    if partial:
        plural = len(partial) > 1
        bullets.append(
            f"**Partial-window platform{'s' if plural else ''}**: {'; '.join(partial)}, so "
            f"{'these platforms were' if plural else 'it was'} not live for the full window. "
            f"{'Their' if plural else 'Its'} metrics are directional and should not be compared "
            f"like-for-like with always-on platforms.")
    if low_volume:
        plural = len(low_volume) > 1
        bullets.append(
            f"**Low-volume platform{'s' if plural else ''}**: {join_list(low_volume)} influenced "
            f"under 1% of conversions{' each' if plural else ''}. Any conclusion drawn on "
            f"{'them' if plural else 'it'} is directional, not statistically solid.")

    bullets += [
        f"The Mixed-path sample is small (n={num(m.n_mixed_paths)}, {pct(m.pct_mixed)} of "
        f"conversions in the window), so point estimates on this subset (for example the "
        f"classic-hypothesis rate) carry wide uncertainty and should be revisited as more data "
        f"accumulates.",

        "This is a path-to-conversion / last-touch-adjacent export, not a full multi-touch "
        "attribution model, so all percentages here are directional evidence for the mid-funnel "
        "hypothesis rather than a formal attribution result.",

        "**Recommendation**: re-run this report on the next refresh once every mid-funnel platform "
        "has a full month of in-window data, to tighten these estimates and confirm the trend "
        "direction.",
    ]
    return bullets


def _kpis(m: Metrics) -> list[KPI]:
    return [
        KPI('Attributed conversions', num(m.n_conversions),
            f"{num(m.n_export_conversions)} in the export, {pct(m.pct_attributed)} carry a touch"),
        KPI('Touched by mid-funnel', pct(m.pct_mf_touched),
            f"{num(m.n_mf_touched)} conversions"),
        KPI('Mixed paths', pct(m.pct_mixed), f"{num(m.n_mixed)} both Search and mid-funnel"),
        KPI('View-through only', pct(m.pct_mf_impr_only, 0),
            f"{num(m.n_mf_impr_only)} of touched paths had no mid-funnel click"),
        KPI('Median assist lag', f"{dec(m.lag_median)} days",
            f"first mid-funnel touch to converting Search click ({num(m.n_classic)} paths)"),
    ]


def build_spec(result: AnalysisResult, client_name: str, subtitle: str,
               context: str = '') -> ReportSpec:
    """Assemble the full report as data, mirroring the section order and wording
    of the original deliverable."""
    m = result.metrics
    charts = result.charts
    client = client_name.strip() or 'the client'

    sections: list[Section] = []

    # ---------------- Summary ----------------
    mf_list = join_list(m.mid_funnel_present) or 'the mid-funnel platforms'
    sections.append(Section(
        id='summary',
        heading='Summary',
        facts={
            'client': client,
            'mid_funnel_platforms': mf_list,
            'date_min': date(m.date_min), 'date_max': date(m.date_max),
            'n_conversions': num(m.n_conversions),
            'n_export_conversions': num(m.n_export_conversions),
            'n_unattributed': num(m.n_unattributed),
            'pct_attributed': pct(m.pct_attributed),
            'pct_mf_touched': pct(m.pct_mf_touched), 'n_mf_touched': num(m.n_mf_touched),
            'pct_untouched': pct(m.pct_untouched),
            'pct_mf_impr_only': pct(m.pct_mf_impr_only, 0), 'n_mf_impr_only': num(m.n_mf_impr_only),
            'pct_search_only': pct(m.pct_search_only), 'pct_mixed': pct(m.pct_mixed),
            'pct_mf_only': pct(m.pct_mf_only),
            'pct_classic': pct(m.pct_classic), 'n_classic': num(m.n_classic),
            'n_mixed_paths': num(m.n_mixed_paths),
            'lag_median_days': dec(m.lag_median), 'pct_multi_day': pct(m.pct_multi_day),
        },
        blocks=[
            Prose(
                f"This report analyzes CM360 path-to-conversion data for {client} to test whether "
                f"mid-funnel awareness channels ({mf_list}) build interest that later converts "
                f"through Search. It covers conversions from {date(m.date_min)} to "
                f"{date(m.date_max)}, the period in which all mid-funnel platforms were live and "
                f"tagged, so the numbers reflect mid-funnel's true impact rather than an "
                f"activation ramp-up."),
            Bullets(_summary_bullets(m)),
        ],
    ))

    # ---------------- Methodology ----------------
    method_blocks: list[Block] = [
        Prose(
            f"Source: CM360 Path-to-Conversion export for the floodlight activity "
            f"\"{m.activity_name}\", covering activity from {date(m.date_min, '%Y-%m-%d')} to "
            f"{date(m.date_max, '%Y-%m-%d')}. Each conversion's full touch sequence (up to "
            f"{m.n_interaction_slots} recorded interactions) was reshaped into a touch-level table "
            f"and classified using the following taxonomy, derived from the campaigns and sites "
            f"actually present in the export:"),
        Table(['Campaign', 'Site (CM360)', 'Channel', 'Platform'],
              m.taxonomy.astype(str).values.tolist(), widths=[1.55, 1.75, 1.2, 1.5]),
        Prose(
            f"Attribution coverage: {num(m.n_export_conversions)} conversions were returned for "
            f"this activity. {num(m.n_conversions)} ({pct(m.pct_attributed)}) carry at least one "
            f"CM360 interaction and form the basis of every path metric below; the remaining "
            f"{num(m.n_unattributed)} have a path length of 0, meaning no click or impression was "
            f"matched to them, and are excluded rather than counted as Search-only."),
    ]

    if m.has_rampup:
        cut = date(m.steady_state_start)
        method_blocks += [
            Prose(
                f"The raw export covers {date(m.ctx_full_date_min, '%b %d')} to "
                f"{date(m.ctx_full_date_max)} ({num(m.ctx_full_n)} attributed conversions), but "
                f"the mid-funnel platforms were not live for the first part of that range. The "
                f"first mid-funnel interaction recorded anywhere in the data is "
                f"{date(m.first_mf_date)}; everything before that is Search-only by construction, "
                f"not by consumer behaviour. Including those weeks does not measure how often "
                f"mid-funnel is involved, it measures how long the platforms took to turn on, and "
                f"mechanically drags every mid-funnel metric toward zero."),
            Prose(
                f"The data makes the distortion concrete. Measuring the full export against the "
                f"post-activation window (from {cut}, once all platforms were live):"),
            Table(['Metric', 'Full export', f'This report (from {cut})'],
                  [['Attributed conversions', num(m.ctx_full_n), num(m.n_conversions)],
                   ['% touched by any mid-funnel', pct(m.ctx_full_pct_touched), pct(m.pct_mf_touched)],
                   ['% Mixed (Search + Mid-funnel)', pct(m.ctx_full_pct_mixed), pct(m.pct_mixed)]],
                  widths=[2.4, 1.7, 1.9]),
            Prose(
                f"Scoping to the post-activation window lifts the mid-funnel touch rate from "
                f"{pct(m.ctx_full_pct_touched)} to {pct(m.pct_mf_touched)} because it stops "
                f"averaging in weeks where mid-funnel could not appear. All findings that follow "
                f"use only this post-activation window."),
        ]
    else:
        method_blocks += [
            Prose(
                f"Window: the export was pulled from {date(m.date_min)} onward, which is already "
                f"the post-activation window, so no ramp-up weeks need to be trimmed and no "
                f"mid-funnel metric is diluted by weeks in which the platforms were not yet live. "
                f"Individual platforms did, however, start and stop at different points, which is "
                f"what the touch windows below show. Touch dates can precede the conversion "
                f"window, since an exposure that led to an in-window conversion may have happened "
                f"earlier:"),
            Table(['Platform', 'First recorded touch', 'Last recorded touch', 'Touches'],
                  [[p, date(r['first_touch']), date(r['last_touch']), num(r['touches'])]
                   for p, r in m.live_windows.iterrows()],
                  widths=[1.5, 1.65, 1.65, 1.2]),
            Prose(
                "Platforms that joined or stopped mid-window carry fewer exposure days than the "
                "always-on Search campaigns, so their share of conversions understates their "
                "steady-state contribution. The timeseries below shows daily touch volume per "
                "platform, making each platform's live period and relative intensity visible."),
        ]

    method_blocks.append(Figure(charts.get('daily_mf'),
                               'Figure 1. Mid-funnel platforms timeseries.'))

    sections.append(Section(
        id='methodology', heading='Methodology & Data Notes', blocks=method_blocks,
        page_break_after=True,
        facts={
            'activity_name': m.activity_name,
            'n_interaction_slots': str(m.n_interaction_slots),
            'date_min': date(m.date_min), 'date_max': date(m.date_max),
            'n_export_conversions': num(m.n_export_conversions),
            'n_conversions': num(m.n_conversions),
            'n_unattributed': num(m.n_unattributed),
            'pct_attributed': pct(m.pct_attributed),
            'has_rampup': str(m.has_rampup),
        },
    ))

    # ---------------- Path mix ----------------
    sections.append(Section(
        id='path_mix', heading='Mid-Funnel vs. Search Path Mix',
        facts={
            'n_conversions': num(m.n_conversions),
            'pct_search_only': pct(m.pct_search_only), 'n_search_only': num(m.n_search_only),
            'pct_mf_only': pct(m.pct_mf_only), 'n_mf_only': num(m.n_mf_only),
            'pct_mixed': pct(m.pct_mixed), 'n_mixed': num(m.n_mixed),
            'n_mixed_paths': num(m.n_mixed_paths), 'n_classic': num(m.n_classic),
            'pct_classic': pct(m.pct_classic),
        },
        blocks=[
            Prose(
                f"Out of {num(m.n_conversions)} attributed conversions, the large majority "
                f"({pct(m.pct_search_only)}) never touch a mid-funnel platform at all. "
                f"{pct(m.pct_mf_only)} convert on a mid-funnel view-through impression with no "
                f"Search touch in the path, and {pct(m.pct_mixed)} ({num(m.n_mixed)} conversions) "
                f"show both channels in the same path."),
            Figure(charts.get('path_type'),
                   'Figure 2. Conversions by path type (campaign level).'),
            Prose(
                f"Within these {num(m.n_mixed_paths)} Mixed conversions, {num(m.n_classic)} "
                f"({pct(m.pct_classic)}) follow the exact hypothesis pattern, mid-funnel touches "
                f"first and Search converts last. This confirms the pattern exists and is not "
                f"negligible, but it is not yet the dominant journey shape among Mixed paths; the "
                f"reverse order (Search touching first, mid-funnel later) also occurs."),
        ],
    ))

    # ---------------- Top converting paths ----------------
    top_rows = result.top_paths_rows
    top_share = sum(r['pct'] for r in top_rows)
    sections.append(Section(
        id='top_paths', heading='Top Converting Paths by Platform',
        page_break_after=True,
        facts={
            'n_top_paths': str(len(top_rows)),
            'top_share': pct(top_share),
            'n_conversions': num(m.n_conversions),
            'top_journey': top_rows[0]['journey'] if top_rows else MISSING,
            'top_journey_pct': pct(top_rows[0]['pct']) if top_rows else MISSING,
        },
        blocks=[
            Prose(
                f"Collapsing each conversion's touch sequence into its ordered distinct-consecutive "
                f"platform steps (so repeated touches on the same platform read as one step) and "
                f"ranking the most common journeys gives a DV360-style top converting paths view. "
                f"Position 1 is the converting (last) touch. The {len(top_rows)} journeys below "
                f"account for {pct(top_share)} of all {num(m.n_conversions)} conversions in this "
                f"window."),
            Figure(charts.get('top_paths'),
                   'Figure 3. Top converting paths, grouped by platform '
                   '(position 1 = converting touch).'),
            Table(['Rank', 'Converting path (first -> last)', 'Conversions', '% of conversions'],
                  [[str(i + 1), r['journey'], num(r['conversions']), pct(r['pct'])]
                   for i, r in enumerate(top_rows)],
                  widths=[0.6, 3.0, 1.1, 1.3]),
            Prose(
                "Read in practice: the top paths are dominated by single-platform Search journeys, "
                "confirming most conversions never involve a mid-funnel touch. The multi-platform "
                "journeys that do appear are exactly the mid-funnel-assisted paths quantified in "
                "the path mix and funnel velocity sections, real but a small share of total volume "
                "in the current window."),
        ],
    ))

    # ---------------- Transition flow ----------------
    tm = result.transition_matrix
    diag = {p: pct(tm.loc[p, p], 0) for p in tm.index} if not tm.empty else {}
    sections.append(Section(
        id='transitions', heading='Platform Transition Flow',
        facts={'self_transition_rates': ', '.join(f'{k}: {v}' for k, v in diag.items()) or MISSING},
        blocks=[
            Prose(
                "The heatmap below shows, for every consecutive touch pair in a conversion path, "
                "the probability of each next-touch platform (row %). Rows represent the current "
                "platform and columns where the user touches next. The diagonal reflects platform "
                "loyalty, how often a touch on a given platform is immediately followed by another "
                "touch on the same platform, while off-diagonal cells reveal cross-platform "
                "migration."),
            Bullets(_transition_bullets(tm, m)),
            Figure(charts.get('heatmap'),
                   'Figure 4. Platform-to-platform transition probabilities '
                   '(row % of next-touch platform).'),
        ],
    ))

    # ---------------- Velocity by path type ----------------
    ratio = (m.touched_apl / m.untouched_apl) if m.untouched_apl else float('nan')
    sections.append(Section(
        id='velocity', heading='Mixed Paths Take Longer to Convert',
        page_break_after=True,
        facts={
            'touched_avg_touches': dec(m.touched_apl), 'touched_avg_days': dec(m.touched_days),
            'untouched_avg_touches': dec(m.untouched_apl), 'untouched_avg_days': dec(m.untouched_days),
            'path_length_ratio': dec(ratio), 'extra_days': dec(m.touched_days - m.untouched_days),
        },
        blocks=[
            Prose(
                "If mid-funnel is genuinely building interest earlier in the journey rather than "
                "acting as a same-session assist, Mixed paths should show longer paths and longer "
                "time-to-convert than Search-only paths. The data supports this:"),
            Table(['Path type', 'Conversions', 'Avg. path length (touches)', 'Avg. days to convert'],
                  [[t, num(m.by_type.loc[t, 'conversions']),
                    dec(m.by_type.loc[t, 'avg_path_length'], 2),
                    dec(m.by_type.loc[t, 'avg_days_to_convert'], 2)]
                   for t in ['Search-only', 'Mixed', 'Mid-funnel-only'] if t in m.by_type.index],
                  widths=[1.4, 1.1, 1.9, 1.6]),
            Prose(
                f"Collapsing this to a two-way comparison makes the gap clear: conversions touched "
                f"by mid-funnel at any point average {dec(m.touched_apl)} touches and "
                f"{dec(m.touched_days)} days from first touch to conversion, versus "
                f"{dec(m.untouched_apl)} touches and {dec(m.untouched_days)} days for Search-only "
                f"conversions. A mid-funnel touch is therefore associated with a path roughly "
                f"{dec(ratio)}x longer that takes about {dec(m.touched_days - m.untouched_days)} "
                f"more days to close, the signature of a longer, more considered journey rather "
                f"than same-session intent capture."),
            Figure(charts.get('length_time'),
                   'Figure 5. Average path length and days-to-convert by path type.'),
        ],
    ))

    # ---------------- Platform breakdown ----------------
    ranked = m.platform_volume.sort_values('conversions_influenced', ascending=False) \
        if not m.platform_volume.empty else m.platform_volume
    lead = ranked.index[0] if len(ranked) else MISSING
    sections.append(Section(
        id='platforms', heading='Platform Breakdown & Path Position',
        facts={
            'lead_platform': str(lead),
            'other_platforms': join_list(ranked.index[1:]) if len(ranked) > 1 else MISSING,
            'platform_reach': ', '.join(
                f"{p}: {num(r['conversions_influenced'])} conversions "
                f"({pct(r['pct_of_all_conversions'])})" for p, r in ranked.iterrows()) or MISSING,
        },
        blocks=[
            Prose(
                f"At the site level, {lead} has the largest footprint among mid-funnel platforms"
                + (f", followed by {join_list(ranked.index[1:])}." if len(ranked) > 1 else ".")
                + " Touch counts include both clicks and view-through impressions."),
            Table(['Platform', 'Touches', 'Conversions influenced', '% of all conversions'],
                  [[p, num(r['touches']), num(r['conversions_influenced']),
                    pct(r['pct_of_all_conversions'])] for p, r in ranked.iterrows()],
                  widths=[1.5, 1.1, 1.9, 1.5]),
            Prose(
                "Looking at where each platform's touch tends to land within the path (first / "
                "middle / last / only touch) shows whether a platform behaves more like "
                "top-of-funnel awareness or late-stage retargeting:"),
            Figure(charts.get('position'),
                   'Figure 6. Touch position distribution by mid-funnel platform.'),
        ],
    ))

    # ---------------- Path flow ----------------
    sections.append(Section(
        id='path_flow', heading='Path Flow: First Touch to Converting Touch',
        facts={'n_multi_touch': num(int((result.paths['n_touches'] > 1).sum()))},
        blocks=[
            Prose(
                "For multi-touch conversions, tracing the flow from the first touch platform to "
                "the last (converting) touch platform gives a quick visual read on whether "
                "mid-funnel platforms feed into Search by the end of the journey, or whether paths "
                "tend to stay within one platform."),
            Figure(charts.get('sankey'),
                   'Figure 7. First-touch platform to last-touch platform flow '
                   '(multi-touch conversions).'),
        ],
    ))

    # ---------------- Funnel velocity ----------------
    sections.append(Section(
        id='funnel_velocity',
        heading='Funnel Velocity: Mid-Funnel Builds Interest, Search Converts Later',
        page_break_after=True,
        facts={
            'n_classic': num(m.n_classic), 'lag_median_days': dec(m.lag_median),
            'lag_mean_days': dec(m.lag_mean), 'pct_multi_day': pct(m.pct_multi_day),
        },
        blocks=[
            Prose(
                f"For the {num(m.n_classic)} mid-funnel-assisted Search conversions, the median "
                f"time between the first mid-funnel touch and the eventual converting Search click "
                f"is {dec(m.lag_median)} days (mean {dec(m.lag_mean)} days). "
                f"{pct(m.pct_multi_day)} of these conversions take a day or more to close after "
                f"the initial mid-funnel exposure, the clearest quantitative evidence that "
                f"mid-funnel is acting as an earlier-funnel nurture touch rather than a "
                f"same-session assist."),
            Figure(charts.get('lag'),
                   'Figure 8. Days between first mid-funnel touch and converting Search click.'),
        ],
    ))

    # ---------------- Conclusions ----------------
    # Written by the narrative agent from the whole report rather than reworded
    # from a template; these baseline bullets are what a failed generation
    # degrades to.
    sections.append(Section(
        id='conclusions', heading='Conclusions & Recommendations',
        mode='generate',
        facts={
            'date_min': date(m.date_min), 'date_max': date(m.date_max),
            'n_mixed_paths': num(m.n_mixed_paths), 'pct_mixed': pct(m.pct_mixed),
        },
        blocks=[Bullets(_conclusion_bullets(m))],
    ))

    return ReportSpec(
        client_name=client,
        title='Path to Conversion Copilot',
        subtitle=subtitle,
        cover_lines=[
            f"Client: {client}",
            f"Data range: {date(m.date_min)} - {date(m.date_max)}",
            f"Total conversions analyzed: {num(m.n_conversions)}",
            f"Report prepared: {date(pd.Timestamp.now(), '%B %d, %Y')}",
        ],
        sections=sections,
        kpis=_kpis(m),
        context=context,
    )


# ----------------------------------------------------------------------------
# Report digest
#
# What a generative section is given instead of a draft to reword: every figure
# the report contains, the data behind every chart, and the prose of the sections
# it is concluding. Values are pre-formatted with the same helpers the report
# uses, so a figure the agent copies out of the digest is character-identical to
# the one the reader sees in the body.
# ----------------------------------------------------------------------------

MAX_ROWS = 40          # per table, so the whole digest stays inside a flash context
MAX_DAILY_ROWS = 70

LAG_BUCKETS = [
    ('Same day (under 1 day)', 0.0, 1.0),
    ('1 to 3 days', 1.0, 4.0),
    ('4 to 7 days', 4.0, 8.0),
    ('8 to 14 days', 8.0, 15.0),
    ('15 days or more', 15.0, float('inf')),
]


def _path_type_records(m: Metrics) -> list[dict[str, str]]:
    shares = {'Search-only': m.pct_search_only, 'Mixed': m.pct_mixed,
              'Mid-funnel-only': m.pct_mf_only}
    order = [t for t in ['Search-only', 'Mixed', 'Mid-funnel-only'] if t in m.by_type.index]
    return [{
        'path_type': t,
        'conversions': num(m.by_type.loc[t, 'conversions']),
        'share_of_conversions': pct(shares.get(t)),
        'avg_path_length': dec(m.by_type.loc[t, 'avg_path_length'], 2),
        'avg_days_to_convert': dec(m.by_type.loc[t, 'avg_days_to_convert'], 2),
    } for t in order]


def _daily_records(analysis: AnalysisResult) -> list[dict[str, str]]:
    daily, m = analysis.daily_counts, analysis.metrics
    cols = [p for p in m.mid_funnel_present if p in getattr(daily, 'columns', [])]
    if not cols:
        return []
    sub = daily[cols]
    sub = sub[sub.sum(axis=1) > 0].tail(MAX_DAILY_ROWS)
    return [{'day': date(day, '%Y-%m-%d'),
             **{p: num(row[p]) for p in cols}} for day, row in sub.iterrows()]


def _transition_records(tm: pd.DataFrame) -> list[dict[str, str]]:
    if tm.empty:
        return []
    rows = [(p, q, float(tm.loc[p, q])) for p in tm.index for q in tm.columns
            if float(tm.loc[p, q]) > 0]
    rows.sort(key=lambda r: r[2], reverse=True)
    return [{'from_platform': str(p), 'next_platform': str(q), 'probability': pct(v, 0)}
            for p, q, v in rows[:MAX_ROWS]]


def _position_records(position_dist: pd.DataFrame) -> list[dict[str, str]]:
    if position_dist.empty:
        return []
    return [{'platform': str(p),
             **{str(c): pct(row[c], 0) for c in position_dist.columns}}
            for p, row in position_dist.iterrows()]


def _flow_records(flow_counts: pd.DataFrame) -> list[dict[str, str]]:
    if flow_counts.empty:
        return []
    top = flow_counts.sort_values('n', ascending=False).head(MAX_ROWS)
    return [{'first_touch_platform': str(r.first_touch_platform),
             'last_touch_platform': str(r.last_touch_platform),
             'conversions': num(r.n)} for r in top.itertuples()]


def _lag_records(m: Metrics) -> dict[str, Any]:
    lag = m.lag_days
    total = len(lag)
    dist = []
    for label, lo, hi in LAG_BUCKETS:
        n = int(((lag >= lo) & (lag < hi)).sum()) if total else 0
        if n:
            dist.append({'bucket': label, 'conversions': num(n),
                         'share': pct(_ratio(n, total))})
    return {
        'n_paths': num(total),
        'median_days': dec(m.lag_median),
        'mean_days': dec(m.lag_mean),
        'share_1_day_or_more': pct(m.pct_multi_day),
        'distribution': dist,
    }


def _live_window_records(m: Metrics) -> list[dict[str, str]]:
    return [{'platform': str(p), 'first_touch': date(r['first_touch']),
             'last_touch': date(r['last_touch']), 'touches': num(r['touches'])}
            for p, r in m.live_windows.iterrows()]


def build_digest(spec: ReportSpec, analysis: AnalysisResult,
                 exclude_section: str | None = None) -> dict[str, Any]:
    """Everything a generative section may reason over, as plain formatted data."""
    m = analysis.metrics

    return {
        'report': {
            'client': spec.client_name,
            'title': spec.title,
            'subtitle': spec.subtitle,
            'floodlight_activity': m.activity_name,
            'window_start': date(m.date_min),
            'window_end': date(m.date_max),
            'mid_funnel_platforms': list(m.mid_funnel_present),
            'search_platforms': list(m.search_present),
        },
        'analyst_context': spec.context.strip()[:8000],
        'headline_kpis': [{'label': k.label, 'value': k.value, 'detail': k.help}
                          for k in spec.kpis],
        'section_facts': {s.id: dict(s.facts) for s in spec.sections
                          if s.id != exclude_section and s.facts},
        'section_narrative': {s.id: {'heading': s.heading, 'text': s.all_text()}
                              for s in spec.sections
                              if s.id != exclude_section and s.all_text().strip()},
        'chart_data': {
            'conversions_and_velocity_by_path_type': _path_type_records(m),
            'daily_mid_funnel_touches_by_platform': _daily_records(analysis),
            'platform_live_windows': _live_window_records(m),
            'top_converting_journeys': [
                {'rank': str(i + 1), 'journey': r['journey'],
                 'conversions': num(r['conversions']), 'share_of_conversions': pct(r['pct'])}
                for i, r in enumerate(analysis.top_paths_rows)],
            'platform_transition_probabilities': _transition_records(analysis.transition_matrix),
            'touch_position_by_platform': _position_records(analysis.position_dist),
            'first_to_last_touch_flows': _flow_records(analysis.flow_counts),
            'mid_funnel_assist_lag': _lag_records(m),
        },
        'comparisons': derived_comparisons(m),
        'data_quality_flags': quality_signals(m),
    }
