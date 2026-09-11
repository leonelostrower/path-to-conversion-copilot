"""
Generate an executive-summary Word report for the Path-to-Conversion analysis.

Rebuilds the same data pipeline used in QBR_rates.ipynb directly from the raw
CM360 export, regenerates a curated set of charts, and assembles a .docx
report with findings, charts, and analysis. Safe to re-run any time the
underlying CSV is refreshed — all numbers are computed live, never hardcoded.

The .docx follows the layout of the 2026 Q2 QBR deliverable: .monks cover,
Helvetica Neue type scale, green-header tables and captioned figures.

Usage:
    python3 generate_report.py [path/to/export.csv]
"""

import os
import re
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plotly.graph_objects as go

from matplotlib.patches import Polygon

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
REPORTS_DIR = os.path.join(ROOT, 'output', 'reports')
LOGO_PATH = os.path.join(ROOT, 'assets', 'monks_logo.png')


def latest_export():
    """Newest CSV in data/, so a refreshed export is picked up with no edits here.
    Pass a path as the first argument to report on a specific export instead."""
    csvs = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.lower().endswith('.csv')]
    if not csvs:
        raise SystemExit(f"No CSV exports found in {DATA_DIR}")
    return max(csvs, key=os.path.getmtime)


CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else latest_export()

REPORT_SUBTITLE = '2026 Q3: Quarterly Business Review'
# Date all three original mid-funnel platforms were live and tagged. Exports that
# already start on/after this date need no ramp-up caveat.
STEADY_STATE_START = pd.Timestamp('2026-06-26')

plt.rcParams['figure.figsize'] = (10, 5)
plt.rcParams['savefig.dpi'] = 150

COLORS_PT = {'Search-only': '#4C72B0', 'Mixed': '#DD8452', 'Mid-funnel-only': '#55A868'}
PLATFORM_COLORS = {
    'Google Search': '#4285F4', 'MSN Search': '#00A4EF', 'Facebook': '#1877F2',
    'Reddit': '#FF4500', 'StackAdapt': '#00C4A7', 'TikTok': '#EE1D52',
}

CHANNEL_MAP = {'DART Search': 'Search', 'Auto Mid-funnel 2026': 'Mid-funnel'}
PLATFORM_MAP = {
    'DART Search : Google': 'Google Search',
    'DART Search : MSN': 'MSN Search',
    'Rates.ca - FB': 'Facebook',
    'Rates.ca - Reddit': 'Reddit',
    'Rates.ca - StackAdapt': 'StackAdapt',
    'Rates.ca - TikTok': 'TikTok',
}
MID_FUNNEL_PLATFORMS = ['Facebook', 'Reddit', 'StackAdapt', 'TikTok']
SEARCH_PLATFORMS = ['Google Search', 'MSN Search']


def channel_for(campaign):
    return CHANNEL_MAP.get(campaign, 'Other')


def platform_for(site):
    return PLATFORM_MAP.get(site, 'Other')


# ----------------------------------------------------------------------------
# Data pipeline (mirrors QBR_rates.ipynb)
# ----------------------------------------------------------------------------

def read_export_preamble():
    """CM360/RDC exports prepend a metadata block ('Date Range', 'Activity', ...)
    before the real column header. Returns (preamble dict, header row index).
    Exports already cleaned in Sheets have no preamble, so the header is row 0."""
    meta, header_row = {}, 0
    with open(CSV_PATH, newline='') as f:
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


EXPORT_META, HEADER_ROW = read_export_preamble()


def output_paths(date_min, date_max):
    """Outputs are named after the analysis window, so re-running on a refreshed
    export never overwrites a previous period's deliverable."""
    slug = f"{date_min:%Y%m%d}_{date_max:%Y%m%d}"
    charts_dir = os.path.join(REPORTS_DIR, f"charts_{slug}")
    os.makedirs(charts_dir, exist_ok=True)
    return charts_dir, os.path.join(REPORTS_DIR, f"QBR_Path_to_Conversion_Report_{slug}.docx")


def load_data(period_start=None):
    raw = pd.read_csv(CSV_PATH, skiprows=HEADER_ROW, low_memory=False)
    df = raw[raw['Conversion ID'] != 'Grand Total:'].copy()
    df['Path Length'] = pd.to_numeric(df['Path Length'], errors='coerce').astype('Int64')
    df['Activity Date/Time'] = pd.to_datetime(df['Activity Date/Time'])
    if period_start is not None:
        df = df[df['Activity Date/Time'] >= period_start].copy()
    return df


def n_interaction_slots(df):
    """How many 'Interaction N: ...' column blocks the export actually carries."""
    found = [int(m.group(1)) for c in df.columns
             if (m := re.match(r'Interaction (\d+): Campaign$', c))]
    return max(found) if found else 0


def infer_platform_name(site_value):
    """Infer a clean platform name from a site value. Handles common naming patterns."""
    if not site_value or site_value == '---':
        return None
    
    # Already mapped or in special cases
    if site_value in PLATFORM_MAP:
        return PLATFORM_MAP[site_value]
    
    # Try to infer from common patterns
    if 'Google' in site_value:
        return 'Google Search'
    elif 'MSN' in site_value:
        return 'MSN Search'
    elif 'Facebook' in site_value or 'FB' in site_value:
        return 'Facebook'
    elif 'Reddit' in site_value:
        return 'Reddit'
    elif 'TikTok' in site_value:
        return 'TikTok'
    elif 'Pinterest' in site_value:
        return 'Pinterest'
    elif 'StackAdapt' in site_value or 'Stack' in site_value:
        return 'StackAdapt'
    elif 'YouTube' in site_value or 'YT' in site_value:
        return 'YouTube'
    else:
        # Generic fallback: capitalize and clean up
        return site_value.replace('Rates.ca - ', '').replace('DART Search : ', '')


def auto_map_platforms(df, slots):
    """Auto-detect new platforms and update PLATFORM_MAP / MID_FUNNEL_PLATFORMS.
    Returns True if new platforms were added, False otherwise."""
    global PLATFORM_MAP, MID_FUNNEL_PLATFORMS, PLATFORM_COLORS
    
    sites = set()
    for i in range(1, slots + 1):
        sites |= set(df[f'Interaction {i}: Site (CM360)'].dropna().unique())
    
    new_platforms_added = False
    
    for site in sorted(sites):
        if site not in PLATFORM_MAP or site == '---':
            if site == '---':
                continue
            
            inferred = infer_platform_name(site)
            if inferred and inferred not in PLATFORM_MAP.values():
                PLATFORM_MAP[site] = inferred
                new_platforms_added = True
                
                # Auto-classify: if it's not a Search platform, add to mid-funnel
                if inferred not in SEARCH_PLATFORMS and inferred not in MID_FUNNEL_PLATFORMS:
                    MID_FUNNEL_PLATFORMS.append(inferred)
                    # Assign a default color if missing
                    if inferred not in PLATFORM_COLORS:
                        PLATFORM_COLORS[inferred] = '#999999'
                    
                    print(f"  [NEW] Added '{inferred}' to mid-funnel platforms")
                else:
                    print(f"  [NEW] Mapped '{site}' -> '{inferred}'")
    
    return new_platforms_added


