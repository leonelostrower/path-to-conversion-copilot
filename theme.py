"""Monks Flow 2.0 styling for the Streamlit front end.

One palette, one type scale, one set of radii and shadows, all taken from the
MF 2.0 tokens. Plum is the only accent; ruby appears solely on genuine errors.
Nothing here is decorative for its own sake: the app is locked to the viewport,
so the stylesheet also carries the layout rules that keep each screen inside it.
"""

from __future__ import annotations

FONT_STACK = "'Helvetica Now for Monks', 'Helvetica Neue', Helvetica, Arial, sans-serif"

# The stylesheet carries percentages and braces, so the font stack is injected
# with a plain token replacement rather than %-formatting or an f-string.
STYLESHEET = """
<style>
  :root {
    --font: __FONT_STACK__;

    /* Ink */
    --ink: #3C3C3E;
    --ink-soft: #5D5D60;
    --muted: #737378;
    --faint: #A1A1A5;

    /* Accent — the only brand colour in the interface */
    --plum: #4F24EE;
    --plum-press: #3B11D5;
    --plum-mid: #7252E9;
    --plum-200: #E1D9FC;
    --plum-100: #F0ECFE;
    --plum-50: #F7F6FE;

    /* Reserved for real failures, nothing else */
    --ruby: #FF245B;
    --ruby-50: #FFF3F6;

    /* Surfaces */
    --surface: #FFFFFF;
    --canvas: #F4F4F6;
    --grey-50: #F7F7F7;
    --grey-100: #F2F2F2;
    --grey-200: #E4E4E5;

    --line: rgba(0, 0, 0, 0.10);
    --line-strong: rgba(0, 0, 0, 0.19);

    --shadow-2: 0 2px 7px rgba(0, 0, 0, 0.10);
    --shadow-4: 0 4px 16px rgba(0, 0, 0, 0.10);

    --r-sm: 8px;
    --r-md: 12px;
    --r-lg: 16px;
    --r-xl: 24px;
  }

  /* ---------------------------------------------------------------- type */
  html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
  h1, h2, h3, h4, h5, h6, p, span, div, li, label, small, strong, em,
  input, textarea, select, button, [data-baseweb] {
    font-family: var(--font);
  }
  /* Material ligature icons must keep their own family. */
  [data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons,
  span[translate="no"] {
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
  }

  html, body, [data-testid="stAppViewContainer"] { color: var(--ink); }
  h1, h2, h3, h4, h5, h6 {
    color: var(--ink);
    font-weight: 500 !important;
    letter-spacing: -0.04em !important;
  }
  p, li, label { letter-spacing: -0.01em; }
  strong, b { font-weight: 500; }
  a, a:visited { color: var(--plum); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* -------------------------------------------------------------- canvas */
  [data-testid="stAppViewContainer"] {
    background:
      radial-gradient(115% 78% at 50% -18%, var(--plum-50) 0%, transparent 58%),
      var(--canvas);
  }

  /* Viewport-locked shell: the page itself never scrolls. */
  html, body { overflow: hidden !important; }
  [data-testid="stAppViewContainer"] { max-height: 100dvh; overflow: hidden !important; }
  [data-testid="stMain"] { overflow: hidden !important; }

  /* The toolbar stays: it hosts the control that reopens the settings rail. */
  [data-testid="stHeader"] {
    position: relative !important;
    height: 48px;
    min-height: 48px;
    background: transparent;
    z-index: 60;
  }
  [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
  [data-testid="stMainMenu"], footer { display: none !important; }

  .block-container {
    height: calc(100dvh - 48px);
    max-width: 1080px;
    padding: 0 32px 14px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .block-container > [data-testid="stVerticalBlock"] {
    flex: 1;
    min-height: 0;
    gap: 14px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--grey-200) transparent;
    padding-right: 6px;
  }
  .block-container > [data-testid="stVerticalBlock"]::-webkit-scrollbar { width: 6px; }
  .block-container > [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: var(--grey-200);
  }

  /* ------------------------------------------------------------- app bar */
  .mf-navbar {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 0 2px 10px;
    border-bottom: 1px solid var(--line);
  }
  .mf-brand { display: flex; align-items: center; gap: 10px; }
  .mf-mark {
    width: 30px; height: 30px;
    display: grid; place-items: center;
    border-radius: 9px;
    background: linear-gradient(145deg, var(--plum-mid), var(--plum));
    color: #fff;
    font-size: 15px; line-height: 1;
    box-shadow: var(--shadow-2);
  }
  .mf-brand-name {
    font-size: 15px; line-height: 20px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  .mf-brand-meta { color: var(--muted); font-size: 11px; line-height: 15px; }
  .mf-chip {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 12px;
    border: 1px solid var(--plum-200);
    border-radius: 999px;
    background: var(--plum-50);
    color: var(--plum);
    font-size: 12px; line-height: 16px; font-weight: 500;
  }
  .mf-chip::before {
    content: ''; width: 6px; height: 6px; border-radius: 50%;
    background: var(--plum);
  }

  /* ------------------------------------------------------------ workflow */
  .stepper {
    flex: 0 0 auto;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    margin: 0 auto;
    padding: 6px;
    width: 100%;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: rgba(255, 255, 255, 0.86);
    box-shadow: var(--shadow-2);
    backdrop-filter: blur(12px);
  }
  .step {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    padding: 8px 10px;
    border-radius: var(--r-md);
    text-align: center;
    transition: all .2s ease;
  }
  .step .n {
    width: 22px; height: 22px;
    display: grid; place-items: center;
    border-radius: 50%;
    background: var(--grey-100);
    color: var(--muted);
    font-size: 11px; line-height: 1; font-weight: 500;
  }
  .step .t {
    color: var(--ink-soft);
    font-size: 13px; line-height: 17px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  .step.done { background: var(--plum-50); }
  .step.done .n { background: var(--plum-100); color: var(--plum); }
  .step.active { background: var(--plum-100); }
  .step.active .n {
    background: var(--plum); color: #fff;
    box-shadow: 0 2px 7px rgba(79, 36, 238, 0.28);
  }
  .step.active .t { color: var(--plum); }

  /* ---------------------------------------------------------------- hero */
  .mf-hero {
    position: relative;
    flex: 0 0 auto;
    overflow: hidden;
    padding: 26px 32px 28px;
    border: 1px solid rgba(255, 255, 255, 0.8);
    border-radius: var(--r-xl);
    background: linear-gradient(101deg, #CFE8FC 0%, #ECF4FE 16%,
                #F7F6FE 52%, #FAF6FD 87%, #FFF3F6 100%);
    box-shadow: var(--shadow-4);
    text-align: center;
  }
  .mf-hero::after {
    content: '';
    position: absolute;
    width: 210px; height: 210px;
    right: -66px; top: -92px;
    border-radius: 50%;
    border: 40px solid rgba(79, 36, 238, 0.09);
  }
  .mf-hero-content { position: relative; z-index: 1; margin: 0 auto; max-width: 660px; }
  .mf-eyebrow {
    display: inline-flex; align-items: center; gap: 6px;
    margin-bottom: 10px;
    padding: 3px 11px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.78);
    color: var(--plum);
    font-size: 11px; line-height: 16px; font-weight: 500;
    letter-spacing: 0.0071em;
    text-transform: uppercase;
    backdrop-filter: blur(8px);
  }
  .hero-title {
    margin-bottom: 6px;
    color: var(--ink);
    font-size: 32px; line-height: 38px; font-weight: 400;
    letter-spacing: -0.04em;
  }
  .hero-sub {
    margin: 0 auto;
    max-width: 560px;
    color: var(--ink-soft);
    font-size: 14px; line-height: 20px;
    letter-spacing: -0.01em;
  }

  /* Centred page header for screens where a hero would waste height */
  .mf-page-head { text-align: center; padding: 2px 0 0; }
  .mf-page-title {
    color: var(--ink);
    font-size: 26px; line-height: 32px; font-weight: 400;
    letter-spacing: -0.04em;
  }
  .mf-page-meta { color: var(--muted); font-size: 13px; line-height: 18px; }

  /* Section heading, centred to match the rest of the composition */
  .mf-section {
    margin: 2px 0 2px;
    text-align: center;
  }
  .mf-section-title {
    color: var(--ink);
    font-size: 17px; line-height: 24px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  .mf-section-note { color: var(--muted); font-size: 12px; line-height: 17px; }

  /* -------------------------------------------------------------- panels */
  .mf-card {
    padding: 18px 20px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    box-shadow: var(--shadow-2);
  }
  .mf-stage {
    position: relative;
    height: 100%;
    padding: 16px 18px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    box-shadow: var(--shadow-2);
    text-align: center;
    transition: all .2s ease;
  }
  .mf-stage:hover {
    transform: translateY(-2px);
    border-color: var(--plum-200);
    box-shadow: var(--shadow-4);
  }
  .mf-stage-glyph {
    width: 34px; height: 34px;
    margin: 0 auto 10px;
    display: grid; place-items: center;
    border-radius: 10px;
    background: var(--plum-100);
    color: var(--plum);
    font-size: 14px; font-weight: 500;
  }
  .mf-stage-name {
    margin-bottom: 4px;
    font-size: 14px; line-height: 20px; font-weight: 500;
  }
  .mf-stage-desc { color: var(--muted); font-size: 12px; line-height: 17px; }
  .mf-stage-tag {
    display: inline-flex;
    margin-top: 10px;
    padding: 2px 10px;
    border-radius: 999px;
    background: var(--grey-100);
    color: var(--muted);
    font-size: 10px; line-height: 15px; font-weight: 500;
    letter-spacing: 0.0071em;
    text-transform: uppercase;
  }
  .mf-stage.is-ai .mf-stage-tag { background: var(--plum-100); color: var(--plum); }

  /* Key/value summary of a detected export */
  .mf-detail {
    padding: 2px 18px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    box-shadow: var(--shadow-2);
  }
  .mf-detail-row { padding: 10px 0; border-bottom: 1px solid var(--line); }
  .mf-detail-row:last-child { border-bottom: none; }
  .mf-detail-key {
    margin-bottom: 2px;
    color: var(--faint);
    font-size: 10px; line-height: 15px; font-weight: 500;
    letter-spacing: 0.0071em;
    text-transform: uppercase;
  }
  .mf-detail-val { color: var(--ink); font-size: 13px; line-height: 18px; }

  /* ------------------------------------------------------------ controls */
  div.stButton > button, div.stDownloadButton > button {
    min-height: 40px;
    padding: 0 20px;
    border: 1px solid var(--line-strong);
    border-radius: var(--r-md);
    background: var(--surface);
    color: var(--ink);
    font-size: 14px; line-height: 20px; font-weight: 500;
    letter-spacing: -0.01em;
    box-shadow: none;
    transition: all .2s ease;
  }
  div.stButton > button:hover, div.stDownloadButton > button:hover {
    border-color: var(--plum);
    color: var(--plum);
    background: var(--plum-50);
  }
  div.stButton > button:active, div.stDownloadButton > button:active {
    transform: scale(.98);
  }
  div.stButton > button[kind="primary"], div.stDownloadButton > button[kind="primary"] {
    border-color: var(--plum);
    background: var(--plum);
    color: #fff;
    box-shadow: 0 2px 7px rgba(79, 36, 238, 0.24);
  }
  div.stButton > button[kind="primary"]:hover,
  div.stDownloadButton > button[kind="primary"]:hover {
    border-color: var(--plum-press);
    background: var(--plum-press);
    color: #fff;
  }
  div.stButton > button:disabled, div.stButton > button:disabled:hover,
  div.stDownloadButton > button:disabled {
    border-color: var(--line);
    background: var(--grey-100);
    color: var(--faint);
    box-shadow: none;
    cursor: not-allowed;
    transform: none;
  }

  [data-testid="stTextInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-baseweb="select"] > div,
  [data-testid="stDateInput"] input {
    border: 1px solid var(--line) !important;
    border-radius: var(--r-md) !important;
    background: var(--grey-50) !important;
    color: var(--ink) !important;
    box-shadow: none !important;
    font-size: 14px !important;
  }
  [data-testid="stTextInput"] input { min-height: 40px; }
  [data-testid="stTextInput"] input:focus,
  [data-testid="stTextArea"] textarea:focus {
    border-color: var(--plum) !important;
    background: var(--surface) !important;
    box-shadow: 0 0 0 3px rgba(79, 36, 238, 0.10) !important;
  }
  input::placeholder, textarea::placeholder {
    color: var(--faint) !important;
    opacity: 1 !important;
  }
  textarea::placeholder { line-height: 21px; }
  [data-testid="stWidgetLabel"] { margin-bottom: 3px; }
  [data-testid="stWidgetLabel"] p {
    color: var(--ink);
    font-size: 13px !important; line-height: 18px;
    font-weight: 500;
  }

  [data-testid="stFileUploader"] {
    padding: 6px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    box-shadow: var(--shadow-2);
  }
  [data-testid="stFileUploaderDropzone"] {
    min-height: 96px;
    padding: 12px 16px;
    border: 1px dashed var(--plum-200);
    border-radius: var(--r-md);
    background: var(--plum-50);
  }
  [data-testid="stFileUploaderDropzone"] button {
    border-color: var(--plum);
    border-radius: var(--r-md);
    background: var(--surface);
    color: var(--plum);
  }

  /* Toggles, radios and checkboxes follow the accent */
  [data-baseweb="checkbox"] [data-checked="true"],
  [data-testid="stToggle"] [data-checked="true"] { background: var(--plum) !important; }
  [data-baseweb="radio"] [data-checked="true"] { border-color: var(--plum) !important; }
  [data-baseweb="radio"] [data-checked="true"] > div { background: var(--plum) !important; }

  [data-testid="stMetric"] {
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    box-shadow: var(--shadow-2);
    text-align: center;
  }
  [data-testid="stMetricLabel"] { justify-content: center; }
  [data-testid="stMetricLabel"] p {
    color: var(--muted);
    font-size: 11px !important; line-height: 15px;
    font-weight: 500;
    letter-spacing: 0.0071em;
    text-transform: uppercase;
  }
  [data-testid="stMetricValue"] {
    justify-content: center;
    color: var(--ink);
    font-size: 26px; font-weight: 400;
    letter-spacing: -0.04em;
  }

  /* Alerts: one palette. Ruby is reserved for errors. */
  [data-testid="stAlert"] {
    padding: 12px 16px;
    border: 1px solid var(--plum-200);
    border-left: 3px solid var(--plum);
    border-radius: var(--r-md);
    background: var(--plum-50);
    color: var(--ink);
    box-shadow: none;
  }
  [data-testid="stAlert"] p { color: var(--ink); font-size: 13px; line-height: 19px; }
  [data-testid="stAlertContentError"], [data-testid="stAlertContentError"] p {
    color: var(--ink);
  }
  div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {
    border-color: rgba(255, 36, 91, 0.28);
    border-left-color: var(--ruby);
    background: var(--ruby-50);
  }

  [data-testid="stExpander"] {
    border: 1px solid var(--line);
    border-radius: var(--r-md);
    background: var(--surface);
    box-shadow: none;
    overflow: hidden;
  }
  [data-testid="stExpander"] summary {
    font-size: 13px; font-weight: 500;
  }
  [data-testid="stExpander"] summary:hover { color: var(--plum); }

  [data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {
    border: 1px solid var(--line);
    border-radius: var(--r-md);
    overflow: hidden;
  }
  [data-testid="stImage"] img { border-radius: var(--r-md); }
  [data-testid="stCaptionContainer"] p {
    margin-bottom: 0;
    color: var(--muted);
    font-size: 12px; line-height: 17px;
  }
  hr { border-color: var(--line); }

  /* Status container used while the agents run */
  [data-testid="stStatusWidget"], [data-testid="stStatus"] {
    border: 1px solid var(--line);
    border-radius: var(--r-md);
    background: var(--surface);
  }

  /* ----------------------------------------------------------------- tabs */
  [data-testid="stElementContainer"]:has(> [data-testid="stTabs"]) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  [data-testid="stTabs"] {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    flex: 0 0 auto;
    justify-content: center;
    gap: 6px;
    margin: 0 auto;
    padding: 4px;
    border-radius: var(--r-md);
    background: var(--grey-100);
  }
  [data-testid="stTabs"] button[role="tab"] {
    height: 34px;
    padding: 0 20px;
    border-radius: var(--r-sm);
    color: var(--muted);
    font-size: 13px; font-weight: 500;
  }
  [data-testid="stTabs"] button[aria-selected="true"] {
    background: var(--surface);
    color: var(--plum);
    box-shadow: var(--shadow-2);
  }
  [data-testid="stTabs"] [data-baseweb="tab-highlight"],
  [data-testid="stTabs"] [data-baseweb="tab-border"] { display: none; }
  [data-testid="stTabs"] [data-baseweb="tab-panel"] {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 10px 6px 0 0;
    scrollbar-width: thin;
    scrollbar-color: var(--grey-200) transparent;
  }
  [data-testid="stTabs"] [data-baseweb="tab-panel"]::-webkit-scrollbar { width: 6px; }
  [data-testid="stTabs"] [data-baseweb="tab-panel"]::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: var(--grey-200);
  }

  /* -------------------------------------------------------------- report */
  .report-shell {
    padding: 30px 34px;
    border: 1px solid var(--line);
    border-radius: var(--r-xl);
    background: var(--surface);
    box-shadow: var(--shadow-2);
  }
  .report-cover { text-align: center; }
  .cover-title {
    color: var(--ink);
    font-size: 28px; line-height: 34px; font-weight: 400;
    letter-spacing: -0.04em;
  }
  .cover-sub {
    margin: 4px 0 16px;
    color: var(--plum);
    font-size: 16px; line-height: 24px;
  }
  .cover-meta {
    display: inline-block;
    padding: 14px 20px;
    border: 1px solid var(--line);
    border-radius: var(--r-md);
    background: var(--plum-50);
    color: var(--ink-soft);
    font-size: 13px; line-height: 22px;
    text-align: left;
  }
  .report-shell h2 {
    margin: 30px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line);
    color: var(--ink);
    font-size: 20px; line-height: 28px;
  }
  .report-shell h2:first-child { margin-top: 0; }

  /* -------------------------------------------------------- settings rail */
  [data-testid="stSidebar"] {
    border-right: 1px solid var(--line);
    background: var(--surface);
  }
  [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 14px; }
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 9px; }
  [data-testid="stSidebar"] div.stButton > button {
    min-height: 44px;
    padding: 0 14px;
    border-color: var(--line);
    border-radius: var(--r-md);
    justify-content: flex-start;
    font-size: 13px;
  }
  [data-testid="stSidebar"] div.stButton > button p {
    font-size: 13px;
    font-weight: 500;
  }
  .mf-rail-title {
    color: var(--ink);
    font-size: 15px; line-height: 20px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  .mf-rail-label {
    margin: 6px 0 2px;
    color: var(--faint);
    font-size: 10px; line-height: 15px; font-weight: 500;
    letter-spacing: 0.0071em;
    text-transform: uppercase;
  }

  /* Open control lives in the toolbar, so it carries a label */
  button[data-testid="stExpandSidebarButton"] {
    display: inline-flex !important;
    align-items: center;
    gap: 6px;
    height: 34px;
    padding: 0 12px !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 10px !important;
    background: var(--surface) !important;
    color: var(--plum) !important;
    box-shadow: var(--shadow-2) !important;
  }
  button[data-testid="stExpandSidebarButton"]::after {
    content: 'Settings';
    color: var(--ink);
    font-size: 13px; font-weight: 500;
    letter-spacing: -0.01em;
  }
  button[data-testid="stExpandSidebarButton"]:hover {
    border-color: var(--plum) !important;
    background: var(--plum-50) !important;
  }
  /* Streamlit reveals the close control on hover; keep it permanent. */
  [data-testid="stSidebarCollapseButton"] {
    visibility: visible !important;
    opacity: 1 !important;
  }
  [data-testid="stSidebarCollapseButton"] button {
    width: 32px; height: 32px;
    border: 1px solid var(--line-strong) !important;
    border-radius: 9px !important;
    background: var(--surface) !important;
    color: var(--plum) !important;
  }
  [data-testid="stSidebarCollapseButton"] button:hover {
    border-color: var(--plum) !important;
    background: var(--plum-50) !important;
  }

  /* ------------------------------------------------------------- spacing */
  [data-testid="stColumn"] [data-testid="stVerticalBlock"] { gap: 12px; }
  [data-testid="stColumn"] { display: flex; flex-direction: column; }

  /* ------------------------------------------------- short viewports */
  @media (max-height: 860px) {
    .mf-hero { padding: 18px 28px 20px; }
    .hero-title { font-size: 26px; line-height: 32px; }
    .hero-sub { font-size: 13px; line-height: 19px; }
    .report-shell { padding: 22px 24px; }
  }
  @media (max-height: 720px) {
    .mf-hero { padding: 14px 24px 15px; }
    .mf-eyebrow { display: none; }
    .hero-title { font-size: 22px; line-height: 27px; }
    .step { padding: 6px 8px; }
    [data-testid="stMetric"] { padding: 10px 12px; }
    [data-testid="stMetricValue"] { font-size: 21px; }
  }

  @media (max-width: 900px) {
    .block-container { padding: 0 16px 12px; }
    .stepper { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
""".replace('__FONT_STACK__', FONT_STACK)
