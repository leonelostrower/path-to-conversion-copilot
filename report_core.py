"""
Path-to-conversion analysis pipeline, refactored from generate_report.py into
importable pure functions.

Every function here is side-effect free at import time and takes its taxonomy
explicitly, so the Streamlit app can drive the pipeline with a client-specific
mapping produced at runtime instead of the Rates.ca constants the original
script hardcoded.

Nothing in this module calls Gemini. All numbers are computed from the export.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

import plotly.graph_objects as go

# ----------------------------------------------------------------------------
# Paths — rebased onto this project directory (the original resolved one level
# too high and pointed at ~/Desktop).
# ----------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
REPORTS_DIR = os.path.join(OUTPUT_DIR, 'reports')
UPLOADS_DIR = os.path.join(OUTPUT_DIR, 'uploads')
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'assets')
LOGO_PATH = os.path.join(ASSETS_DIR, 'monks_logo.png')

plt.rcParams['figure.figsize'] = (10, 5)
plt.rcParams['savefig.dpi'] = 150

# Path-type palette is fixed: the three types are structural, not client-specific.
COLORS_PT = {'Search-only': '#4C72B0', 'Mixed': '#DD8452', 'Mid-funnel-only': '#55A868'}

CHANNEL_SEARCH = 'Search'
CHANNEL_MID_FUNNEL = 'Mid-funnel'
CHANNEL_OTHER = 'Other'
VALID_CHANNELS = (CHANNEL_SEARCH, CHANNEL_MID_FUNNEL, CHANNEL_OTHER)

# Placeholder CM360 writes when a dimension has no value.
NULL_TOKEN = '---'

FALLBACK_COLORS = [
    '#4285F4', '#FF4500', '#1877F2', '#00C4A7', '#EE1D52', '#00A4EF',
    '#E60023', '#FF0000', '#7B68EE', '#FF8C00', '#20B2AA', '#DB7093',
]

# Well-known platform colours, used when a platform name is recognised.
KNOWN_PLATFORM_COLORS = {
    'Google Search': '#4285F4', 'MSN Search': '#00A4EF', 'Bing Search': '#00A4EF',
    'Facebook': '#1877F2', 'Instagram': '#E1306C', 'Reddit': '#FF4500',
    'StackAdapt': '#00C4A7', 'TikTok': '#EE1D52', 'Pinterest': '#E60023',
    'YouTube': '#FF0000', 'LinkedIn': '#0A66C2', 'Snapchat': '#FFFC00',
    'X (Twitter)': '#000000', 'Twitter': '#1DA1F2', 'Spotify': '#1DB954',
    'Amazon': '#FF9900', 'Display': '#5F6368', 'Programmatic': '#8E24AA',
}


# ----------------------------------------------------------------------------
# Taxonomy — the object Agent 1 produces and the user can edit
# ----------------------------------------------------------------------------

@dataclass
class Taxonomy:
    """Maps the campaign / site values in an export onto channels and platforms.

    Replaces the module-level CHANNEL_MAP / PLATFORM_MAP / MID_FUNNEL_PLATFORMS /
    SEARCH_PLATFORMS / PLATFORM_COLORS globals that generate_report.py mutated
    in place, so two clients can be analysed in one process without bleeding
    into each other.
    """

    channel_map: dict[str, str] = field(default_factory=dict)
    platform_map: dict[str, str] = field(default_factory=dict)
    mid_funnel_platforms: list[str] = field(default_factory=list)
    search_platforms: list[str] = field(default_factory=list)
    platform_colors: dict[str, str] = field(default_factory=dict)
    notes: str = ''

    def channel_for(self, campaign: Any) -> str:
        return self.channel_map.get(campaign, CHANNEL_OTHER)

    def platform_for(self, site: Any) -> str:
        return self.platform_map.get(site, CHANNEL_OTHER)

    def color_for(self, platform: str) -> str:
        if platform in self.platform_colors:
            return self.platform_colors[platform]
        if platform in KNOWN_PLATFORM_COLORS:
            return KNOWN_PLATFORM_COLORS[platform]
        return '#999999'

    def ordered_platforms(self, present: Iterable[str] | None = None) -> list[str]:
        """Search platforms first, then mid-funnel, then anything else. Used for
        consistent axis ordering across charts."""
        order = list(self.search_platforms) + [
            p for p in self.mid_funnel_platforms if p not in self.search_platforms
        ]
        if present is not None:
            present = list(dict.fromkeys(present))
            ordered = [p for p in order if p in present]
            ordered += [p for p in present if p not in ordered]
            return ordered
        return order

    def is_usable(self) -> bool:
        """A taxonomy is only useful if at least one campaign resolves to a real
        channel; otherwise every touch would collapse into 'Other'."""
        return any(v in (CHANNEL_SEARCH, CHANNEL_MID_FUNNEL) for v in self.channel_map.values())

    # -- round-trip helpers for the editable tables in the UI -----------------

    def campaign_rows(self) -> list[dict[str, str]]:
        return [{'Campaign': c, 'Channel': ch} for c, ch in sorted(self.channel_map.items())]

    def site_rows(self) -> list[dict[str, str]]:
        rows = []
        for site, platform in sorted(self.platform_map.items()):
            if platform in self.search_platforms:
                role = CHANNEL_SEARCH
            elif platform in self.mid_funnel_platforms:
                role = CHANNEL_MID_FUNNEL
            else:
                role = CHANNEL_OTHER
            rows.append({'Site (CM360)': site, 'Platform': platform, 'Funnel role': role})
        return rows

    @classmethod
    def from_rows(cls, campaign_rows, site_rows, notes: str = '') -> 'Taxonomy':
        channel_map, platform_map = {}, {}
        search, mid = [], []

        for row in campaign_rows:
            campaign = str(row.get('Campaign', '') or '').strip()
            channel = str(row.get('Channel', '') or '').strip()
            if campaign and channel in VALID_CHANNELS:
                channel_map[campaign] = channel

        for row in site_rows:
            site = str(row.get('Site (CM360)', '') or '').strip()
            platform = str(row.get('Platform', '') or '').strip()
            role = str(row.get('Funnel role', '') or '').strip()
            if not site or not platform:
                continue
            platform_map[site] = platform
            if role == CHANNEL_SEARCH and platform not in search:
                search.append(platform)
            elif role == CHANNEL_MID_FUNNEL and platform not in mid:
                mid.append(platform)

        colors = {}
        for i, platform in enumerate(dict.fromkeys(list(search) + list(mid))):
            colors[platform] = KNOWN_PLATFORM_COLORS.get(
                platform, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])

        return cls(channel_map=channel_map, platform_map=platform_map,
                   mid_funnel_platforms=mid, search_platforms=search,
                   platform_colors=colors, notes=notes)

    def taxonomy_table(self, touches: pd.DataFrame) -> pd.DataFrame:
        """Campaign / site / channel / platform combinations actually present."""
        return (touches[['campaign', 'site', 'channel', 'platform']]
                .drop_duplicates()
                .sort_values(['channel', 'platform'])
                .reset_index(drop=True))


# ----------------------------------------------------------------------------
# Export loading
# ----------------------------------------------------------------------------

@dataclass
class ExportInfo:
    """Everything learned from a CSV before the taxonomy exists."""
    path: str
    meta: dict[str, str]
    header_row: int
    n_slots: int
    campaigns: list[str]
    sites: list[str]
    n_rows: int
    activity: str
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None


def read_export_preamble(csv_path: str) -> tuple[dict[str, str], int]:
    """CM360/RDC exports prepend a metadata block ('Date Range', 'Activity', ...)
    before the real column header. Returns (preamble dict, header row index).
    Exports already cleaned in Sheets have no preamble, so the header is row 0."""
    meta: dict[str, str] = {}
    header_row = 0
    with open(csv_path, newline='', encoding='utf-8-sig', errors='replace') as f:
        for i, line in enumerate(f):
            if line.startswith('Conversion ID,'):
                header_row = i
                break
            parts = [p.strip().strip('"') for p in line.rstrip('\n').split(',')]
            if len(parts) >= 2 and parts[0] and parts[1]:
                meta[parts[0]] = parts[1]
            if i > 60:  # header should appear early; avoid scanning a huge file
                break
    return meta, header_row


def n_interaction_slots(df: pd.DataFrame) -> int:
    """How many 'Interaction N: ...' column blocks the export actually carries."""
    found = [int(m.group(1)) for c in df.columns
             if (m := re.match(r'Interaction (\d+): Campaign$', c))]
    return max(found) if found else 0


def load_data(csv_path: str, header_row: int = 0,
              period_start: pd.Timestamp | None = None) -> pd.DataFrame:
    raw = pd.read_csv(csv_path, skiprows=header_row, low_memory=False)
    df = raw[raw['Conversion ID'] != 'Grand Total:'].copy()
    df['Path Length'] = pd.to_numeric(df['Path Length'], errors='coerce').astype('Int64')
    df['Activity Date/Time'] = pd.to_datetime(df['Activity Date/Time'], errors='coerce')
    df = df[df['Activity Date/Time'].notna()].copy()
    if period_start is not None:
        df = df[df['Activity Date/Time'] >= period_start].copy()
    return df


def distinct_campaigns_and_sites(df: pd.DataFrame, slots: int) -> tuple[list[str], list[str]]:
    """Every campaign / site value appearing in any interaction slot. This is the
    input Agent 1 reasons over."""
    campaigns: set[str] = set()
    sites: set[str] = set()
    for i in range(1, slots + 1):
        camp_col = f'Interaction {i}: Campaign'
        site_col = f'Interaction {i}: Site (CM360)'
        if camp_col in df.columns:
            campaigns |= set(df[camp_col].dropna().astype(str).unique())
        if site_col in df.columns:
            sites |= set(df[site_col].dropna().astype(str).unique())
    clean = lambda values: sorted(v for v in values if v and v != NULL_TOKEN)
    return clean(campaigns), clean(sites)


class ExportValidationError(ValueError):
    """Raised when an upload does not look like a CM360 path-to-conversion export."""


REQUIRED_COLUMNS = ['Conversion ID', 'Activity Date/Time', 'Path Length']


def inspect_export(csv_path: str) -> ExportInfo:
    """Validate an upload and pull out everything needed before mapping."""
    meta, header_row = read_export_preamble(csv_path)

    try:
        head = pd.read_csv(csv_path, skiprows=header_row, nrows=5, low_memory=False)
    except Exception as exc:
        raise ExportValidationError(f"Could not parse the file as CSV: {exc}") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in head.columns]
    if missing:
        raise ExportValidationError(
            "This does not look like a CM360 path-to-conversion export. "
            f"Missing required column(s): {', '.join(missing)}."
        )

    slots = n_interaction_slots(head)
    if slots == 0:
        raise ExportValidationError(
            "No 'Interaction N: Campaign' columns found. Re-export from Campaign "
            "Manager with the path/interaction fields included."
        )

    df = load_data(csv_path, header_row)
    if df.empty:
        raise ExportValidationError("The export contains no conversion rows.")

    campaigns, sites = distinct_campaigns_and_sites(df, slots)
    activity = str(df['Activity'].dropna().iloc[0]) if 'Activity' in df.columns and df['Activity'].notna().any() else 'n/a'

    return ExportInfo(
        path=csv_path, meta=meta, header_row=header_row, n_slots=slots,
        campaigns=campaigns, sites=sites, n_rows=len(df), activity=activity,
        date_min=df['Activity Date/Time'].min(), date_max=df['Activity Date/Time'].max(),
    )


# ----------------------------------------------------------------------------
# Heuristic taxonomy — the fallback when Gemini is unavailable
# ----------------------------------------------------------------------------

SEARCH_HINTS = [
    ('google', 'Google Search'), ('msn', 'MSN Search'), ('bing', 'Bing Search'),
    ('yahoo', 'Yahoo Search'), ('sa360', 'Google Search'), ('dart search', 'Google Search'),
]
SOCIAL_HINTS = [
    ('facebook', 'Facebook'), (' fb', 'Facebook'), ('- fb', 'Facebook'), ('meta', 'Facebook'),
    ('instagram', 'Instagram'), ('reddit', 'Reddit'), ('tiktok', 'TikTok'),
    ('pinterest', 'Pinterest'), ('stackadapt', 'StackAdapt'), ('stack adapt', 'StackAdapt'),
    ('youtube', 'YouTube'), (' yt', 'YouTube'), ('linkedin', 'LinkedIn'),
    ('snapchat', 'Snapchat'), ('twitter', 'Twitter'), ('spotify', 'Spotify'),
    ('amazon', 'Amazon'), ('trade desk', 'The Trade Desk'), ('dv360', 'DV360'),
]


def infer_platform_name(site_value: str) -> str | None:
    """Infer a clean platform name from a raw site value, handling the common
    'Advertiser - Platform' and 'Engine : Platform' naming patterns."""
    if not site_value or site_value == NULL_TOKEN:
        return None

    low = site_value.lower()
    for needle, name in SEARCH_HINTS + SOCIAL_HINTS:
        if needle in low:
            return name

    # Generic fallback: strip the advertiser prefix and keep the trailing token.
    cleaned = re.split(r'\s*[:\-|]\s*', site_value)[-1].strip()
    return cleaned or site_value


def infer_channel(campaign: str) -> str:
    low = campaign.lower()
    if any(k in low for k in ('search', 'sem', 'ppc', 'brand kw', 'keyword', 'sa360', 'dart')):
        return CHANNEL_SEARCH
    if any(k in low for k in ('mid-funnel', 'mid funnel', 'midfunnel', 'awareness',
                              'social', 'display', 'video', 'prospecting', 'upper',
                              'consideration', 'reach')):
        return CHANNEL_MID_FUNNEL
    return CHANNEL_OTHER


def heuristic_taxonomy(campaigns: Iterable[str], sites: Iterable[str]) -> Taxonomy:
    """Best-effort taxonomy from name patterns alone, used when the mapping agent
    fails or its output is rejected."""
    campaigns, sites = list(campaigns), list(sites)
    channel_map = {c: infer_channel(c) for c in campaigns}

    # If nothing resolved, assume the largest campaign is search and the rest is
    # mid-funnel rather than collapsing everything into 'Other'.
    if not any(v != CHANNEL_OTHER for v in channel_map.values()) and campaigns:
        for c in campaigns:
            channel_map[c] = CHANNEL_SEARCH if 'search' in c.lower() else CHANNEL_MID_FUNNEL

    platform_map, search, mid = {}, [], []
    for site in sites:
        platform = infer_platform_name(site)
        if not platform:
            continue
        platform_map[site] = platform
        is_search = any(needle in site.lower() for needle, _ in SEARCH_HINTS) or 'search' in platform.lower()
        if is_search:
            if platform not in search:
                search.append(platform)
        elif platform not in mid:
            mid.append(platform)

    colors = {}
    for i, platform in enumerate(dict.fromkeys(search + mid)):
        colors[platform] = KNOWN_PLATFORM_COLORS.get(
            platform, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])

    return Taxonomy(channel_map=channel_map, platform_map=platform_map,
                    mid_funnel_platforms=mid, search_platforms=search,
                    platform_colors=colors,
                    notes='Derived from naming patterns (heuristic fallback).')


def unmapped_values(df: pd.DataFrame, slots: int, tax: Taxonomy) -> tuple[list[str], list[str]]:
    """Campaigns / sites present in the export but missing from the taxonomy, so a
    newly launched platform cannot silently land in 'Other'."""
    campaigns, sites = distinct_campaigns_and_sites(df, slots)
    return (sorted(set(campaigns) - set(tax.channel_map)),
            sorted(set(sites) - set(tax.platform_map)))


# ----------------------------------------------------------------------------
# Data pipeline
# ----------------------------------------------------------------------------

def build_touches(df: pd.DataFrame, tax: Taxonomy) -> pd.DataFrame:
    """Reshape the wide 'Interaction N: ...' blocks into one row per touch."""
    blocks = []
    for i in range(1, n_interaction_slots(df) + 1):
        cols = {
            'Conversion ID': 'Conversion ID',
            f'Interaction {i}: Interaction Date/Time': 'touch_time',
            f'Interaction {i}: Interaction Number': 'interaction_number',
            f'Interaction {i}: Campaign': 'campaign',
            f'Interaction {i}: Site (CM360)': 'site',
            f'Interaction {i}: Interaction Type': 'interaction_type',
        }
        if not all(c in df.columns for c in cols):
            continue
        sub = df[list(cols)].rename(columns=cols).dropna(subset=['site'])
        blocks.append(sub)

    if not blocks:
        raise ExportValidationError('No interaction columns could be reshaped into touches.')

    touches = pd.concat(blocks, ignore_index=True)
    touches = touches[touches['site'].astype(str) != NULL_TOKEN].copy()
    touches['touch_time'] = pd.to_datetime(touches['touch_time'], errors='coerce')
    touches = touches[touches['touch_time'].notna()].copy()
    touches['channel'] = touches['campaign'].map(tax.channel_for)
    touches['platform'] = touches['site'].map(tax.platform_for)
    touches = touches.sort_values(['Conversion ID', 'touch_time']).reset_index(drop=True)
    touches['touch_order'] = touches.groupby('Conversion ID').cumcount() + 1
    return touches


def classify_path(channel_set: set[str]) -> str:
    has_mf = CHANNEL_MID_FUNNEL in channel_set
    has_search = CHANNEL_SEARCH in channel_set
    if has_mf and has_search:
        return 'Mixed'
    if has_mf:
        return 'Mid-funnel-only'
    if has_search:
        return 'Search-only'
    return CHANNEL_OTHER


def build_paths(touches_df: pd.DataFrame, activity_df: pd.DataFrame) -> pd.DataFrame:
    """One row per conversion, with its ordered channel/platform sequence."""
    g = touches_df.groupby('Conversion ID', sort=False)

    first_touch = g[['channel', 'platform']].first().rename(
        columns={'channel': 'first_touch_channel', 'platform': 'first_touch_platform'})
    last_touch = g[['channel', 'platform']].last().rename(
        columns={'channel': 'last_touch_channel', 'platform': 'last_touch_platform'})
    first_time = g['touch_time'].first().rename('first_touch_time')

    paths = pd.concat([first_touch, last_touch, first_time], axis=1)
    paths['channel_sequence'] = g['channel'].apply(lambda s: ' > '.join(s))
    paths['platform_sequence'] = g['platform'].apply(lambda s: ' > '.join(s))
    paths['n_touches'] = g.size()
    paths['n_mid_funnel_touches'] = g['channel'].apply(lambda s: int((s == CHANNEL_MID_FUNNEL).sum()))
    paths['n_search_touches'] = g['channel'].apply(lambda s: int((s == CHANNEL_SEARCH).sum()))
    paths['path_type'] = g['channel'].apply(lambda s: classify_path(set(s)))

    def mf_then_search(sequence: str) -> bool:
        seq = sequence.split(' > ')
        if CHANNEL_MID_FUNNEL not in seq or CHANNEL_SEARCH not in seq:
            return False
        first_mf_idx = seq.index(CHANNEL_MID_FUNNEL)
        last_search_idx = len(seq) - 1 - seq[::-1].index(CHANNEL_SEARCH)
        return first_mf_idx < last_search_idx

    paths['mid_funnel_assisted_search'] = paths['channel_sequence'].map(mf_then_search)

    activity = activity_df.drop_duplicates(subset=['Conversion ID']).set_index('Conversion ID')
    paths = paths.merge(activity[['Activity Date/Time', 'Path Length']],
                        left_index=True, right_index=True)
    paths['days_to_convert'] = (
        paths['Activity Date/Time'] - paths['first_touch_time']
    ).dt.total_seconds() / 86400
    return paths.reset_index()


def build_touch_positions(touches: pd.DataFrame) -> pd.DataFrame:
    """Label each touch First / Middle / Last / Only touch within its path."""
    touches_pos = touches.merge(
        touches.groupby('Conversion ID').size().rename('path_len_touch'),
        left_on='Conversion ID', right_index=True)
    touches_pos['position'] = np.where(
        touches_pos['touch_order'] == 1, 'First',
        np.where(touches_pos['touch_order'] == touches_pos['path_len_touch'], 'Last', 'Middle')
    )
    touches_pos.loc[touches_pos['path_len_touch'] == 1, 'position'] = 'Only touch'
    return touches_pos


def compute_lag_days(touches: pd.DataFrame, mixed: pd.DataFrame) -> pd.Series:
    """Days from the first mid-funnel touch to the last Search touch, for
    mid-funnel-assisted Search conversions.

    Vectorised via groupby rather than the original per-conversion scan of the
    full touch table, which was quadratic on large exports.
    """
    if mixed.empty or 'mid_funnel_assisted_search' not in mixed.columns:
        return pd.Series(dtype='float64')

    assisted = set(mixed.loc[mixed['mid_funnel_assisted_search'], 'Conversion ID'])
    if not assisted:
        return pd.Series(dtype='float64')

    sub = touches[touches['Conversion ID'].isin(assisted)]
    first_mf = sub.loc[sub['channel'] == CHANNEL_MID_FUNNEL].groupby('Conversion ID')['touch_time'].min()
    last_search = sub.loc[sub['channel'] == CHANNEL_SEARCH].groupby('Conversion ID')['touch_time'].max()

    lag = ((last_search - first_mf).dropna().dt.total_seconds() / 86400)
    return lag[lag >= 0]


def platform_live_windows(touches: pd.DataFrame) -> pd.DataFrame:
    """First / last recorded touch per platform, straight from the data — replaces
    hardcoded activation dates so the narrative stays correct on every refresh."""
    w = touches.groupby('platform')['touch_time'].agg(['min', 'max', 'count'])
    w.columns = ['first_touch', 'last_touch', 'touches']
    return w.sort_values('touches', ascending=False)


def infer_steady_state_start(touches_full: pd.DataFrame) -> pd.Timestamp | None:
    """The day mid-funnel tagging first appears anywhere in the export.

    generate_report.py hardcoded 2026-06-26 for Rates.ca. Deriving it means the
    ramp-up trim is correct for any client: conversions before the first
    mid-funnel touch are Search-only by construction, not by consumer behaviour.
    """
    mf = touches_full[touches_full['channel'] == CHANNEL_MID_FUNNEL]
    if mf.empty:
        return None
    return mf['touch_time'].min().normalize()


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

class Metrics:
    """Container for every number referenced in the report narrative."""

    def __getattr__(self, name):  # only called when the attribute is absent
        raise AttributeError(
            f"Metric {name!r} was never computed. compute_metrics() must set it "
            f"before the narrative references it."
        )


def _safe_div(a, b):
    return a / b if b else float('nan')


def compute_metrics(df, touches, paths, touches_pos, mid_funnel_touches,
                    platform_volume, lag_days, tax: Taxonomy) -> Metrics:
    m = Metrics()
    m.n_conversions = len(paths)
    m.date_min = df['Activity Date/Time'].min()
    m.date_max = df['Activity Date/Time'].max()

    # Exports pulled with "Include Unattributed Conversions" carry rows with no
    # interactions at all (Path Length 0); every path metric below is computed on
    # the attributed subset, so both counts are reported for transparency.
    m.n_export_conversions = len(df)
    m.n_unattributed = m.n_export_conversions - m.n_conversions
    m.pct_attributed = _safe_div(m.n_conversions, m.n_export_conversions)
    m.activity_name = (str(df['Activity'].dropna().iloc[0])
                       if 'Activity' in df.columns and df['Activity'].notna().any() else 'n/a')
    m.live_windows = platform_live_windows(touches)

    counts = paths['path_type'].value_counts()
    pct = paths['path_type'].value_counts(normalize=True)
    m.n_search_only, m.pct_search_only = int(counts.get('Search-only', 0)), float(pct.get('Search-only', 0.0))
    m.n_mixed, m.pct_mixed = int(counts.get('Mixed', 0)), float(pct.get('Mixed', 0.0))
    m.n_mf_only, m.pct_mf_only = int(counts.get('Mid-funnel-only', 0)), float(pct.get('Mid-funnel-only', 0.0))

    mixed = paths[paths['path_type'] == 'Mixed'].copy()
    m.n_mixed_paths = len(mixed)
    m.n_classic = int(((mixed['first_touch_channel'] == CHANNEL_MID_FUNNEL)
                       & (mixed['last_touch_channel'] == CHANNEL_SEARCH)).sum())
    m.pct_classic = _safe_div(m.n_classic, m.n_mixed_paths)

    last_click_search = paths[paths['last_touch_channel'] == CHANNEL_SEARCH]
    m.n_last_click_search = len(last_click_search)
    m.n_assisted = int((last_click_search['n_mid_funnel_touches'] > 0).sum())
    m.pct_assisted = _safe_div(m.n_assisted, m.n_conversions)

    # Any mid-funnel touch (Mixed + Mid-funnel-only) — the headline "touched" number
    touched_mask = paths['n_mid_funnel_touches'] > 0
    m.n_mf_touched = int(touched_mask.sum())
    m.pct_mf_touched = _safe_div(m.n_mf_touched, m.n_conversions)
    m.n_untouched = m.n_conversions - m.n_mf_touched
    m.pct_untouched = _safe_div(m.n_untouched, m.n_conversions)

    # Of the touched paths, how many had at least one mid-funnel CLICK vs
    # impression-only (view-through)
    mf = touches[touches['channel'] == CHANNEL_MID_FUNNEL]
    if mf.empty:
        m.n_mf_with_click = 0
        m.first_mf_date = None
    else:
        mf_click = mf.groupby('Conversion ID')['interaction_type'].apply(lambda s: (s == 'Click').any())
        m.n_mf_with_click = int(mf_click.sum())
        m.first_mf_date = mf['touch_time'].min()
    m.n_mf_impr_only = m.n_mf_touched - m.n_mf_with_click
    m.pct_mf_impr_only = _safe_div(m.n_mf_impr_only, m.n_mf_touched)

    # Path length / velocity: any mid-funnel touch vs. search-only (never touched)
    m.touched_apl = float(paths.loc[touched_mask, 'Path Length'].mean())
    m.touched_days = float(paths.loc[touched_mask, 'days_to_convert'].mean())
    m.untouched_apl = float(paths.loc[~touched_mask, 'Path Length'].mean())
    m.untouched_days = float(paths.loc[~touched_mask, 'days_to_convert'].mean())

    m.by_type = paths.groupby('path_type').agg(
        conversions=('Conversion ID', 'count'),
        avg_path_length=('Path Length', 'mean'),
        avg_days_to_convert=('days_to_convert', 'mean'),
    ).round(2)

    m.platform_volume = platform_volume

    m.lag_days = lag_days
    m.lag_median = float(lag_days.median()) if len(lag_days) else float('nan')
    m.lag_mean = float(lag_days.mean()) if len(lag_days) else float('nan')
    m.pct_multi_day = float((lag_days >= 1).mean()) if len(lag_days) else float('nan')

    m.mixed = mixed
    m.taxonomy = tax.taxonomy_table(touches)
    m.mid_funnel_present = [p for p in tax.mid_funnel_platforms if p in m.live_windows.index]
    m.search_present = [p for p in tax.search_platforms if p in m.live_windows.index]

    # Defaults for the ramp-up context, overwritten by run_analysis when needed.
    m.has_rampup = False
    m.ctx_full_n = m.n_conversions
    m.ctx_full_pct_touched = m.pct_mf_touched
    m.ctx_full_pct_mixed = m.pct_mixed
    m.ctx_full_date_min = m.date_min
    m.ctx_full_date_max = m.date_max
    m.steady_state_start = None
    m.n_interaction_slots = 0
    return m


# ----------------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------------

def _save(fig, out_path):
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)
    return out_path


def chart_path_type(paths, out_path):
    counts = paths['path_type'].value_counts()
    pct = paths['path_type'].value_counts(normalize=True)
    order = [c for c in ['Search-only', 'Mixed', 'Mid-funnel-only'] if c in counts.index]
    if not order:
        order = list(counts.index)

    fig, ax = plt.subplots(figsize=(7, 5))
    counts.loc[order].plot(kind='bar', ax=ax, color=[COLORS_PT.get(x, 'gray') for x in order])
    ax.set_ylim(0, counts.max() * 1.15)
    for i, k in enumerate(order):
        ax.text(i, counts[k] + counts.max() * 0.02, f"{counts[k]:,}\n({pct[k]:.1%})",
                ha='center', fontsize=10)
    ax.set_title('Conversions by Path Type (Campaign Level)')
    ax.set_ylabel('Conversions')
    ax.set_xlabel('')
    plt.xticks(rotation=0)
    return _save(fig, out_path)


def chart_length_time(by_type, out_path):
    order = [o for o in ['Search-only', 'Mixed', 'Mid-funnel-only'] if o in by_type.index]
    if not order:
        order = list(by_type.index)

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    colors = [COLORS_PT.get(x, 'gray') for x in order]
    by_type.loc[order, 'avg_path_length'].plot(kind='bar', ax=axes[0], color=colors)
    axes[0].set_title('Avg. Path Length by Path Type')
    axes[0].set_ylabel('Touches')
    axes[0].set_xlabel('')
    axes[0].tick_params(axis='x', rotation=20)

    by_type.loc[order, 'avg_days_to_convert'].plot(kind='bar', ax=axes[1], color=colors)
    axes[1].set_title('Avg. Days From First Touch to Conversion')
    axes[1].set_ylabel('Days')
    axes[1].set_xlabel('')
    axes[1].tick_params(axis='x', rotation=20)
    return _save(fig, out_path)


def chart_position(mid_funnel_touches, out_path):
    if mid_funnel_touches.empty:
        return None, pd.DataFrame()
    position_dist = pd.crosstab(mid_funnel_touches['platform'],
                                mid_funnel_touches['position'], normalize='index').round(3)
    position_dist = position_dist.reindex(
        columns=[c for c in ['First', 'Middle', 'Last', 'Only touch'] if c in position_dist.columns],
        fill_value=0)

    fig, ax = plt.subplots(figsize=(8, 5))
    position_dist.plot(kind='bar', stacked=True, ax=ax,
                       color=['#4C72B0', '#DD8452', '#55A868', '#C44E52'][:position_dist.shape[1]])
    ax.set_title('Touch Position Distribution by Mid-Funnel Platform')
    ax.set_ylabel('Share of touches')
    ax.set_xlabel('')
    ax.legend(title='Position in path', bbox_to_anchor=(1.02, 1), loc='upper left')
    plt.xticks(rotation=20)
    _save(fig, out_path)
    return out_path, position_dist


def chart_flow_matrix(flow_counts, out_path):
    """Fallback for the Sankey: same first-to-last platform flows as a count matrix."""
    trans = flow_counts.pivot_table(index='first_touch_platform', columns='last_touch_platform',
                                    values='n', fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    im = ax.imshow(trans.values, cmap='Blues', aspect='auto')
    ax.set_xticks(range(len(trans.columns)))
    ax.set_xticklabels(trans.columns, rotation=45, ha='right')
    ax.set_yticks(range(len(trans.index)))
    ax.set_yticklabels(trans.index)
    for i in range(len(trans.index)):
        for j in range(len(trans.columns)):
            v = trans.values[i, j]
            if v > 0:
                ax.text(j, i, f"{int(v)}", ha='center', va='center', fontsize=9)
    ax.set_title('First Touch Platform -> Last (Converting) Touch Platform',
                 fontsize=12, fontweight='bold')
    ax.set_xlabel('Last (converting) touch platform')
    ax.set_ylabel('First touch platform')
    plt.colorbar(im, ax=ax, label='Conversions')
    return _save(fig, out_path)


def chart_sankey(paths, out_path, tax: Taxonomy, min_flow: int = 3):
    """Returns (chart path, flow counts). The flows are returned as well as drawn,
    so the narrative can reason over the same first-to-last movements the reader
    sees in the diagram."""
    multi = paths[paths['n_touches'] > 1].copy()
    if multi.empty:
        return None, pd.DataFrame()
    flow_counts = (multi.groupby(['first_touch_platform', 'last_touch_platform'])
                   .size().reset_index(name='n'))
    flow_counts = flow_counts[flow_counts['n'] >= min_flow]
    if flow_counts.empty:
        return None, pd.DataFrame()

    first_labels = sorted(flow_counts['first_touch_platform'].unique())
    last_labels = sorted(flow_counts['last_touch_platform'].unique())
    nodes = [f"{p} (first)" for p in first_labels] + [f"{p} (last)" for p in last_labels]
    node_idx = {n: i for i, n in enumerate(nodes)}

    fig = go.Figure(go.Sankey(
        node=dict(
            label=nodes, pad=15, thickness=18,
            color=[tax.color_for(p) for p in first_labels] + [tax.color_for(p) for p in last_labels],
        ),
        link=dict(
            source=[node_idx[f"{r.first_touch_platform} (first)"] for r in flow_counts.itertuples()],
            target=[node_idx[f"{r.last_touch_platform} (last)"] for r in flow_counts.itertuples()],
            value=[int(r.n) for r in flow_counts.itertuples()],
        )
    ))
    fig.update_layout(
        title=dict(text="First Touch Platform -> Last (Converting) Touch Platform",
                   font_size=15, x=0.5, xanchor='center'),
        font_size=13, width=1100, height=550, margin=dict(l=20, r=20, t=70, b=20),
    )
    try:
        fig.write_image(out_path, scale=2)
    except Exception:
        # Kaleido needs a Chrome install; fall back to the matplotlib matrix.
        chart_flow_matrix(flow_counts, out_path)
    return out_path, flow_counts


def chart_daily_mid_funnel(touches, out_path, tax: Taxonomy):
    """Daily touch volume per mid-funnel platform. Shades any leading stretch with
    no mid-funnel tagging at all, and marks platforms that launched mid-window, so
    the chart reads correctly whether or not the export covers an activation ramp-up."""
    daily = touches.copy()
    daily['day'] = daily['touch_time'].dt.date
    counts = daily.groupby(['day', 'platform']).size().unstack(fill_value=0)
    present = [p for p in tax.mid_funnel_platforms if p in counts.columns]

    fig, ax = plt.subplots(figsize=(12, 5))
    for p in present:
        ax.plot(counts.index, counts[p], marker='o', ms=3, label=p, color=tax.color_for(p))

    mf_total = counts[present].sum(axis=1) if present else pd.Series(dtype='int64')
    live_days = mf_total[mf_total > 0].index
    top = ax.get_ylim()[1]

    if len(live_days):
        first_live, day_one = min(live_days), counts.index.min()
        if (first_live - day_one).days > 1:
            ax.axvspan(day_one, first_live, alpha=0.1, color='gray')
            ax.text(day_one + (first_live - day_one) / 2, top * 0.9,
                    'No mid-funnel\ntagging yet', ha='center', fontsize=9, color='gray')

        for p in present:
            platform_days = counts[p][counts[p] > 0].index
            if len(platform_days) and (min(platform_days) - first_live).days > 7:
                start = min(platform_days)
                ax.axvline(start, color=tax.color_for(p), linestyle='--', alpha=0.6, lw=1)
                ax.text(start, top * 0.82, f' {p} starts', fontsize=8, color=tax.color_for(p))

    ax.set_title('Daily mid-funnel touches by platform (by touch date)')
    ax.set_ylabel('Touches')
    if present:
        ax.legend()
    fig.autofmt_xdate()
    _save(fig, out_path)
    return counts


def chart_lag_histogram(lag_days, out_path):
    if lag_days is None or len(lag_days) == 0:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(lag_days, bins=min(15, max(3, len(lag_days) // 2)), color='#DD8452', edgecolor='white')
    median_lag = lag_days.median()
    ax.axvline(median_lag, color='black', linestyle='--', label=f'Median = {median_lag:.1f} days')
    ax.set_title('Days Between First Mid-Funnel Touch and Converting Search Click\n'
                 '(Mid-Funnel-Assisted Search Conversions)')
    ax.set_xlabel('Days')
    ax.set_ylabel('Conversions')
    ax.legend()
    return _save(fig, out_path)


def collapse_sequence(seq_str: str) -> str:
    """Reddit > Reddit > Search  ->  Reddit > Search."""
    out: list[str] = []
    for p in seq_str.split(' > '):
        if not out or out[-1] != p:
            out.append(p)
    return ' > '.join(out)


def chart_top_paths(paths, out_path, tax: Taxonomy, level='platform', n_top=8):
    """DV360-style 'Top Converting Paths' chevron chart. Collapses each
    conversion's touch sequence into ordered distinct-consecutive steps, then
    ranks the most common journeys by share of conversions. Position 1
    (rightmost) = the converting (last) touch. Returns the ranked rows."""
    seq_col = 'platform_sequence' if level == 'platform' else 'channel_sequence'

    journeys = paths[seq_col].map(collapse_sequence)
    total = len(paths)
    top = journeys.value_counts().head(n_top)
    rows = [{'journey': j, 'conversions': int(c), 'pct': c / total} for j, c in top.items()]
    if not rows:
        return None, []

    seg_colors = {p: tax.color_for(p) for p in tax.ordered_platforms()}
    seg_colors.update({CHANNEL_SEARCH: '#4285F4', CHANNEL_MID_FUNNEL: '#FF7043',
                       CHANNEL_OTHER: '#B0B0B0'})
    short = {'Google Search': 'Google', 'MSN Search': 'MSN', 'Bing Search': 'Bing'}

    seqs = [r['journey'].split(' > ') for r in rows]
    max_len = max(len(s) for s in seqs)
    seg_w, gap, notch, h = 1.0, 0.06, 0.28, 0.72
    n_rows = len(rows)

    fig, ax = plt.subplots(figsize=(11, 0.72 * n_rows + 1.4))
    x_right = max_len
    for r_i, (row, seq) in enumerate(zip(rows, seqs)):
        y = n_rows - 1 - r_i
        rev = list(reversed(seq))  # rev[0] = last (converting) touch -> rightmost
        for i, label in enumerate(rev):
            x1 = x_right - i * (seg_w + gap)
            x0 = x1 - seg_w
            left_notch = notch if i < len(rev) - 1 else 0.0  # leftmost flat
            verts = [(x0, y - h / 2), (x1 - notch, y - h / 2), (x1, y),
                     (x1 - notch, y + h / 2), (x0, y + h / 2), (x0 + left_notch, y)]
            ax.add_patch(Polygon(verts, closed=True,
                                 facecolor=seg_colors.get(label, '#9AB4E8'),
                                 edgecolor='white', linewidth=1.5))
            ax.text((x0 + x1) / 2 + (notch / 2 if left_notch else 0), y,
                    short.get(label, label), ha='center', va='center',
                    color='white', fontsize=10, fontweight='bold')
        ax.text(x_right + 0.4, y, f"{row['pct'] * 100:.0f}%", ha='left', va='center',
                fontsize=13, fontweight='bold', color='#1a73e8')

    for pos in range(1, max_len + 1):
        xc = x_right - (pos - 1) * (seg_w + gap) - seg_w / 2
        ax.text(xc, -0.9, str(pos), ha='center', va='center', fontsize=10, color='#888')
    ax.text(x_right + 0.4, n_rows - 0.15, '% of Conv.', ha='left', va='center',
            fontsize=10, color='#555', fontweight='bold')
    ax.set_xlim(x_right - max_len * (seg_w + gap) - 0.8, x_right + 2.0)
    ax.set_ylim(-1.6, n_rows - 0.1)
    ax.axis('off')
    ax.set_title('Top Converting Paths, grouped by Platform',
                 fontsize=13, fontweight='bold', loc='left', pad=12)
    ax.text(x_right - max_len * (seg_w + gap) - 0.8, -1.45,
            'Ad exposures - position 1 = converting (last) touch',
            fontsize=8, style='italic', color='#999')
    _save(fig, out_path)
    return out_path, rows


def chart_transition_heatmap(touches, out_path, tax: Taxonomy):
    """Full sequential (Markov-style) transition analysis: for every consecutive
    touch pair in every path, what platform comes next? Row-normalized, so the
    diagonal is platform loyalty and off-diagonal is cross-platform migration."""
    present = touches['platform'].dropna().unique().tolist()
    order = tax.ordered_platforms(present)
    if not order:
        return None, pd.DataFrame()

    t = touches.sort_values(['Conversion ID', 'touch_order']).copy()
    t['next_platform'] = t.groupby('Conversion ID')['platform'].shift(-1)
    transitions = t.dropna(subset=['next_platform'])
    if transitions.empty:
        return None, pd.DataFrame()

    trans = (pd.crosstab(transitions['platform'], transitions['next_platform'], normalize='index')
             .reindex(index=order, columns=order).fillna(0))

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(trans.values, cmap='YlOrRd', vmin=0, vmax=1)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(order, rotation=45, ha='right')
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    for i in range(len(order)):
        for j in range(len(order)):
            v = trans.values[i, j]
            if v > 0:
                ax.text(j, i, f"{v:.0%}", ha='center', va='center', fontsize=8,
                        color='black' if v < 0.5 else 'white')
    ax.set_title('Platform -> Next-Touch Platform Transition Probability (Row %)')
    ax.set_xlabel('Next touch platform')
    ax.set_ylabel('Current touch platform')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    _save(fig, out_path)
    return out_path, trans


# ----------------------------------------------------------------------------
# Orchestrated analysis
# ----------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    metrics: Metrics
    paths: pd.DataFrame
    touches: pd.DataFrame
    charts: dict[str, str]
    top_paths_rows: list[dict]
    transition_matrix: pd.DataFrame
    position_dist: pd.DataFrame
    charts_dir: str
    # The data behind every chart is kept, not just the PNG, so the narrative can
    # be grounded in the same figures the reader is looking at.
    daily_counts: pd.DataFrame = field(default_factory=pd.DataFrame)
    flow_counts: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)


CHART_FILENAMES = {
    'daily_mf': '01_mid_funnel_timeseries.png',
    'path_type': '02_path_type.png',
    'top_paths': '03_top_paths.png',
    'heatmap': '04_heatmap.png',
    'length_time': '05_length_time.png',
    'position': '06_position.png',
    'sankey': '07_sankey.png',
    'lag': '08_lag_histogram.png',
}


def output_paths(date_min, date_max, base_dir: str | None = None) -> tuple[str, str]:
    """Outputs are named after the analysis window, so re-running on a refreshed
    export never overwrites a previous period's deliverable."""
    base_dir = base_dir or REPORTS_DIR
    slug = f"{date_min:%Y%m%d}_{date_max:%Y%m%d}"
    charts_dir = os.path.join(base_dir, f"charts_{slug}")
    os.makedirs(charts_dir, exist_ok=True)
    return charts_dir, os.path.join(base_dir, f"Path_to_Conversion_Report_{slug}.pdf")