def unmapped_values(df, slots):
    """Campaigns / sites present in the export but missing from the taxonomy —
    surfaced on every run so a newly launched platform can't slip through as 'Other'."""
    camps, sites = set(), set()
    for i in range(1, slots + 1):
        camps |= set(df[f'Interaction {i}: Campaign'].dropna().unique())
        sites |= set(df[f'Interaction {i}: Site (CM360)'].dropna().unique())
    
    # Filter out '---' (placeholder/null marker) from results
    unmapped_sites = sorted((sites - set(PLATFORM_MAP)) - {'---'})
    unmapped_camps = sorted((camps - set(CHANNEL_MAP)) - {'---'})
    
    return unmapped_camps, unmapped_sites


def build_touches(df):
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
        sub = df[list(cols.keys())].rename(columns=cols).dropna(subset=['site'])
        blocks.append(sub)

    touches = pd.concat(blocks, ignore_index=True)
    touches['touch_time'] = pd.to_datetime(touches['touch_time'])
    touches['channel'] = touches['campaign'].map(channel_for)
    touches['platform'] = touches['site'].map(platform_for)
    touches = touches.sort_values(['Conversion ID', 'touch_time']).reset_index(drop=True)
    touches['touch_order'] = touches.groupby('Conversion ID').cumcount() + 1
    return touches


def build_paths(touches_df, activity_df):
    g = touches_df.groupby('Conversion ID', sort=False)

    first_touch = g.first()[['channel', 'platform']].rename(
        columns={'channel': 'first_touch_channel', 'platform': 'first_touch_platform'})
    last_touch = g.last()[['channel', 'platform']].rename(
        columns={'channel': 'last_touch_channel', 'platform': 'last_touch_platform'})
    first_time = g['touch_time'].first().rename('first_touch_time')

    channel_seq = g['channel'].apply(lambda s: ' > '.join(s))
    platform_seq = g['platform'].apply(lambda s: ' > '.join(s))
    channels_present = g['channel'].apply(lambda s: set(s))

    paths = pd.concat([first_touch, last_touch, first_time], axis=1)
    paths['channel_sequence'] = channel_seq
    paths['platform_sequence'] = platform_seq
    paths['n_touches'] = g.size()
    paths['n_mid_funnel_touches'] = g['channel'].apply(lambda s: (s == 'Mid-funnel').sum())
    paths['n_search_touches'] = g['channel'].apply(lambda s: (s == 'Search').sum())

    def classify(ch_set):
        has_mf = 'Mid-funnel' in ch_set
        has_search = 'Search' in ch_set
        if has_mf and has_search:
            return 'Mixed'
        elif has_mf:
            return 'Mid-funnel-only'
        elif has_search:
            return 'Search-only'
        return 'Other'
    paths['path_type'] = channels_present.apply(classify)

    def mf_then_search(row):
        seq = row['channel_sequence'].split(' > ')
        if 'Mid-funnel' not in seq or 'Search' not in seq:
            return False
        first_mf_idx = seq.index('Mid-funnel')
        last_search_idx = len(seq) - 1 - seq[::-1].index('Search')
        return first_mf_idx < last_search_idx
    paths['mid_funnel_assisted_search'] = paths.apply(mf_then_search, axis=1)

    paths = paths.merge(activity_df.set_index('Conversion ID')[['Activity Date/Time', 'Path Length']],
                         left_index=True, right_index=True)
    paths['days_to_convert'] = (paths['Activity Date/Time'] - paths['first_touch_time']).dt.total_seconds() / 86400
    return paths.reset_index()


def build_touch_positions(touches):
    touches_pos = touches.merge(
        touches.groupby('Conversion ID').size().rename('path_len_touch'),
        left_on='Conversion ID', right_index=True)
    touches_pos['position'] = np.where(
        touches_pos['touch_order'] == 1, 'First',
        np.where(touches_pos['touch_order'] == touches_pos['path_len_touch'], 'Last', 'Middle')
    )
    touches_pos.loc[touches_pos['path_len_touch'] == 1, 'position'] = 'Only touch'
    return touches_pos


def compute_lag_days(touches, mixed):
    def compute_lag(conv_id):
        sub = touches[touches['Conversion ID'] == conv_id]
        mf_times = sub.loc[sub['channel'] == 'Mid-funnel', 'touch_time']
        search_times = sub.loc[sub['channel'] == 'Search', 'touch_time']
        if mf_times.empty or search_times.empty:
            return np.nan
        return (search_times.max() - mf_times.min()).total_seconds() / 86400

    assisted_convs = mixed.loc[mixed['mid_funnel_assisted_search'], 'Conversion ID']
    lag_days = assisted_convs.apply(compute_lag)
    return lag_days[lag_days >= 0]


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

class Metrics:
    """Container for every number referenced in the report narrative."""
    pass


def platform_live_windows(touches):
    """First / last recorded touch per platform, straight from the data — replaces
    hardcoded activation dates so the narrative stays correct on every refresh."""
    w = touches.groupby('platform')['touch_time'].agg(['min', 'max', 'count'])
    w.columns = ['first_touch', 'last_touch', 'touches']
    return w.sort_values('touches', ascending=False)


def compute_metrics(df, touches, paths, touches_pos, mid_funnel_touches, platform_volume, lag_days):
    m = Metrics()
    m.n_conversions = len(paths)
    m.date_min = df['Activity Date/Time'].min()
    m.date_max = df['Activity Date/Time'].max()

    # Exports pulled with "Include Unattributed Conversions" carry rows with no
    # interactions at all (Path Length 0); every path metric below is computed on
    # the attributed subset, so both counts are reported for transparency.
    m.n_export_conversions = len(df)
    m.n_unattributed = m.n_export_conversions - m.n_conversions
    m.pct_attributed = m.n_conversions / m.n_export_conversions if m.n_export_conversions else float('nan')
    m.activity_name = df['Activity'].dropna().iloc[0] if 'Activity' in df and len(df) else 'n/a'
    m.live_windows = platform_live_windows(touches)

    counts = paths['path_type'].value_counts()
    pct = paths['path_type'].value_counts(normalize=True)
    m.n_search_only, m.pct_search_only = counts.get('Search-only', 0), pct.get('Search-only', 0)
    m.n_mixed, m.pct_mixed = counts.get('Mixed', 0), pct.get('Mixed', 0)
    m.n_mf_only, m.pct_mf_only = counts.get('Mid-funnel-only', 0), pct.get('Mid-funnel-only', 0)

    mixed = paths[paths['path_type'] == 'Mixed'].copy()
    m.n_mixed_paths = len(mixed)
    m.n_classic = int(((mixed['first_touch_channel'] == 'Mid-funnel') & (mixed['last_touch_channel'] == 'Search')).sum())
    m.pct_classic = m.n_classic / m.n_mixed_paths if m.n_mixed_paths else float('nan')

    last_click_search = paths[paths['last_touch_channel'] == 'Search']
    m.n_last_click_search = len(last_click_search)
    m.n_assisted = int((last_click_search['n_mid_funnel_touches'] > 0).sum())
    m.pct_assisted = m.n_assisted / m.n_conversions

    # Any mid-funnel touch (Mixed + Mid-funnel-only) — the headline "touched" number
    touched_mask = paths['n_mid_funnel_touches'] > 0
    m.n_mf_touched = int(touched_mask.sum())
    m.pct_mf_touched = m.n_mf_touched / m.n_conversions
    m.n_untouched = m.n_conversions - m.n_mf_touched
    m.pct_untouched = m.n_untouched / m.n_conversions

    # Of the touched paths, how many had at least one mid-funnel CLICK vs impression-only (view-through)
    mf = touches[touches['channel'] == 'Mid-funnel']
    mf_click = mf.groupby('Conversion ID')['interaction_type'].apply(lambda s: (s == 'Click').any())
    m.n_mf_with_click = int(mf_click.sum())
    m.n_mf_impr_only = m.n_mf_touched - m.n_mf_with_click
    m.pct_mf_impr_only = m.n_mf_impr_only / m.n_mf_touched if m.n_mf_touched else float('nan')
    m.first_mf_date = mf['touch_time'].min()

    # Path length / velocity: any mid-funnel touch vs. search-only (never touched)
    m.touched_apl = paths.loc[touched_mask, 'Path Length'].mean()
    m.touched_days = paths.loc[touched_mask, 'days_to_convert'].mean()
    m.untouched_apl = paths.loc[~touched_mask, 'Path Length'].mean()
    m.untouched_days = paths.loc[~touched_mask, 'days_to_convert'].mean()

    by_type = paths.groupby('path_type').agg(
        conversions=('Conversion ID', 'count'),
        avg_path_length=('Path Length', 'mean'),
        avg_days_to_convert=('days_to_convert', 'mean'),
    ).round(2)
    m.by_type = by_type

    m.platform_volume = platform_volume

    m.lag_days = lag_days
    m.lag_median = lag_days.median()
    m.lag_mean = lag_days.mean()
    m.pct_multi_day = (lag_days >= 1).mean()

    # Full-window vs. post-activation context (ctx_full_*) is attached in main(),
    # since it requires the unfiltered export.

    m.mixed = mixed
    return m


