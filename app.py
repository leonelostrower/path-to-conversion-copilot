"""
Streamlit front end for Path to Conversion Copilot.

Four steps: upload the export and name the client, add written context, run the
mapping agent, the analysis and the narrative agent, read the report.

Only the two Gemini stages are called agents in the interface. The analysis in
between is plain Python and is named as such, so a reader can tell at a glance
which numbers an AI could have touched.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
from html import escape

# matplotlib must find a writable config dir before report_core imports it.
os.environ.setdefault('MPLCONFIGDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '.mplcache'))

import pandas as pd
import streamlit as st

import report_core as rc
from agents import narrative_agent, orchestrator
from agents.gemini_client import (
    DEFAULT_MODEL, SELECTABLE_MODELS, GeminiAuthError, GeminiClient, GeminiError,
)
from report_spec import Bullets, Figure, Prose, Section, Table

st.set_page_config(page_title='Path to Conversion Copilot',
                   page_icon='✦', layout='wide',
                   initial_sidebar_state='collapsed')

STEPS = [
    ('Upload', 'Export and client'),
    ('Context', 'Background for the narrative'),
    ('Generate', 'Mapping, analysis, narrative'),
    ('Report', 'Read and download'),
]

# Vendors shown in the sidebar switcher. Only Gemini is wired to the runtime;
# the rest are presentational, so the switcher stays a mockup on purpose.
PROVIDERS = [
    ('G', 'Gemini', 'Google · connected', True),
    ('C', 'Claude', 'Anthropic', False),
    ('O', 'GPT', 'OpenAI', False),
    ('X', 'Grok', 'xAI', False),
    ('L', 'Llama', 'Meta · self-hosted', False),
]

STYLE_CSS = """
<style>
  :root {
    --mf-font: 'Helvetica Now for Monks', Helvetica, Arial, sans-serif;
    --mf-text: #3C3C3E;
    --mf-muted: #737378;
    --mf-plum: #4F24EE;
    --mf-plum-dark: #3B11D5;
    --mf-blue: #0F8CF0;
    --mf-border: rgba(0, 0, 0, 0.12);
    --mf-border-strong: rgba(0, 0, 0, 0.19);
    --mf-surface: #FFFFFF;
    --mf-canvas: #F7F7F7;
    --mf-plum-soft: #F7F6FE;
    --mf-blue-soft: #F1F6FF;
    --mf-green-soft: #F1FDF8;
    --mf-shadow-2: 0 2px 7px rgba(0, 0, 0, 0.10);
    --mf-shadow-4: 0 4px 16px rgba(0, 0, 0, 0.10);
  }

  html, body, [class*="css"], [data-testid="stAppViewContainer"] {
    font-family: var(--mf-font);
    color: var(--mf-text);
  }
  [data-testid="stAppViewContainer"] {
    background:
      radial-gradient(circle at 92% 2%, rgba(207,232,252,.58), transparent 24rem),
      var(--mf-canvas);
  }

  /* Viewport-locked shell: the page itself never scrolls. */
  html, body { overflow: hidden !important; }
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"] {
    max-height: 100dvh;
    overflow: hidden !important;
  }
  [data-testid="stHeader"] {
    height: 2.5rem;
    min-height: 2.5rem;
    background: transparent;
  }
  [data-testid="stToolbar"] { display: none; }
  #MainMenu, footer { visibility: hidden; }
  .block-container {
    height: calc(100dvh - 2.5rem);
    max-width: 1160px;
    padding: 0.35rem 2.25rem 0.75rem;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  /* Only the content region below the fixed chrome may scroll internally. */
  .block-container > [data-testid="stVerticalBlock"] {
    flex: 1;
    min-height: 0;
    gap: 0.55rem;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: #D1D2DB transparent;
    padding-right: 4px;
  }
  .block-container > [data-testid="stVerticalBlock"]::-webkit-scrollbar { width: 6px; }
  .block-container > [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: #D1D2DB;
  }
  h1, h2, h3, h4, h5, h6 {
    font-family: var(--mf-font) !important;
    color: var(--mf-text);
    font-weight: 500 !important;
    letter-spacing: -0.04em !important;
  }
  p, label, li, input, textarea, button {
    font-family: var(--mf-font) !important;
    letter-spacing: -0.01em;
  }
  strong { font-weight: 500; }

  /* App bar */
  .mf-navbar {
    flex: 0 0 auto;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 0 4px 8px;
    margin-bottom: 10px;
    border-bottom: 1px solid var(--mf-border);
  }
  .mf-brand { display: flex; align-items: center; gap: 10px; }
  .mf-mark {
    width: 32px; height: 32px; border-radius: 10px;
    display: grid; place-items: center;
    color: white; font-size: 17px; line-height: 1;
    background: linear-gradient(145deg, #7252E9, #4F24EE);
    box-shadow: var(--mf-shadow-2);
  }
  .mf-brand-name {
    font-size: 16px; line-height: 24px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  .mf-brand-meta {
    font-size: 12px; line-height: 16px; color: var(--mf-muted);
  }
  .mf-nav-status {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 7px 12px; border-radius: 999px;
    background: #E3FCF1; color: #388E3C;
    font-size: 12px; line-height: 16px; font-weight: 500;
  }
  .mf-nav-status::before {
    content: ''; width: 7px; height: 7px; border-radius: 50%;
    background: #4CAF50;
  }

  /* Workflow */
  .stepper {
    position: relative;
    flex: 0 0 auto;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    margin: 0 0 10px;
    padding: 6px;
    border: 1px solid var(--mf-border);
    border-radius: 14px;
    background: rgba(255,255,255,.82);
    box-shadow: var(--mf-shadow-2);
    backdrop-filter: blur(12px);
  }
  .step {
    position: relative;
    min-height: 42px;
    padding: 6px 10px 6px 38px;
    border-radius: 10px;
    font-size: 13px;
    line-height: 18px;
    transition: all .2s ease;
  }
  .step .n {
    position: absolute; left: 10px; top: 9px;
    width: 20px; height: 20px; border-radius: 50%;
    display: grid; place-items: center;
    background: #F2F2F2; color: #737378;
    font-size: 11px; line-height: 14px; font-weight: 500;
  }
  .step .t { font-weight: 500; color: #49494B; }
  .step .s {
    color: #8A8A8E; font-size: 11px; line-height: 15px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .step.done { background: #F1FDF8; }
  .step.done .n { background: #E3FCF1; color: #388E3C; }
  .step.active { background: #F0ECFE; }
  .step.active .n {
    background: var(--mf-plum); color: #fff;
    box-shadow: 0 2px 7px rgba(79,36,238,.28);
  }
  .step.active .t { color: var(--mf-plum); }

  /* Hero */
  .mf-hero {
    position: relative;
    flex: 0 0 auto;
    overflow: hidden;
    display: flex;
    align-items: flex-end;
    padding: 18px 26px;
    margin-bottom: 12px;
    border: 1px solid rgba(255,255,255,.78);
    border-radius: 18px;
    background: linear-gradient(101deg, #CFE8FC 0%, #ECF4FE 16%, #F7F6FE 52%, #FAF6FD 87%, #FFF3F6 100%);
    box-shadow: var(--mf-shadow-4);
  }
  .mf-hero::after {
    content: '';
    position: absolute; width: 190px; height: 190px;
    right: -48px; top: -74px; border-radius: 50%;
    border: 38px solid rgba(79,36,238,.10);
    box-shadow: 0 0 0 22px rgba(15,140,240,.07);
  }
  .mf-hero-content { position: relative; z-index: 1; max-width: 780px; }
  .mf-eyebrow {
    display: inline-flex; align-items: center; gap: 6px;
    margin-bottom: 8px; padding: 2px 9px;
    border-radius: 999px; background: rgba(255,255,255,.72);
    color: var(--mf-plum); font-size: 11px; line-height: 15px;
    font-weight: 500; backdrop-filter: blur(8px);
  }
  .mf-eyebrow::before { content: '✦'; font-size: 10px; }
  .hero-title {
    max-width: 740px;
    margin-bottom: 3px;
    color: #3C3C3E;
    font-size: 26px;
    line-height: 32px;
    font-weight: 400;
    letter-spacing: -0.04em;
  }
  .hero-sub {
    max-width: 720px;
    color: #5D5D60;
    font-size: 13px;
    line-height: 18px;
    letter-spacing: -0.01em;
  }

  /* Native Streamlit controls */
  div.stButton > button, div.stDownloadButton > button {
    min-height: 40px;
    padding: 0 18px;
    border-radius: 12px;
    border: 1px solid var(--mf-border-strong);
    background: #fff;
    color: var(--mf-text);
    font-size: 14px;
    line-height: 20px;
    font-weight: 500;
    box-shadow: none;
    transition: all .2s ease;
  }
  div.stButton > button:hover, div.stDownloadButton > button:hover {
    border-color: var(--mf-plum);
    color: var(--mf-plum);
    transform: translateY(-1px);
    box-shadow: var(--mf-shadow-2);
  }
  div.stButton > button:active, div.stDownloadButton > button:active {
    transform: scale(.98);
  }
  div.stButton > button[kind="primary"],
  div.stDownloadButton > button[kind="primary"] {
    border-color: var(--mf-plum);
    background: var(--mf-plum);
    color: #fff;
  }
  div.stButton > button[kind="primary"]:hover,
  div.stDownloadButton > button[kind="primary"]:hover {
    border-color: var(--mf-plum-dark);
    background: var(--mf-plum-dark);
    color: #fff;
  }
  [data-testid="stTextInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-baseweb="select"] > div {
    border: 1px solid var(--mf-border) !important;
    border-radius: 12px !important;
    background: #F7F7F7 !important;
    color: var(--mf-text) !important;
    box-shadow: none !important;
  }
  [data-testid="stTextInput"] input { min-height: 40px; }
  [data-testid="stTextInput"] input:focus,
  [data-testid="stTextArea"] textarea:focus {
    border-color: var(--mf-plum) !important;
    background: #fff !important;
    box-shadow: 0 0 0 3px rgba(79,36,238,.10) !important;
  }
  [data-testid="stFileUploader"] {
    padding: 8px;
    border: 1px solid var(--mf-border);
    border-radius: 16px;
    background: #fff;
    box-shadow: var(--mf-shadow-2);
  }
  [data-testid="stFileUploaderDropzone"] {
    min-height: 92px;
    padding: 10px 14px;
    border: 1px dashed #A892F7;
    border-radius: 12px;
    background: var(--mf-plum-soft);
  }
  [data-testid="stFileUploaderDropzone"] button {
    border-radius: 12px; border-color: var(--mf-plum);
    color: var(--mf-plum); background: #fff;
  }
  [data-testid="stMetric"] {
    min-height: 74px;
    padding: 12px 14px;
    border: 1px solid var(--mf-border);
    border-radius: 14px;
    background: #fff;
    box-shadow: var(--mf-shadow-2);
  }
  [data-testid="stMetricLabel"] { color: var(--mf-muted); }
  [data-testid="stMetricLabel"] p { font-size: 12px !important; line-height: 16px; }
  [data-testid="stMetricValue"] {
    color: var(--mf-text);
    font-size: 24px;
    font-weight: 400;
    letter-spacing: -0.04em;
  }
  [data-testid="stAlert"] {
    border-radius: 12px;
    border-width: 1px;
    box-shadow: none;
  }
  [data-testid="stExpander"] {
    border: 1px solid var(--mf-border);
    border-radius: 12px;
    background: #fff;
    overflow: hidden;
  }
  [data-testid="stDataFrame"] {
    border: 1px solid var(--mf-border);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: var(--mf-shadow-2);
  }
  /* Tabs own the remaining height; only the active panel scrolls. */
  [data-testid="stTabs"] {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    flex: 0 0 auto;
    gap: 6px;
    padding: 4px;
    border-radius: 12px;
    background: #F2F2F2;
  }
  [data-testid="stTabs"] [data-baseweb="tab-panel"] {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 8px 6px 0 0;
    scrollbar-width: thin;
    scrollbar-color: #D1D2DB transparent;
  }
  [data-testid="stTabs"] [data-baseweb="tab-panel"]::-webkit-scrollbar { width: 6px; }
  [data-testid="stTabs"] [data-baseweb="tab-panel"]::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: #D1D2DB;
  }
  [data-testid="stTabs"] button[role="tab"] {
    height: 34px;
    padding: 0 16px;
    border-radius: 8px;
    color: #737378;
  }
  [data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--mf-plum);
    background: #fff;
    box-shadow: var(--mf-shadow-2);
  }
  [data-testid="stTabs"] [data-baseweb="tab-highlight"] { display: none; }

  /* Sidebar / navrail */
  [data-testid="stSidebar"] {
    border-right: 1px solid var(--mf-border);
    background: #fff;
  }
  [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 20px;
  }
  [data-testid="stSidebar"] h3 {
    margin-top: 8px;
    font-size: 20px;
    line-height: 28px;
  }
  [data-testid="stSidebar"] hr { border-color: var(--mf-border); margin: 0.5rem 0; }
  [data-testid="stSidebar"] div.stButton > button { min-height: 36px; font-size: 13px; }
  .mf-sidebar-kicker {
    color: var(--mf-plum);
    font-size: 12px;
    line-height: 16px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: .0071em;
  }

  /* Open / close control for the settings rail */
  [data-testid="stSidebarCollapseButton"] button,
  [data-testid="stExpandSidebarButton"] button,
  [data-testid="collapsedControl"] button {
    width: 36px;
    height: 36px;
    border: 1px solid var(--mf-border-strong) !important;
    border-radius: 10px !important;
    background: #fff !important;
    color: var(--mf-plum) !important;
    box-shadow: var(--mf-shadow-2) !important;
  }
  [data-testid="stSidebarCollapseButton"] button:hover,
  [data-testid="stExpandSidebarButton"] button:hover,
  [data-testid="collapsedControl"] button:hover {
    border-color: var(--mf-plum) !important;
    background: var(--mf-plum-soft) !important;
  }

  /* Collapsible groups inside the rail */
  [data-testid="stSidebar"] [data-testid="stExpander"] {
    border-radius: 12px;
    box-shadow: none;
  }
  [data-testid="stSidebar"] [data-testid="stExpander"] summary {
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 500;
  }
  [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    color: var(--mf-plum);
  }

  /* Visual-only model provider switcher */
  .mf-providers { display: flex; flex-direction: column; gap: 6px; }
  .mf-provider {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border: 1px solid var(--mf-border);
    border-radius: 10px;
    background: #fff;
    cursor: pointer;
    transition: all .2s ease;
  }
  .mf-provider:hover {
    border-color: var(--mf-plum);
    background: var(--mf-plum-soft);
    transform: translateY(-1px);
  }
  .mf-provider.is-active {
    border-color: var(--mf-plum);
    background: #F0ECFE;
  }
  .mf-provider-glyph {
    width: 24px; height: 24px; flex: 0 0 24px;
    display: grid; place-items: center;
    border-radius: 7px;
    background: #F2F2F2;
    color: #52566A;
    font-size: 11px; font-weight: 500;
  }
  .mf-provider.is-active .mf-provider-glyph {
    background: var(--mf-plum); color: #fff;
  }
  .mf-provider-body { flex: 1; min-width: 0; }
  .mf-provider-name {
    font-size: 13px; line-height: 18px; font-weight: 500;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .mf-provider-meta {
    color: #8A8A8E;
    font-size: 11px; line-height: 15px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .mf-provider-tag {
    flex: 0 0 auto;
    padding: 1px 8px;
    border-radius: 999px;
    background: #F2F2F2;
    color: #737378;
    font-size: 10px; line-height: 15px; font-weight: 500;
  }
  .mf-provider.is-active .mf-provider-tag {
    background: var(--mf-plum); color: #fff;
  }

  /* Compact page header used where a hero would waste height */
  .mf-page-head { padding: 2px 0 4px; }
  .mf-page-title {
    font-size: 24px; line-height: 30px; font-weight: 400;
    letter-spacing: -0.04em;
  }
  .mf-page-meta {
    color: #737378;
    font-size: 13px; line-height: 18px;
  }

  /* Tabs must own the leftover height, so their wrapper stretches. */
  [data-testid="stElementContainer"]:has(> [data-testid="stTabs"]) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  /* Content cards */
  .report-shell {
    border: 1px solid var(--mf-border);
    border-radius: 18px;
    padding: 22px 26px;
    margin-top: 2px;
    background: #fff;
    box-shadow: var(--mf-shadow-2);
  }
  .report-shell h2 {
    margin: 28px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--mf-border);
    font-size: 20px;
    line-height: 28px;
  }
  .report-shell h2:first-child { margin-top: 0; }
  .cover-title {
    font-size: 26px; line-height: 32px; font-weight: 400;
    letter-spacing: -0.04em;
  }
  .cover-sub {
    margin: 2px 0 14px;
    color: var(--mf-plum);
    font-size: 16px; line-height: 24px;
  }
  .cover-meta {
    padding: 14px;
    border-radius: 12px;
    background: var(--mf-blue-soft);
    color: #5D5D60;
    font-size: 14px; line-height: 24px;
  }
  .agent-card {
    position: relative;
    height: 100%;
    overflow: hidden;
    padding: 12px 14px;
    border: 1px solid var(--mf-border);
    border-radius: 14px;
    background: #fff;
    box-shadow: var(--mf-shadow-2);
    transition: all .2s ease;
  }
  .agent-card:hover {
    transform: translateY(-2px) scale(1.01);
    box-shadow: var(--mf-shadow-4);
  }
  .agent-card::before {
    content: ''; position: absolute; inset: 0 auto 0 0; width: 3px;
    background: var(--mf-plum);
  }
  .agent-card .lbl {
    color: #8A8A8E;
    font-size: 11px; line-height: 15px;
    letter-spacing: .0071em; font-weight: 500;
  }
  .agent-card .nm {
    margin: 5px 0 3px;
    font-size: 14px; line-height: 20px; font-weight: 500;
  }
  .agent-card .ds {
    color: #737378;
    font-size: 12px; line-height: 17px;
  }
  .badge {
    display: inline-flex;
    margin-left: 6px;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px; line-height: 16px; font-weight: 500;
  }
  .badge.ai { background: #F0ECFE; color: var(--mf-plum); }
  .badge.calc { background: #E3FCF1; color: #388E3C; }

  /* Short viewports: shed the decorative height first. */
  @media (max-height: 820px) {
    .hero-title { font-size: 22px; line-height: 28px; }
    .hero-sub { font-size: 12px; line-height: 17px; }
    .mf-hero { padding: 14px 22px; margin-bottom: 10px; }
    .step .s { display: none; }
    .step { min-height: 34px; padding: 7px 10px 7px 36px; }
    .step .n { top: 7px; }
  }
  @media (max-height: 680px) {
    .mf-hero { display: none; }
    [data-testid="stMetric"] { min-height: 62px; padding: 10px 12px; }
    [data-testid="stMetricValue"] { font-size: 20px; }
  }

  @media (max-width: 900px) {
    .block-container { padding: 0.35rem 1rem 0.6rem; }
    .stepper { grid-template-columns: repeat(2, 1fr); }
    .report-shell { padding: 16px 18px; }
  }
  @media (max-width: 560px) {
    .mf-nav-status { display: none; }
    .stepper { grid-template-columns: repeat(4, 1fr); }
    .step { padding: 7px 6px; min-height: 34px; }
    .step .n { position: static; margin-bottom: 2px; }
    .step .t { font-size: 11px; }
    .hero-title { font-size: 20px; line-height: 26px; }
  }
</style>
"""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

DEFAULTS = {
    'step': 1,
    'info': None,
    'csv_path': None,
    'csv_name': None,
    'client_name': '',
    'subtitle': '2026 Q3: Quarterly Business Review',
    'context': '',
    'mapping': None,
    'campaign_rows': None,
    'site_rows': None,
    'run': None,
    'gemini_status': None,
    'progress_log': [],
}


def init_state():
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)


def goto(step: int):
    st.session_state['step'] = step


def reset_downstream():
    """Anything computed from the upload/context is invalidated by an edit."""
    st.session_state['mapping'] = None
    st.session_state['campaign_rows'] = None
    st.session_state['site_rows'] = None
    st.session_state['run'] = None
    st.session_state['progress_log'] = []


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def make_client(api_key: str, model: str) -> GeminiClient | None:
    try:
        return GeminiClient.create(api_key=api_key or None, model=model)
    except GeminiAuthError:
        return None


def provider_switcher():
    """Presentational only: shows where other model vendors would be selected.

    Nothing here is wired to the runtime, which uses the Gemini chain below.
    """
    cards = []
    for glyph, name, meta, active in PROVIDERS:
        cards.append(
            f"<div class='mf-provider{' is-active' if active else ''}'>"
            f"<div class='mf-provider-glyph'>{escape(glyph)}</div>"
            f"<div class='mf-provider-body'><div class='mf-provider-name'>{escape(name)}</div>"
            f"<div class='mf-provider-meta'>{escape(meta)}</div></div>"
            f"<div class='mf-provider-tag'>{'In use' if active else 'Preview'}</div>"
            "</div>")
    st.markdown(f"<div class='mf-providers'>{''.join(cards)}</div>",
                unsafe_allow_html=True)
    st.caption('Only Gemini is connected. The other vendors are a design preview.')


def sidebar() -> tuple[GeminiClient | None, str, bool]:
    with st.sidebar:
        st.markdown("<div class='mf-sidebar-kicker'>Workspace controls</div>",
                    unsafe_allow_html=True)
        st.caption('Use the arrow above to hide or show this panel.')

        with st.expander('Model provider', expanded=True):
            provider_switcher()

        with st.expander('Gemini credentials', expanded=False):
            env_key = os.environ.get('GEMINI_API_KEY', '')
            api_key = st.text_input(
                'API key', value='', type='password',
                placeholder='Loaded from .env' if env_key else 'Paste your Gemini API key',
                help='Leave blank to use GEMINI_API_KEY from .env.')

            model = st.selectbox('Model', SELECTABLE_MODELS,
                                 index=SELECTABLE_MODELS.index(DEFAULT_MODEL),
                                 help='If this model is busy, the next ones are tried '
                                      'automatically.')

            client = make_client(api_key, model)
            if client is not None and st.button('Test connection', width='stretch'):
                try:
                    st.session_state['gemini_status'] = f'Connected via {client.check()}'
                except GeminiError as exc:
                    st.session_state['gemini_status'] = f'Failed: {exc}'

        # Kept outside the collapsed groups so a bad key is never hidden.
        if client is None:
            st.error('No API key. Add GEMINI_API_KEY to .env or paste one in '
                     'Gemini credentials.')
        elif st.session_state['gemini_status']:
            status = st.session_state['gemini_status']
            (st.success if status.startswith('Connected') else st.error)(status)

        with st.expander('Narrative', expanded=False):
            style = st.radio('Writing style', list(narrative_agent.STYLES),
                             index=list(narrative_agent.STYLES).index(narrative_agent.DEFAULT_STYLE),
                             help='How the narrative agent should rewrite the prose. '
                                  'Numbers never change.')
            rewrite = st.toggle('Rewrite narrative with Gemini', value=True,
                                help='Off, the report keeps the deterministic wording.')

        if st.session_state['run'] is not None or st.session_state['info'] is not None:
            if st.button('Start over', width='stretch'):
                for key in DEFAULTS:
                    st.session_state[key] = DEFAULTS[key]
                st.rerun()

        return client, style, rewrite


def stepper():
    cells = []
    current = st.session_state['step']
    for i, (name, sub) in enumerate(STEPS, start=1):
        cls = 'done' if i < current else ('active' if i == current else '')
        cells.append(
            f"<div class='step {cls}'><div class='n'>{'✓' if i < current else i}</div>"
            f"<div class='t'>{name}</div><div class='s'>{sub}</div></div>")
    st.markdown(f"<div class='stepper'>{''.join(cells)}</div>", unsafe_allow_html=True)


def app_header():
    st.markdown(
        "<div class='mf-navbar'>"
        "<div class='mf-brand'>"
        "<div class='mf-mark'>✦</div>"
        "<div><div class='mf-brand-name'>Path to Conversion Copilot</div>"
        "<div class='mf-brand-meta'>Campaign intelligence workspace</div></div>"
        "</div>"
        "<div class='mf-nav-status'>Analysis engine ready</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def page_hero(eyebrow: str, title: str, subtitle: str):
    st.markdown(
        "<section class='mf-hero'><div class='mf-hero-content'>"
        f"<div class='mf-eyebrow'>{escape(eyebrow)}</div>"
        f"<div class='hero-title'>{escape(title)}</div>"
        f"<div class='hero-sub'>{escape(subtitle)}</div>"
        "</div></section>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Step 1 — upload
# ---------------------------------------------------------------------------

def save_upload(uploaded) -> str:
    os.makedirs(rc.UPLOADS_DIR, exist_ok=True)
    path = os.path.join(rc.UPLOADS_DIR, uploaded.name)
    with open(path, 'wb') as f:
        f.write(uploaded.getbuffer())
    return path


def step_upload():
    page_hero(
        'CM360 intelligence',
        'Turn every conversion path into a clear next move.',
        'Upload a Campaign Manager 360 export. Two Gemini agents and a '
        'deterministic analysis transform it into a polished, evidence-led report.',
    )

    left, right = st.columns([3, 2], gap='large')

    with left:
        st.markdown('#### 1. The export')
        uploaded = st.file_uploader(
            'CM360 path-to-conversion CSV', type=['csv'],
            help='The raw export, metadata preamble and all. Needs the '
                 '"Interaction N:" path columns.')

        if uploaded is not None and uploaded.name != st.session_state['csv_name']:
            with st.spinner('Reading and validating the export...'):
                path = save_upload(uploaded)
                try:
                    info = rc.inspect_export(path)
                except rc.ExportValidationError as exc:
                    st.error(str(exc))
                    st.session_state['info'] = None
                    st.session_state['csv_name'] = None
                    return
                st.session_state.update(
                    info=info, csv_path=path, csv_name=uploaded.name)
                reset_downstream()

        st.markdown('#### 2. The client')
        client_name = st.text_input(
            'Client name', value=st.session_state['client_name'],
            placeholder='e.g. Rates.ca',
            help='Used on the cover page and throughout the narrative.')
        subtitle = st.text_input('Report subtitle', value=st.session_state['subtitle'],
                                 placeholder='e.g. 2026 Q3: Quarterly Business Review')
        if client_name != st.session_state['client_name']:
            st.session_state['client_name'] = client_name
        st.session_state['subtitle'] = subtitle

    with right:
        info = st.session_state['info']
        if info is None:
            st.markdown('#### What runs')
            for badge, label, kind, name, desc in [
                ('ai', 'STEP 1', 'Gemini agent', 'Mapping agent',
                 'Reads the campaign and site names and works out which are Search '
                 'and which are mid-funnel. You approve it before anything is counted.'),
                ('calc', 'STEP 2', 'No AI', 'Analysis',
                 'Computes every metric and draws eight charts in plain Python. '
                 'Nothing here is an agent, so the arithmetic is reproducible.'),
                ('ai', 'STEP 3', 'Gemini agent', 'Narrative agent',
                 'Rewrites the report prose around those numbers and writes the '
                 'conclusions, using your context. Any figure it cannot verify is '
                 'rejected.'),
            ]:
                st.markdown(
                    f"<div class='agent-card'><div class='lbl'>{label} "
                    f"<span class='badge {badge}'>{kind}</span></div>"
                    f"<div class='nm'>{name}</div><div class='ds'>{desc}</div></div>",
                    unsafe_allow_html=True)
        else:
            st.markdown('#### Detected')
            c1, c2 = st.columns(2)
            c1.metric('Conversion rows', f"{info.n_rows:,}")
            c2.metric('Interaction slots', info.n_slots)
            st.caption(f"**Activity**  \n{info.activity}")
            st.caption(f"**Date range**  \n{info.date_min:%b %d, %Y} to "
                       f"{info.date_max:%b %d, %Y}")
            st.caption(f"**Campaigns ({len(info.campaigns)})**  \n"
                       + ', '.join(info.campaigns))
            st.caption(f"**Sites ({len(info.sites)})**  \n" + ', '.join(info.sites))

    info = st.session_state['info']
    if info is not None:
        with st.expander('Export metadata and first rows'):
            if info.meta:
                st.dataframe(
                    pd.DataFrame({'Field': list(info.meta), 'Value': list(info.meta.values())}),
                    hide_index=True, width='stretch', height=180)
            preview = pd.read_csv(info.path, skiprows=info.header_row, nrows=8,
                                  low_memory=False)
            st.dataframe(preview, width='stretch', height=200)

        ready = bool(st.session_state['client_name'].strip())
        if not ready:
            st.info('Add a client name to continue.')
        if st.button('Next: add context', type='primary', disabled=not ready):
            goto(2)
            st.rerun()


# ---------------------------------------------------------------------------
# Step 2 — context
# ---------------------------------------------------------------------------

CONTEXT_PLACEHOLDER = """\
What the client does, who they sell to, and what this campaign was trying to achieve.
The business question this report should answer.
Anything unusual in the period: platform launches or pauses, budget shifts, seasonality.
Vocabulary the client uses for their channels and audiences.
"""


def step_context():
    page_hero(
        'Narrative intelligence',
        'Give the analysis a sharper point of view.',
        'Add the business context behind the campaign. It shapes framing and '
        'vocabulary while every reported number remains locked to the source data.',
    )

    left, right = st.columns([3, 2], gap='large')

    with left:
        context = st.text_area(
            f"Background on {st.session_state['client_name'] or 'the client'}",
            value=st.session_state['context'], height=200,
            placeholder=CONTEXT_PLACEHOLDER)
        if context != st.session_state['context']:
            st.session_state['context'] = context
            st.session_state['run'] = None
        st.caption(f"{len(context):,} characters. Optional, but the report reads far more "
                   f"like the client's own language with it.")

    with right:
        st.markdown('#### How it is used')
        st.markdown(
            "- **The mapping agent** uses it to disambiguate campaign and site names.\n"
            "- **The narrative agent** uses it for framing, terminology and emphasis.\n"
            "- Every figure still comes only from the export."
        )
        st.info('The numbers are computed before the narrative is written, so no amount '
                'of context can move them.', icon='🔒')

    back, fwd = st.columns([1, 3])
    if back.button('Back'):
        goto(1)
        st.rerun()
    if fwd.button('Next: generate the report', type='primary'):
        goto(3)
        st.rerun()


# ---------------------------------------------------------------------------
# Step 3 — generate
# ---------------------------------------------------------------------------

# The orchestrator's stage keys, named for the screen. Only the two Gemini
# stages are called agents.
STAGE_NAMES = {
    'mapping': 'Mapping agent',
    'analysis': 'Analysis',
    'narrative': 'Narrative agent',
}


def taxonomy_editor(mapping) -> rc.Taxonomy:
    """Editable view of the mapping agent's output. Returns the taxonomy as shown."""
    tax = mapping.taxonomy

    if st.session_state['campaign_rows'] is None:
        st.session_state['campaign_rows'] = tax.campaign_rows()
        st.session_state['site_rows'] = tax.site_rows()

    channels = [rc.CHANNEL_SEARCH, rc.CHANNEL_MID_FUNNEL, rc.CHANNEL_OTHER]

    left, right = st.columns(2, gap='large')
    with left:
        st.markdown('**Campaigns to channels**')
        campaigns = st.data_editor(
            pd.DataFrame(st.session_state['campaign_rows']),
            hide_index=True, width='stretch', height=230, key='campaign_editor',
            column_config={
                'Campaign': st.column_config.TextColumn(disabled=True),
                'Channel': st.column_config.SelectboxColumn(options=channels, required=True),
            })
    with right:
        st.markdown('**Sites to platforms**')
        sites = st.data_editor(
            pd.DataFrame(st.session_state['site_rows']),
            hide_index=True, width='stretch', height=230, key='site_editor',
            column_config={
                'Site (CM360)': st.column_config.TextColumn(disabled=True),
                'Platform': st.column_config.TextColumn(
                    help='The name that appears in the report and on every chart.'),
                'Funnel role': st.column_config.SelectboxColumn(options=channels, required=True),
            })

    return rc.Taxonomy.from_rows(campaigns.to_dict('records'), sites.to_dict('records'),
                                notes=mapping.notes)


def step_generate(client: GeminiClient | None, style: str, rewrite: bool):
    info = st.session_state['info']

    page_hero(
        'Human-guided AI',
        'Map, validate, and build with confidence.',
        'Review the proposed taxonomy before deterministic analysis computes the '
        'metrics and the narrative agent turns the evidence into a client-ready story.',
    )

    # -- Stage 1: mapping ---------------------------------------------------
    if st.session_state['mapping'] is None:
        st.markdown('#### Mapping agent')
        st.write('Gemini reads the campaign and site names in your export and proposes '
                 'which are Search and which are mid-funnel.')
        if st.button('Run the mapping agent', type='primary'):
            log = []
            with st.status('Mapping agent', expanded=True) as status:
                def progress(_stage, msg):
                    log.append(msg)
                    status.write(msg)
                mapping = orchestrator.run_mapping(
                    info, st.session_state['client_name'], client,
                    st.session_state['context'], progress)
                status.update(label='Mapping agent complete', state='complete')
            st.session_state['mapping'] = mapping
            st.session_state['campaign_rows'] = None
            st.session_state['progress_log'] = log
            st.rerun()

        if st.button('Back'):
            goto(2)
            st.rerun()
        return

    mapping = st.session_state['mapping']

    st.markdown('#### Mapping agent')
    if mapping.source == 'gemini':
        st.success(f"Gemini classified {len(mapping.taxonomy.channel_map)} campaigns and "
                   f"{len(mapping.taxonomy.platform_map)} sites.", icon='✅')
    else:
        st.warning('Gemini was unavailable, so this came from naming patterns. '
                   'Check it carefully.', icon='⚠️')
    if mapping.notes:
        st.caption(f"Mapping agent note: {mapping.notes}")
    for warning in mapping.warnings:
        st.warning(warning, icon='⚠️')

    st.caption('Edit anything that looks wrong. Every number in the report depends on '
               'this mapping, so it is worth a glance.')
    tax = taxonomy_editor(mapping)

    if not tax.is_usable():
        st.error('At least one campaign must be Search or Mid-funnel, otherwise every '
                 'touch falls into "Other" and the report will be empty.')
        return

    unmapped_campaigns = set(info.campaigns) - set(tax.channel_map)
    unmapped_sites = set(info.sites) - set(tax.platform_map)
    if unmapped_campaigns or unmapped_sites:
        st.warning('Left unmapped and counted as "Other": '
                   + ', '.join(sorted(unmapped_campaigns | unmapped_sites)), icon='⚠️')

    with st.expander('Advanced: analysis window'):
        trim = st.toggle(
            'Trim the pre-activation ramp-up', value=True,
            help='Conversions before the first mid-funnel touch are Search-only by '
                 'construction and drag every mid-funnel metric toward zero.')
        override = st.date_input(
            'Window start override', value=None,
            help='Leave empty to derive it from the first mid-funnel touch in the data.')
        steady = pd.Timestamp(override) if override else None

    st.caption('Next, the analysis computes every metric and chart in plain Python, then '
               'the narrative agent writes the prose around those verified numbers.')

    back, fwd = st.columns([1, 3])
    if back.button('Re-run mapping'):
        st.session_state['mapping'] = None
        st.session_state['campaign_rows'] = None
        st.rerun()

    if fwd.button('Build the report', type='primary'):
        with st.status('Building the report...', expanded=True) as status:
            def progress(stage, msg):
                name = STAGE_NAMES.get(stage, stage.title())
                status.write(f'**{name}** · {msg}')
                status.update(label=f'{name} · {msg}')
            try:
                run = orchestrator.run_report(
                    info, tax, client_name=st.session_state['client_name'],
                    subtitle=st.session_state['subtitle'], client=client,
                    context=st.session_state['context'], style=style,
                    steady_state_start=steady, trim_rampup=trim,
                    rewrite_narrative=rewrite, progress=progress)
            except rc.ExportValidationError as exc:
                status.update(label='Analysis failed', state='error')
                st.error(str(exc))
                return
            except GeminiError as exc:
                status.update(label='Gemini failed', state='error')
                st.error(f'{exc}\n\nTurn off narrative rewriting in the sidebar to build '
                         f'the report with the deterministic wording.')
                return
            status.update(label='Report ready', state='complete')
        st.session_state['run'] = run
        goto(4)
        st.rerun()


# ---------------------------------------------------------------------------
# Step 4 — report
# ---------------------------------------------------------------------------

def render_table(table: Table):
    if not table.rows:
        return
    st.dataframe(pd.DataFrame(table.rows, columns=table.headers),
                 hide_index=True, width='stretch')


def render_section(section: Section, show_baseline: bool):
    st.markdown(f"<h2>{section.heading}</h2>", unsafe_allow_html=True)

    if section.status == 'failed' and section.note:
        st.caption(f"⚠️ {section.note}")
    elif section.status == 'generated':
        st.caption('Written by the narrative agent from every figure and chart in this '
                   'report, not reworded from a template.')

    for block in section.blocks:
        if isinstance(block, Prose):
            if block.text.strip():
                st.markdown(block.text)
                if show_baseline and block.is_rewritten:
                    with st.expander('Verified wording before the rewrite'):
                        st.markdown(block.baseline)
        elif isinstance(block, Bullets):
            for item in block.items:
                if item.strip():
                    st.markdown(f"- {item}")
            if show_baseline and block.is_rewritten:
                with st.expander('Verified wording before the rewrite'):
                    for item in block.baseline:
                        st.markdown(f"- {item}")
        elif isinstance(block, Table):
            render_table(block)
        elif isinstance(block, Figure) and block.path and os.path.exists(block.path):
            st.image(block.path, caption=block.caption, width='stretch')

    if show_baseline and section.status == 'generated':
        with st.expander('Deterministic caveats this section replaced'):
            for line in section.baseline_text().split('\n'):
                if line.strip():
                    st.markdown(f"- {line}")


def step_report():
    run = st.session_state['run']
    spec = run.spec
    m = run.metrics

    head, actions = st.columns([3, 1], gap='large')
    with head:
        st.markdown(
            "<div class='mf-page-head'>"
            f"<div class='mf-eyebrow'>Report complete</div>"
            f"<div class='mf-page-title'>{escape(spec.client_name)} · intelligence ready</div>"
            f"<div class='mf-page-meta'>{escape(spec.subtitle)}</div>"
            "</div>",
            unsafe_allow_html=True)
    with actions:
        with open(run.docx_path, 'rb') as f:
            st.download_button(
                'Download .docx', f.read(), file_name=os.path.basename(run.docx_path),
                mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                type='primary', width='stretch')
        st.caption(f"{os.path.getsize(run.docx_path) / 1_000_000:.1f} MB, "
                   f"{len(spec.sections)} sections")

    cols = st.columns(len(spec.kpis))
    for col, kpi in zip(cols, spec.kpis):
        col.metric(kpi.label, kpi.value, help=kpi.help)

    rewritten = run.narrative.n_rewritten
    failed = run.narrative.n_failed
    bits = [f"{rewritten} of {len(spec.sections)} sections rewritten by the narrative "
            f"agent"]
    if run.narrative.n_generated:
        bits.append(f"{run.narrative.n_generated} written from the full report")
    if failed:
        bits.append(f"{failed} kept the verified wording because a figure could not "
                    f"be validated")
    st.caption(' · '.join(bits))

    for warning in run.warnings:
        st.warning(warning, icon='⚠️')

    controls = st.columns([1, 1, 2])
    show_baseline = controls[0].toggle('Show pre-rewrite wording', value=False)
    if controls[1].button('Back to mapping'):
        goto(3)
        st.rerun()

    tab_report, tab_charts, tab_audit = st.tabs(['Report', 'Charts', 'Audit'])

    with tab_report:
        st.markdown("<div class='report-shell'>", unsafe_allow_html=True)
        st.markdown(f"<div class='cover-title'>{spec.title}</div>"
                    f"<div class='cover-sub'>{spec.subtitle}</div>"
                    f"<div class='cover-meta'>"
                    + '<br>'.join(spec.cover_lines) + "</div>",
                    unsafe_allow_html=True)
        for section in spec.sections:
            render_section(section, show_baseline)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab_charts:
        st.caption(f'Written to `{run.analysis.charts_dir}`')
        figures = [(s.heading, fig) for s in spec.sections for fig in s.figures()]
        for i in range(0, len(figures), 2):
            for col, (heading, fig) in zip(st.columns(2), figures[i:i + 2]):
                with col:
                    st.markdown(f"**{heading}**")
                    st.image(fig.path, caption=fig.caption, width='stretch')

    with tab_audit:
        st.markdown('#### Narrative validation')
        st.caption('Every figure in a rewritten passage must already appear in that '
                   "section's verified facts, draft or tables; a generated section is "
                   'checked against every figure in the report. Sections that failed the '
                   'check kept their deterministic wording.')
        st.dataframe(pd.DataFrame([
            {'Section': o.heading,
             'Status': 'generated (full report)' if o.status == 'generated' else o.status,
             'Unverified figures': ', '.join(o.violations) or '—',
             'Detail': o.detail or '—'}
            for o in run.narrative.outcomes]), hide_index=True, width='stretch')

        generated = [o for o in run.narrative.outcomes if o.status == 'generated']
        for outcome in generated:
            if not outcome.recommendations:
                continue
            st.markdown(f'#### Evidence behind {outcome.heading}')
            st.caption('The figures the narrative agent says each recommendation rests '
                       'on, so the reasoning can be checked against the report.')
            st.dataframe(pd.DataFrame([
                {'Priority': str(r.get('priority', '')),
                 'Action': str(r.get('action', '')),
                 'Evidence relied on': ' · '.join(str(e) for e in r.get('evidence') or [])
                                       or '—'}
                for r in outcome.recommendations]), hide_index=True, width='stretch')

        st.markdown('#### Taxonomy used')
        st.dataframe(m.taxonomy, hide_index=True, width='stretch')

        st.markdown('#### Key figures')
        st.dataframe(pd.DataFrame(
            [{'Metric': k, 'Value': v}
             for section in spec.sections for k, v in section.facts.items()]
        ).drop_duplicates(subset=['Metric']), hide_index=True, width='stretch')


# ---------------------------------------------------------------------------

def main():
    init_state()
    st.markdown(STYLE_CSS, unsafe_allow_html=True)
    client, style, rewrite = sidebar()
    app_header()
    stepper()

    step = st.session_state['step']
    if step == 1 or st.session_state['info'] is None:
        step_upload()
    elif step == 2:
        step_context()
    elif step == 3:
        step_generate(client, style, rewrite)
    elif step == 4 and st.session_state['run'] is not None:
        step_report()
    else:
        goto(1)
        st.rerun()


if __name__ == '__main__':
    main()