def run_analysis(csv_path: str, tax: Taxonomy, header_row: int = 0,
                 steady_state_start: pd.Timestamp | None = None,
                 trim_rampup: bool = True,
                 base_dir: str | None = None,
                 progress: Callable[[str], None] | None = None) -> AnalysisResult:
    """Full deterministic pipeline: load, reshape, compute metrics, draw charts.

    steady_state_start: pass None to derive it from the data (first mid-funnel
    touch). Conversions before it are Search-only by construction and would drag
    every mid-funnel metric toward zero.
    """
    say = progress or (lambda _msg: None)
    warnings: list[str] = []

    say('Loading export')
    df_full = load_data(csv_path, header_row)
    slots = n_interaction_slots(df_full)

    bad_campaigns, bad_sites = unmapped_values(df_full, slots, tax)
    for c in bad_campaigns:
        warnings.append(f"Campaign not in taxonomy, treated as 'Other': {c}")
    for s in bad_sites:
        warnings.append(f"Site not in taxonomy, treated as 'Other': {s}")

    say('Reshaping touches')
    touches_full = build_touches(df_full, tax)
    paths_full = build_paths(
        touches_full, df_full[['Conversion ID', 'Activity Date/Time', 'Path Length']])

    if steady_state_start is None and trim_rampup:
        steady_state_start = infer_steady_state_start(touches_full)

    has_rampup = bool(
        trim_rampup and steady_state_start is not None
        and df_full['Activity Date/Time'].min() < steady_state_start
    )

    if has_rampup:
        say(f'Trimming pre-activation weeks (before {steady_state_start:%Y-%m-%d})')
        df = load_data(csv_path, header_row, steady_state_start)
        touches = build_touches(df, tax)
        paths = build_paths(touches, df[['Conversion ID', 'Activity Date/Time', 'Path Length']])
    else:
        df, touches, paths = df_full, touches_full, paths_full

    if paths.empty:
        raise ExportValidationError(
            'No attributed conversions remain after mapping. Check the taxonomy: '
            'every campaign may have resolved to "Other".')

    say('Computing metrics')
    touches_pos = build_touch_positions(touches)
    mid_funnel_touches = touches_pos[touches_pos['channel'] == CHANNEL_MID_FUNNEL].copy()

    if mid_funnel_touches.empty:
        platform_volume = pd.DataFrame(
            columns=['touches', 'conversions_influenced', 'pct_of_all_conversions'])
        warnings.append('No mid-funnel touches found with this taxonomy; '
                        'mid-funnel sections will be sparse.')
    else:
        platform_volume = mid_funnel_touches.groupby('platform').agg(
            touches=('Conversion ID', 'count'),
            conversions_influenced=('Conversion ID', 'nunique'),
        ).sort_values('touches', ascending=False)
        platform_volume['pct_of_all_conversions'] = (
            platform_volume['conversions_influenced'] / len(paths))

    mixed = paths[paths['path_type'] == 'Mixed'].copy()
    lag_days = compute_lag_days(touches, mixed)

    m = compute_metrics(df, touches, paths, touches_pos, mid_funnel_touches,
                        platform_volume, lag_days, tax)
    m.has_rampup = has_rampup
    m.n_interaction_slots = slots
    m.steady_state_start = steady_state_start

    if has_rampup:
        m.ctx_full_n = len(paths_full)
        m.ctx_full_pct_touched = float((paths_full['n_mid_funnel_touches'] > 0).mean())
        m.ctx_full_pct_mixed = float((paths_full['path_type'] == 'Mixed').mean())
        m.ctx_full_date_min = df_full['Activity Date/Time'].min()
        m.ctx_full_date_max = df_full['Activity Date/Time'].max()
        mf_full = touches_full[touches_full['channel'] == CHANNEL_MID_FUNNEL]
        if not mf_full.empty:
            m.first_mf_date = mf_full['touch_time'].min()  # true first touch, pre-cut

    charts_dir, _ = output_paths(m.date_min, m.date_max, base_dir)
    p = {k: os.path.join(charts_dir, v) for k, v in CHART_FILENAMES.items()}

    say('Drawing charts')
    charts: dict[str, str] = {}
    daily_counts = chart_daily_mid_funnel(touches_full, p['daily_mf'], tax)
    charts['daily_mf'] = p['daily_mf']
    charts['path_type'] = chart_path_type(paths, p['path_type'])

    top_chart, top_paths_rows = chart_top_paths(paths, p['top_paths'], tax, level='platform')
    if top_chart:
        charts['top_paths'] = top_chart

    heat_chart, transition_matrix = chart_transition_heatmap(touches, p['heatmap'], tax)
    if heat_chart:
        charts['heatmap'] = heat_chart

    charts['length_time'] = chart_length_time(m.by_type, p['length_time'])

    pos_chart, position_dist = chart_position(mid_funnel_touches, p['position'])
    if pos_chart:
        charts['position'] = pos_chart

    sankey, flow_counts = chart_sankey(paths, p['sankey'], tax)
    if sankey:
        charts['sankey'] = sankey

    lag_chart = chart_lag_histogram(lag_days, p['lag'])
    if lag_chart:
        charts['lag'] = lag_chart

    say('Analysis complete')
    return AnalysisResult(
        metrics=m, paths=paths, touches=touches, charts=charts,
        top_paths_rows=top_paths_rows, transition_matrix=transition_matrix,
        position_dist=position_dist, charts_dir=charts_dir,
        daily_counts=daily_counts, flow_counts=flow_counts, warnings=warnings,
    )