# ----------------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------------

def chart_path_type(paths, out_path):
    counts = paths['path_type'].value_counts()
    pct = paths['path_type'].value_counts(normalize=True)
    order = [c for c in ['Search-only', 'Mixed', 'Mid-funnel-only'] if c in counts.index]

    fig, ax = plt.subplots(figsize=(7, 5))
    counts.loc[order].plot(kind='bar', ax=ax, color=[COLORS_PT.get(x, 'gray') for x in order])
    ax.set_ylim(0, counts.max() * 1.15)
    for i, k in enumerate(order):
        ax.text(i, counts[k] + counts.max() * 0.02, f"{counts[k]:,}\n({pct[k]:.1%})", ha='center', fontsize=10)
    ax.set_title('Conversions by Path Type (Campaign Level)')
    ax.set_ylabel('Conversions')
    ax.set_xlabel('')
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)


def chart_length_time(by_type, out_path):
    order = [o for o in ['Search-only', 'Mixed', 'Mid-funnel-only'] if o in by_type.index]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    by_type.loc[order, 'avg_path_length'].plot(kind='bar', ax=axes[0], color=[COLORS_PT.get(x, 'gray') for x in order])
    axes[0].set_title('Avg. Path Length by Path Type')
    axes[0].set_ylabel('Touches')
    axes[0].set_xlabel('')
    axes[0].tick_params(axis='x', rotation=20)

    by_type.loc[order, 'avg_days_to_convert'].plot(kind='bar', ax=axes[1], color=[COLORS_PT.get(x, 'gray') for x in order])
    axes[1].set_title('Avg. Days From First Touch to Conversion')
    axes[1].set_ylabel('Days')
    axes[1].set_xlabel('')
    axes[1].tick_params(axis='x', rotation=20)

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)


def chart_position(mid_funnel_touches, out_path):
    position_dist = pd.crosstab(mid_funnel_touches['platform'], mid_funnel_touches['position'], normalize='index').round(3)
    position_dist = position_dist.reindex(
        columns=[c for c in ['First', 'Middle', 'Last', 'Only touch'] if c in position_dist.columns], fill_value=0)

    fig, ax = plt.subplots(figsize=(8, 5))
    position_dist.plot(kind='bar', stacked=True, ax=ax, color=['#4C72B0', '#DD8452', '#55A868', '#C44E52'])
    ax.set_title('Touch Position Distribution by Mid-Funnel Platform')
    ax.set_ylabel('Share of touches')
    ax.set_xlabel('')
    ax.legend(title='Position in path', bbox_to_anchor=(1.02, 1), loc='upper left')
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)
    return position_dist


def chart_sankey(paths, out_path):
    multi = paths[paths['n_touches'] > 1].copy()
    flow_counts = multi.groupby(['first_touch_platform', 'last_touch_platform']).size().reset_index(name='n')
    flow_counts = flow_counts[flow_counts['n'] >= 3]

    first_labels = sorted(flow_counts['first_touch_platform'].unique())
    last_labels = sorted(flow_counts['last_touch_platform'].unique())
    nodes = [f"{p} (first)" for p in first_labels] + [f"{p} (last)" for p in last_labels]
    node_idx = {n: i for i, n in enumerate(nodes)}

    fig = go.Figure(go.Sankey(
        node=dict(
            label=nodes, pad=15, thickness=18,
            color=[PLATFORM_COLORS.get(p, '#999') for p in first_labels] + [PLATFORM_COLORS.get(p, '#999') for p in last_labels],
        ),
        link=dict(
            source=[node_idx[f"{r.first_touch_platform} (first)"] for r in flow_counts.itertuples()],
            target=[node_idx[f"{r.last_touch_platform} (last)"] for r in flow_counts.itertuples()],
            value=[r.n for r in flow_counts.itertuples()],
        )
    ))
    fig.update_layout(
        title=dict(text="First Touch Platform -> Last (Converting) Touch Platform", font_size=15, x=0.5, xanchor='center'),
        font_size=13, width=1100, height=550, margin=dict(l=20, r=20, t=70, b=20),
    )
    try:
        fig.write_image(out_path, scale=2)
    except Exception as exc:  # Kaleido needs a Chrome install; fall back to matplotlib
        print(f"  (Sankey via Kaleido unavailable: {type(exc).__name__} — drawing matplotlib fallback)")
        chart_flow_matrix(flow_counts, out_path)


def chart_flow_matrix(flow_counts, out_path):
    """Fallback for the Sankey: same first-to-last platform flows as a count matrix."""
    trans = flow_counts.pivot_table(index='first_touch_platform', columns='last_touch_platform',
                                    values='n', fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    im = ax.imshow(trans.values, cmap='Blues', aspect='auto')
    ax.set_xticks(range(len(trans.columns))); ax.set_xticklabels(trans.columns, rotation=45, ha='right')
    ax.set_yticks(range(len(trans.index))); ax.set_yticklabels(trans.index)
    for i in range(len(trans.index)):
        for j in range(len(trans.columns)):
            v = trans.values[i, j]
            if v > 0:
                ax.text(j, i, f"{int(v)}", ha='center', va='center', fontsize=9)
    ax.set_title('First Touch Platform -> Last (Converting) Touch Platform', fontsize=12, fontweight='bold')
    ax.set_xlabel('Last (converting) touch platform')
    ax.set_ylabel('First touch platform')
    plt.colorbar(im, ax=ax, label='Conversions')
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)


def chart_daily_mid_funnel(touches, out_path):
    """Daily touch volume per mid-funnel platform. Shades any leading stretch with
    no mid-funnel tagging at all, and marks platforms that launched mid-window, so
    the chart reads correctly whether or not the export covers an activation ramp-up."""
    daily = touches.copy()
    daily['day'] = daily['touch_time'].dt.date
    counts = daily.groupby(['day', 'platform']).size().unstack(fill_value=0)
    present = [p for p in MID_FUNNEL_PLATFORMS if p in counts.columns]

    fig, ax = plt.subplots(figsize=(12, 5))
    for p in present:
        ax.plot(counts.index, counts[p], marker='o', ms=3, label=p, color=PLATFORM_COLORS.get(p))

    mf_total = counts[present].sum(axis=1) if present else pd.Series(dtype=int)
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
                ax.axvline(start, color=PLATFORM_COLORS.get(p), linestyle='--', alpha=0.6, lw=1)
                ax.text(start, top * 0.82, f' {p} starts', fontsize=8,
                        color=PLATFORM_COLORS.get(p))

    ax.set_title('Daily mid-funnel touches by platform (by touch date)')
    ax.set_ylabel('Touches')
    ax.legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)
    return counts


def chart_lag_histogram(lag_days, out_path):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(lag_days, bins=15, color='#DD8452', edgecolor='white')
    median_lag = lag_days.median()
    ax.axvline(median_lag, color='black', linestyle='--', label=f'Median = {median_lag:.1f} days')
    ax.set_title('Days Between First Mid-Funnel Touch and Converting Search Click\n(Mid-Funnel-Assisted Search Conversions)')
    ax.set_xlabel('Days')
    ax.set_ylabel('Conversions')
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)


def chart_top_paths(paths, out_path, level='platform', n_top=8):
    """DV360-style 'Top Converting Paths' chevron chart. Collapses each
    conversion's touch sequence into ordered distinct-consecutive steps
    (e.g. Reddit > Reddit > Search -> Reddit > Search), then ranks the most
    common journeys by share of conversions. Position 1 (rightmost) = the
    converting (last) touch. Returns the ranked rows for the narrative/table."""
    seq_col = 'platform_sequence' if level == 'platform' else 'channel_sequence'

    def collapse(seq_str):
        out = []
        for p in seq_str.split(' > '):
            if not out or out[-1] != p:
                out.append(p)
        return ' > '.join(out)

    journeys = paths[seq_col].apply(collapse)
    total = len(paths)
    top = journeys.value_counts().head(n_top)
    rows = [{'journey': j, 'conversions': int(c), 'pct': c / total} for j, c in top.items()]

    seg_colors = dict(PLATFORM_COLORS)
    seg_colors.update({'Search': '#4285F4', 'Mid-funnel': '#FF7043', 'Other': '#B0B0B0'})
    short = {'Google Search': 'Google', 'MSN Search': 'MSN'}

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
            verts = [(x0, y - h/2), (x1 - notch, y - h/2), (x1, y),
                     (x1 - notch, y + h/2), (x0, y + h/2), (x0 + left_notch, y)]
            ax.add_patch(Polygon(verts, closed=True,
                                 facecolor=seg_colors.get(label, '#9AB4E8'),
                                 edgecolor='white', linewidth=1.5))
            ax.text((x0 + x1)/2 + (notch/2 if left_notch else 0), y,
                    short.get(label, label), ha='center', va='center',
                    color='white', fontsize=10, fontweight='bold')
        ax.text(x_right + 0.4, y, f"{row['pct']*100:.0f}%", ha='left', va='center',
                fontsize=13, fontweight='bold', color='#1a73e8')

    for pos in range(1, max_len + 1):
        xc = x_right - (pos - 1) * (seg_w + gap) - seg_w/2
        ax.text(xc, -0.9, str(pos), ha='center', va='center', fontsize=10, color='#888')
    ax.text(x_right + 0.4, n_rows - 0.15, '% of Conv.', ha='left', va='center',
            fontsize=10, color='#555', fontweight='bold')
    ax.set_xlim(x_right - max_len * (seg_w + gap) - 0.8, x_right + 2.0)
    ax.set_ylim(-1.6, n_rows - 0.1)
    ax.axis('off')
    ax.set_title('Top Converting Paths, grouped by Platform', fontsize=13, fontweight='bold', loc='left', pad=12)
    ax.text(x_right - max_len * (seg_w + gap) - 0.8, -1.45,
            'Ad exposures — position 1 = converting (last) touch', fontsize=8, style='italic', color='#999')
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)
    return rows


def chart_transition_heatmap(touches, out_path, platform_order=None):
    """Full sequential (Markov-style) transition analysis: for every
    consecutive touch pair in every path, what platform comes next?
    Row-normalized, so each row sums to 100% — the diagonal is
    'platform loyalty' (repeat exposure), off-diagonal is cross-platform
    migration. Returns the transition matrix for the narrative bullets."""
    order = platform_order or list(PLATFORM_COLORS.keys())
    t = touches.sort_values(['Conversion ID', 'touch_order']).copy()
    t['next_platform'] = t.groupby('Conversion ID')['platform'].shift(-1)
    transitions = t.dropna(subset=['next_platform'])
    trans = pd.crosstab(transitions['platform'], transitions['next_platform'], normalize='index') \
        .reindex(index=order, columns=order).fillna(0)

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(trans.values, cmap='YlOrRd', vmin=0, vmax=1)
    ax.set_xticks(range(len(order))); ax.set_xticklabels(order, rotation=45, ha='right')
    ax.set_yticks(range(len(order))); ax.set_yticklabels(order)
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
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)
    return trans


# ----------------------------------------------------------------------------
# Word document assembly — mirrors the 2026 Q2 QBR deliverable layout
# ----------------------------------------------------------------------------

BODY_FONT = 'Helvetica Neue'
LIGHT_FONT = 'Helvetica Neue Light'
BODY_SIZE = Pt(10)
HEADING_SIZE = Pt(19)
COVER_TITLE_SIZE = Pt(31)
COVER_SUB_SIZE = Pt(24)
META_SIZE = Pt(11)
CAPTION_SIZE = Pt(8)
TABLE_SIZE = Pt(9)

INK = RGBColor(0x21, 0x21, 0x21)
BLACK = RGBColor(0x00, 0x00, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CAPTION_GRAY = RGBColor(0x66, 0x66, 0x66)

TABLE_HEADER_FILL = '356854'
TABLE_HEADER_EDGE = '284e3f'
TABLE_GRID = 'cccccc'

CONTENT_WIDTH_IN = 6.0


def _apply_font(el, font):
    """Set ascii/hAnsi/cs/eastAsia together so Word does not substitute the face."""
    rPr = el.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    for attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        rFonts.set(qn(attr), font)


def style_run(run, size=BODY_SIZE, bold=False, color=None, font=BODY_FONT):
    run.font.size = size
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    _apply_font(run._element, font)
    return run


def new_document():
    doc = Document()

    normal = doc.styles['Normal']
    normal.font.size = BODY_SIZE
    _apply_font(normal.element, BODY_FONT)
    normal.paragraph_format.space_after = Pt(10)
    normal.paragraph_format.line_spacing = 1.15

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(1.25)
    sec.top_margin = sec.bottom_margin = Inches(1)
    return doc


def add_heading(doc, text):
    """Heading 1 so the text still lands in the document outline / Index,
    restyled to the deliverable's type scale."""
    h = doc.add_heading(text, level=1)
    h.paragraph_format.space_before = Pt(18)
    h.paragraph_format.space_after = Pt(6)
    for run in h.runs:
        style_run(run, size=HEADING_SIZE, color=BLACK)
    return h


def add_body(doc, segments, justify=True, size=BODY_SIZE, font=BODY_FONT,
             color=None, space_after=Pt(10)):
    """segments: a string, or a list of strings / (text, bold) pairs."""
    p = doc.add_paragraph()
    if justify:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = space_after
    for seg in ([segments] if isinstance(segments, str) else segments):
        text, bold = (seg, False) if isinstance(seg, str) else seg
        style_run(p.add_run(text), size=size, bold=bold, color=color, font=font)
    return p


def add_bullets(doc, items):
    """items: strings, or lists of (text, bold) pairs for bold lead-ins."""
    for item in items:
        p = doc.add_paragraph(style='List Bullet')
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_after = Pt(8)
        for seg in ([item] if isinstance(item, str) else item):
            text, bold = (seg, False) if isinstance(seg, str) else seg
            style_run(p.add_run(text), bold=bold)


def _shade_cell(cell, fill):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:fill'), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _border_cell(cell, color):
    borders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '4')
        el.set(qn('w:color'), color)
        borders.append(el)
    cell._tc.get_or_add_tcPr().append(borders)


def _write_cell(cell, text, bold=False, color=None, fill=None, border=TABLE_GRID):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    style_run(p.add_run(str(text)), size=TABLE_SIZE, bold=bold, color=color)
    if fill:
        _shade_cell(cell, fill)
    _border_cell(cell, border)


def add_table(doc, headers, rows, widths=None):
    """Green-header table matching the deliverable's table treatment."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)

    if widths is None:
        widths = [CONTENT_WIDTH_IN / len(headers)] * len(headers)

    for cell, head, w in zip(table.rows[0].cells, headers, widths):
        cell.width = Inches(w)
        _write_cell(cell, head, bold=True, color=WHITE,
                    fill=TABLE_HEADER_FILL, border=TABLE_HEADER_EDGE)

    for row in rows:
        cells = table.add_row().cells
        for cell, val, w in zip(cells, row, widths):
            cell.width = Inches(w)
            _write_cell(cell, val)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return table


def add_figure(doc, path, caption, width_in=CONTENT_WIDTH_IN):
    doc.add_picture(path, width=Inches(width_in))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(14)
    style_run(cap.add_run(caption), size=CAPTION_SIZE, color=CAPTION_GRAY)


def add_cover(doc, m):
    if os.path.exists(LOGO_PATH):
        doc.add_picture(LOGO_PATH, width=Inches(2.2))
        doc.paragraphs[-1].paragraph_format.space_after = Pt(36)

    add_body(doc, [('Path to Conversion Copilot', True)], justify=False,
             size=COVER_TITLE_SIZE, color=INK, space_after=Pt(0))
    add_body(doc, REPORT_SUBTITLE, justify=False, size=COVER_SUB_SIZE,
             color=INK, space_after=Pt(24))

    for line in (
        f"Data range: {m.date_min:%b %d, %Y} - {m.date_max:%b %d, %Y}",
        f"Total conversions analyzed: {m.n_conversions:,}",
        f"Report prepared: {pd.Timestamp.now():%B %d, %Y}",
    ):
        add_body(doc, line, justify=False, size=META_SIZE, font=LIGHT_FONT,
                 color=BLACK, space_after=Pt(2))

    add_heading(doc, 'Index')
    add_body(doc, '', space_after=Pt(0))
    doc.add_page_break()


# ----------------------------------------------------------------------------
# Narrative builders (all figures computed from the data, never hardcoded)
# ----------------------------------------------------------------------------

def join_list(items):
    """'a', 'a and b', 'a, b and c'."""
    items = list(items)
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def summary_bullets(m):
    ranked = m.platform_volume.sort_values('conversions_influenced', ascending=False)
    reach = [f"{p} ({int(r.conversions_influenced):,}, {r.pct_of_all_conversions:.1%} of conversions)"
             for p, r in ranked.iterrows()]

    bullets = [
        [('Mid-funnel touch', True),
         f": {m.pct_mf_touched:.1%} of conversions in this window ({m.n_mf_touched:,} of "
         f"{m.n_conversions:,}) were touched by a mid-funnel platform at least once; the remaining "
         f"{m.pct_untouched:.1%} were Search-only. Of the touched paths, {m.pct_mf_impr_only:.0%} "
         f"({m.n_mf_impr_only:,}) were view-through only (impression, no click), showing mid-funnel is "
         f"mostly assisting the journey rather than being clicked directly."],

        [('Path mix', True),
         f": {m.pct_search_only:.1%} of conversions are Search-only, {m.pct_mixed:.1%} are Mixed "
         f"(touched by both Search and mid-funnel), and {m.pct_mf_only:.1%} are Mid-funnel-only "
         f"(view-through, no search touch at all)."],

        f"The hypothesis is partially supported: {m.pct_classic:.1%} of Mixed paths ({m.n_classic} of "
        f"{m.n_mixed_paths}) follow the classic pattern of mid-funnel first touch converting via Search. "
        f"Among these, the median time between the first mid-funnel exposure and the converting Search "
        f"click is {m.lag_median:.1f} days, with {m.pct_multi_day:.1%} taking a day or more.",

        f"Mixed paths take meaningfully longer to convert (avg. "
        f"{m.by_type.loc['Mixed', 'avg_days_to_convert']:.1f} days, "
        f"{m.by_type.loc['Mixed', 'avg_path_length']:.1f} touches) than Search-only paths (avg. "
        f"{m.by_type.loc['Search-only', 'avg_days_to_convert']:.1f} days, "
        f"{m.by_type.loc['Search-only', 'avg_path_length']:.1f} touches), consistent with mid-funnel "
        f"nurturing demand rather than capturing existing intent.",
    ]

    if reach:
        bullets.append([('Platform reach', True),
                        f": {reach[0]} leads among mid-funnel platforms"
                        + (f", ahead of {join_list(reach[1:])}." if len(reach) > 1 else ".")])

    bullets.append([('Attribution coverage', True),
                    f": the export contains {m.n_export_conversions:,} conversions for this activity, of "
                    f"which {m.n_conversions:,} ({m.pct_attributed:.1%}) carry at least one CM360 "
                    f"interaction. The {m.n_unattributed:,} unattributed conversions (path length 0) have "
                    f"no touch data and are excluded from every path metric in this report."])
    return bullets


def transition_bullets(transition_matrix):
    present = [p for p in transition_matrix.index if transition_matrix.loc[p].sum() > 0]
    self_loop = {p: transition_matrix.loc[p, p] for p in present}
    search = [p for p in present if p in SEARCH_PLATFORMS]
    mid = [p for p in present if p in MID_FUNNEL_PLATFORMS]

    out = []
    if search:
        parts = ', '.join(f"{p} ({self_loop[p]:.0%})" for p in search)
        out.append([('Search persistence', True),
                    f": {parts} show high continuity, users return to the same search engine for their "
                    f"next touch."])
    if mid:
        stayers = sorted(mid, key=lambda p: self_loop[p], reverse=True)
        parts = ', '.join(f"{p} ({self_loop[p]:.0%} stay)" for p in stayers)
        out.append([('Social platform loyalty', True),
                    f": {parts}. Platforms with lower self-transition rates are handing users off rather "
                    f"than holding them."])
        lowest = stayers[-1]
        row = transition_matrix.loc[lowest].drop(lowest)
        dest = row.idxmax()
        if row[dest] > 0:
            out.append([(f'{lowest} as an awareness play', True),
                        f": only {self_loop[lowest]:.0%} of {lowest} interactions lead to another "
                        f"{lowest} touch; {row[dest]:.0%} transition to {dest}, suggesting it functions "
                        f"as an upper-funnel driver rather than a closer."])
    return out


def conclusion_bullets(m):
    bullets = [
        [('Analysis window', True),
         f": this report covers conversions from {m.date_min:%b %d, %Y} to {m.date_max:%b %d, %Y}, the "
         f"period in which the mid-funnel platforms were live and tagged. Pre-activation weeks are "
         f"excluded so the numbers are not diluted by weeks in which mid-funnel could not appear."],
    ]

    window_end = m.date_max
    partial, low_volume = [], []
    for platform in MID_FUNNEL_PLATFORMS:
        if platform not in m.live_windows.index:
            continue
        w = m.live_windows.loc[platform]
        late = (w['first_touch'] - m.date_min).days > 3
        early_stop = (window_end - w['last_touch']).days > 7
        if late or early_stop:
            partial.append(
                f"{platform} ran {w['first_touch']:%b %d} to {w['last_touch']:%b %d}")
        if platform in m.platform_volume.index and \
                m.platform_volume.loc[platform, 'pct_of_all_conversions'] < 0.01:
            low_volume.append(
                f"{platform} ({int(m.platform_volume.loc[platform, 'conversions_influenced']):,} "
                f"conversions influenced)")

    if partial:
        plural = len(partial) > 1
        bullets.append([('Partial-window platform' + ('s' if plural else ''), True),
                        f": {'; '.join(partial)}, so "
                        f"{'these platforms were' if plural else 'it was'} not live for the full window. "
                        f"{'Their' if plural else 'Its'} metrics are directional and should not be "
                        f"compared like-for-like with always-on platforms."])
    if low_volume:
        plural = len(low_volume) > 1
        bullets.append([('Low-volume platform' + ('s' if plural else ''), True),
                        f": {join_list(low_volume)} influenced under 1% of conversions"
                        f"{' each' if plural else ''}. Any conclusion drawn on "
                        f"{'them' if plural else 'it'} is directional, not statistically solid."])

    bullets += [
        f"The Mixed-path sample is small (n={m.n_mixed_paths}, {m.pct_mixed:.1%} of conversions in the "
        f"window), so point estimates on this subset (for example the classic-hypothesis rate) carry "
        f"wide uncertainty and should be revisited as more data accumulates.",

        "This is a path-to-conversion / last-touch-adjacent export, not a full multi-touch attribution "
        "model, so all percentages here are directional evidence for the mid-funnel hypothesis rather "
        "than a formal attribution result.",

        [('Recommendation', True),
         ": re-run this report on the next refresh once every mid-funnel platform has a full month of "
         "in-window data, to tighten these estimates and confirm the trend direction."],
    ]
    return bullets


def build_document(m, position_dist, chart_paths, top_paths_rows, transition_matrix, out_path):
    doc = new_document()
    add_cover(doc, m)

    # ---------------- Summary ----------------
    add_heading(doc, 'Summary')
    add_body(doc,
             f"This report analyzes CM360 path-to-conversion data to test whether mid-funnel awareness "
             f"channels ({', '.join(p for p in MID_FUNNEL_PLATFORMS if p in m.live_windows.index)}) "
             f"build interest that later converts through Search. It covers conversions from "
             f"{m.date_min:%b %d, %Y} to {m.date_max:%b %d, %Y}, the period in which all mid-funnel "
             f"platforms were live and tagged, so the numbers reflect mid-funnel's true impact rather "
             f"than an activation ramp-up.")
    add_bullets(doc, summary_bullets(m))

    # ---------------- Methodology ----------------
    add_heading(doc, 'Methodology & Data Notes')
    add_body(doc,
             f"Source: CM360 Path-to-Conversion export for the floodlight activity "
             f"\"{m.activity_name}\", covering activity from {m.date_min:%Y-%m-%d} to "
             f"{m.date_max:%Y-%m-%d}. Each conversion's full touch sequence (up to "
             f"{m.n_interaction_slots} recorded interactions) was reshaped into a touch-level table and "
             f"classified using the following taxonomy, derived from the campaigns and sites actually "
             f"present in the export:")
    add_table(doc, ['Campaign', 'Site (CM360)', 'Channel', 'Platform'],
              m.taxonomy.values.tolist(), widths=[1.55, 1.75, 1.2, 1.5])

    add_body(doc,
             f"Attribution coverage: {m.n_export_conversions:,} conversions were returned for this "
             f"activity. {m.n_conversions:,} ({m.pct_attributed:.1%}) carry at least one CM360 "
             f"interaction and form the basis of every path metric below; the remaining "
             f"{m.n_unattributed:,} have a path length of 0, meaning no click or impression was matched "
             f"to them, and are excluded rather than counted as Search-only.")

    if m.has_rampup:
        add_body(doc,
                 f"The raw export covers {m.ctx_full_date_min:%b %d} to {m.ctx_full_date_max:%b %d, %Y} "
                 f"({m.ctx_full_n:,} attributed conversions), but the mid-funnel platforms were not live "
                 f"for the first part of that range. The first mid-funnel interaction recorded anywhere "
                 f"in the data is {m.first_mf_date:%b %d, %Y}; everything before that is Search-only by "
                 f"construction, not by consumer behaviour. Including those weeks does not measure how "
                 f"often mid-funnel is involved, it measures how long the platforms took to turn on, and "
                 f"mechanically drags every mid-funnel metric toward zero.")
        add_body(doc,
                 f"The data makes the distortion concrete. Measuring the full export against the "
                 f"post-activation window (from {STEADY_STATE_START:%b %d, %Y}, once all platforms were "
                 f"live):")
        add_table(doc,
                  ['Metric', 'Full export', f'This report (>= {STEADY_STATE_START:%b %d})'],
                  [['Attributed conversions', f"{m.ctx_full_n:,}", f"{m.n_conversions:,}"],
                   ['% touched by any mid-funnel', f"{m.ctx_full_pct_touched:.1%}", f"{m.pct_mf_touched:.1%}"],
                   ['% Mixed (Search + Mid-funnel)', f"{m.ctx_full_pct_mixed:.1%}", f"{m.pct_mixed:.1%}"]],
                  widths=[2.4, 1.7, 1.9])
        add_body(doc,
                 f"Scoping to the post-activation window lifts the mid-funnel touch rate from "
                 f"{m.ctx_full_pct_touched:.1%} to {m.pct_mf_touched:.1%} because it stops averaging in "
                 f"weeks where mid-funnel could not appear. All findings that follow use only this "
                 f"post-activation window.")
    else:
        add_body(doc,
                 f"Window: the export was pulled from {m.date_min:%b %d, %Y} onward, which is already the "
                 f"post-activation window, so no ramp-up weeks need to be trimmed and no mid-funnel "
                 f"metric is diluted by weeks in which the platforms were not yet live. Individual "
                 f"platforms did, however, start and stop at different points, which is what the touch "
                 f"windows below show. Touch dates can precede the conversion window, since an exposure "
                 f"that led to an in-window conversion may have happened earlier:")
        add_table(doc,
                  ['Platform', 'First recorded touch', 'Last recorded touch', 'Touches'],
                  [[p, f"{r['first_touch']:%b %d, %Y}", f"{r['last_touch']:%b %d, %Y}",
                    f"{int(r['touches']):,}"]
                   for p, r in m.live_windows.iterrows()],
                  widths=[1.5, 1.65, 1.65, 1.2])
        add_body(doc,
                 "Platforms that joined or stopped mid-window carry fewer exposure days than the "
                 "always-on Search campaigns, so their share of conversions understates their "
                 "steady-state contribution. The timeseries below shows daily touch volume per "
                 "platform, making each platform's live period and relative intensity visible.")

    add_figure(doc, chart_paths['daily_mf'], 'Figure 1. Mid-funnel platforms timeseries.')
    doc.add_page_break()

    # ---------------- Path mix ----------------
    add_heading(doc, 'Mid-Funnel vs. Search Path Mix')
    add_body(doc,
             f"Out of {m.n_conversions:,} attributed conversions, the large majority "
             f"({m.pct_search_only:.1%}) never touch a mid-funnel platform at all. {m.pct_mf_only:.1%} "
             f"convert on a mid-funnel view-through impression with no Search touch in the path, and "
             f"{m.pct_mixed:.1%} ({m.n_mixed:,} conversions) show both channels in the same path.")
    add_figure(doc, chart_paths['path_type'], 'Figure 2. Conversions by path type (campaign level).')
    add_body(doc,
             f"Within these {m.n_mixed_paths} Mixed conversions, {m.n_classic} ({m.pct_classic:.1%}) "
             f"follow the exact hypothesis pattern, mid-funnel touches first and Search converts last. "
             f"This confirms the pattern exists and is not negligible, but it is not yet the dominant "
             f"journey shape among Mixed paths; the reverse order (Search touching first, mid-funnel "
             f"later) also occurs.")

    # ---------------- Top converting paths ----------------
    add_heading(doc, 'Top Converting Paths by Platform')
    top_share = sum(r['pct'] for r in top_paths_rows)
    add_body(doc,
             f"Collapsing each conversion's touch sequence into its ordered distinct-consecutive platform "
             f"steps (so repeated touches on the same platform read as one step) and ranking the most "
             f"common journeys gives a DV360-style top converting paths view. Position 1 is the "
             f"converting (last) touch. The {len(top_paths_rows)} journeys below account for "
             f"{top_share:.1%} of all {m.n_conversions:,} conversions in this window.")
    add_figure(doc, chart_paths['top_paths'],
               'Figure 3. Top converting paths, grouped by platform (position 1 = converting touch).')
    add_table(doc, ['Rank', 'Converting path (first -> last)', 'Conversions', '% of conversions'],
              [[i + 1, r['journey'], f"{r['conversions']:,}", f"{r['pct']:.1%}"]
               for i, r in enumerate(top_paths_rows)],
              widths=[0.6, 3.0, 1.1, 1.3])
    add_body(doc,
             "Read in practice: the top paths are dominated by single-platform Search journeys, "
             "confirming most conversions never involve a mid-funnel touch. The multi-platform journeys "
             "that do appear are exactly the mid-funnel-assisted paths quantified in the path mix and "
             "funnel velocity sections, real but a small share of total volume in the current window.")
    doc.add_page_break()

    # ---------------- Transition flow ----------------
    add_heading(doc, 'Platform Transition Flow')
    add_body(doc,
             "The heatmap below shows, for every consecutive touch pair in a conversion path, the "
             "probability of each next-touch platform (row %). Rows represent the current platform and "
             "columns where the user touches next. The diagonal reflects platform loyalty, how often a "
             "touch on a given platform is immediately followed by another touch on the same platform, "
             "while off-diagonal cells reveal cross-platform migration.")
    add_bullets(doc, transition_bullets(transition_matrix))
    add_figure(doc, chart_paths['heatmap'],
               'Figure 4. Platform-to-platform transition probabilities (row % of next-touch platform).')

    # ---------------- Velocity by path type ----------------
    add_heading(doc, 'Mixed Paths Take Longer to Convert')
    add_body(doc,
             "If mid-funnel is genuinely building interest earlier in the journey rather than acting as "
             "a same-session assist, Mixed paths should show longer paths and longer time-to-convert "
             "than Search-only paths. The data supports this:")
    add_table(doc, ['Path type', 'Conversions', 'Avg. path length (touches)', 'Avg. days to convert'],
              [[t, f"{int(m.by_type.loc[t, 'conversions']):,}",
                f"{m.by_type.loc[t, 'avg_path_length']:.2f}",
                f"{m.by_type.loc[t, 'avg_days_to_convert']:.2f}"]
               for t in ['Search-only', 'Mixed', 'Mid-funnel-only'] if t in m.by_type.index],
              widths=[1.4, 1.1, 1.9, 1.6])
    add_body(doc,
             f"Collapsing this to a two-way comparison makes the gap clear: conversions touched by "
             f"mid-funnel at any point average {m.touched_apl:.1f} touches and {m.touched_days:.1f} days "
             f"from first touch to conversion, versus {m.untouched_apl:.1f} touches and "
             f"{m.untouched_days:.1f} days for Search-only conversions. A mid-funnel touch is therefore "
             f"associated with a path roughly {m.touched_apl / m.untouched_apl:.1f}x longer that takes "
             f"about {m.touched_days - m.untouched_days:.1f} more days to close, the signature of a "
             f"longer, more considered journey rather than same-session intent capture.")
    add_figure(doc, chart_paths['length_time'],
               'Figure 5. Average path length and days-to-convert by path type.')
    doc.add_page_break()

    # ---------------- Platform breakdown ----------------
    add_heading(doc, 'Platform Breakdown & Path Position')
    ranked = m.platform_volume.sort_values('conversions_influenced', ascending=False)
    add_body(doc,
             f"At the site level, {ranked.index[0]} has the largest footprint among mid-funnel platforms"
             + (f", followed by {join_list(ranked.index[1:])}." if len(ranked) > 1 else ".")
             + " Touch counts include both clicks and view-through impressions.")
    add_table(doc, ['Platform', 'Touches', 'Conversions influenced', '% of all conversions'],
              [[p, f"{int(r['touches']):,}", f"{int(r['conversions_influenced']):,}",
                f"{r['pct_of_all_conversions']:.1%}"] for p, r in ranked.iterrows()],
              widths=[1.5, 1.1, 1.9, 1.5])
    add_body(doc,
             "Looking at where each platform's touch tends to land within the path (first / middle / "
             "last / only touch) shows whether a platform behaves more like top-of-funnel awareness or "
             "late-stage retargeting:")
    add_figure(doc, chart_paths['position'],
               'Figure 6. Touch position distribution by mid-funnel platform.')

    # ---------------- Path flow ----------------
    add_heading(doc, 'Path Flow: First Touch to Converting Touch')
    add_body(doc,
             "For multi-touch conversions, tracing the flow from the first touch platform to the last "
             "(converting) touch platform gives a quick visual read on whether mid-funnel platforms feed "
             "into Search by the end of the journey, or whether paths tend to stay within one platform.")
    add_figure(doc, chart_paths['sankey'],
               'Figure 7. First-touch platform to last-touch platform flow (multi-touch conversions).')

    # ---------------- Funnel velocity ----------------
    add_heading(doc, 'Funnel Velocity: Mid-Funnel Builds Interest, Search Converts Later')
    add_body(doc,
             f"For the {m.n_classic} mid-funnel-assisted Search conversions, the median time between the "
             f"first mid-funnel touch and the eventual converting Search click is {m.lag_median:.1f} days "
             f"(mean {m.lag_mean:.1f} days). {m.pct_multi_day:.1%} of these conversions take a day or "
             f"more to close after the initial mid-funnel exposure, the clearest quantitative evidence "
             f"that mid-funnel is acting as an earlier-funnel nurture touch rather than a same-session "
             f"assist.")
    add_figure(doc, chart_paths['lag'],
               'Figure 8. Days between first mid-funnel touch and converting Search click.')
    doc.add_page_break()

    # ---------------- Conclusions ----------------
    add_heading(doc, 'Conclusions & Recommendations')
    add_bullets(doc, conclusion_bullets(m))

    doc.save(out_path)
    return out_path


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def build_taxonomy(touches):
    """Campaign / site / channel / platform combinations actually present in the export."""
    tax = (touches[['campaign', 'site', 'channel', 'platform']]
           .drop_duplicates()
           .sort_values(['channel', 'platform']))
    return tax


def main():
    print(f"Source: {os.path.basename(CSV_PATH)}")
    if EXPORT_META.get('Date Range'):
        print(f"  Export date range: {EXPORT_META['Date Range']}")

    # Whole export, used to decide whether a ramp-up caveat is needed and to draw
    # the mid-funnel timeseries across every day available.
    df_full = load_data()
    slots = n_interaction_slots(df_full)
    
    # Auto-detect and map any new platforms
    print("  Checking for new platforms...")
    auto_map_platforms(df_full, slots)
    
    bad_campaigns, bad_sites = unmapped_values(df_full, slots)
    if bad_campaigns or bad_sites:
        print("  WARNING: values missing from the taxonomy (they will fall into 'Other'):")
        for c in bad_campaigns:
            print(f"    campaign: {c!r}  -> add to CHANNEL_MAP")
        for s in bad_sites:
            print(f"    site:     {s!r}  -> add to PLATFORM_MAP")

    touches_full = build_touches(df_full)
    paths_full = build_paths(touches_full, df_full[['Conversion ID', 'Activity Date/Time', 'Path Length']])
    mf_touches_full = touches_full[touches_full['channel'] == 'Mid-funnel']

    # An export pulled from the steady-state date onward needs no trimming; an
    # older one still covering the activation ramp-up does.
    has_rampup = df_full['Activity Date/Time'].min() < STEADY_STATE_START
    if has_rampup:
        print(f"  Export includes pre-activation weeks; scoping analysis to >= {STEADY_STATE_START:%Y-%m-%d}")
        df = load_data(STEADY_STATE_START)
        touches = build_touches(df)
        paths = build_paths(touches, df[['Conversion ID', 'Activity Date/Time', 'Path Length']])
    else:
        print("  Export already starts in the post-activation window; using it in full")
        df, touches, paths = df_full, touches_full, paths_full

    touches_pos = build_touch_positions(touches)
    mid_funnel_touches = touches_pos[touches_pos['channel'] == 'Mid-funnel'].copy()

    platform_volume = mid_funnel_touches.groupby('platform').agg(
        touches=('Conversion ID', 'count'),
        conversions_influenced=('Conversion ID', 'nunique'),
    ).sort_values('touches', ascending=False)
    platform_volume['pct_of_all_conversions'] = (platform_volume['conversions_influenced'] / len(paths))

    mixed = paths[paths['path_type'] == 'Mixed'].copy()
    lag_days = compute_lag_days(touches, mixed)

    m = compute_metrics(df, touches, paths, touches_pos, mid_funnel_touches, platform_volume, lag_days)
    m.has_rampup = has_rampup
    m.n_interaction_slots = slots
    m.taxonomy = build_taxonomy(touches)

    if has_rampup:
        m.ctx_full_n = len(paths_full)
        m.ctx_full_pct_touched = (paths_full['n_mid_funnel_touches'] > 0).mean()
        m.ctx_full_pct_mixed = (paths_full['path_type'] == 'Mixed').mean()
        m.ctx_full_date_min = df_full['Activity Date/Time'].min()
        m.ctx_full_date_max = df_full['Activity Date/Time'].max()
        m.first_mf_date = mf_touches_full['touch_time'].min()  # true first touch, pre-cut

    charts_dir, out_docx = output_paths(m.date_min, m.date_max)

    print("Generating charts...")
    chart_paths = {
        'daily_mf': os.path.join(charts_dir, '01_mid_funnel_timeseries.png'),
        'path_type': os.path.join(charts_dir, '02_path_type.png'),
        'top_paths': os.path.join(charts_dir, '03_top_paths.png'),
        'heatmap': os.path.join(charts_dir, '04_heatmap.png'),
        'length_time': os.path.join(charts_dir, '05_length_time.png'),
        'position': os.path.join(charts_dir, '06_position.png'),
        'sankey': os.path.join(charts_dir, '07_sankey.png'),
        'lag': os.path.join(charts_dir, '08_lag_histogram.png'),
    }
    chart_daily_mid_funnel(touches_full, chart_paths['daily_mf'])
    chart_path_type(paths, chart_paths['path_type'])
    top_paths_rows = chart_top_paths(paths, chart_paths['top_paths'], level='platform')
    transition_matrix = chart_transition_heatmap(touches, chart_paths['heatmap'])
    chart_length_time(m.by_type, chart_paths['length_time'])
    position_dist = chart_position(mid_funnel_touches, chart_paths['position'])
    chart_sankey(paths, chart_paths['sankey'])
    chart_lag_histogram(lag_days, chart_paths['lag'])
    for name, p in chart_paths.items():
        print(f"  {name}: {os.path.basename(p)} ({os.path.getsize(p):,} bytes)")

    print("Building Word document...")
    out = build_document(m, position_dist, chart_paths, top_paths_rows, transition_matrix, out_docx)
    print(f"Report saved to: {out}")


if __name__ == '__main__':
    main()
