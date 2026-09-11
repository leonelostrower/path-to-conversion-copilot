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
                   page_icon='📊', layout='wide',
                   initial_sidebar_state='expanded')

STEPS = [
    ('Upload', 'Export and client'),
    ('Context', 'Background for the narrative'),
    ('Generate', 'Mapping, analysis, narrative'),
    ('Report', 'Read and download'),
]

STYLE_CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1180px; }
  .stepper { display: flex; gap: 0.4rem; margin: 0 0 1.6rem 0; }
  .step {
    flex: 1; padding: 0.55rem 0.8rem; border-radius: 8px;
    border: 1px solid rgba(128,128,128,0.25); font-size: 0.82rem; line-height: 1.25;
  }
  .step .n { font-weight: 700; font-size: 0.72rem; opacity: 0.55; letter-spacing: .06em; }
  .step .t { font-weight: 600; }
  .step .s { opacity: 0.62; font-size: 0.74rem; }
  .step.done { border-color: #356854; background: rgba(53,104,84,0.10); }
  .step.active { border-color: #356854; background: rgba(53,104,84,0.24); }
  .hero-title { font-size: 1.9rem; font-weight: 700; margin-bottom: 0.15rem; }
  .hero-sub { opacity: 0.7; margin-bottom: 1.4rem; }
  .report-shell {
    border: 1px solid rgba(128,128,128,0.22); border-radius: 12px;
    padding: 1.6rem 2rem; margin-top: 0.6rem;
  }
  .report-shell h2 {
    font-size: 1.28rem; margin: 1.7rem 0 0.6rem 0;
    padding-bottom: 0.3rem; border-bottom: 2px solid #356854;
  }
  .report-shell h2:first-child { margin-top: 0; }
  .cover-title { font-size: 1.75rem; font-weight: 700; line-height: 1.2; }
  .cover-sub { font-size: 1.15rem; opacity: 0.75; margin-bottom: 0.7rem; }
  .cover-meta { font-size: 0.86rem; opacity: 0.7; line-height: 1.6; }
  .agent-card {
    border: 1px solid rgba(128,128,128,0.22); border-radius: 10px;
    padding: 0.9rem 1.1rem; height: 100%;
  }
  .agent-card .lbl { font-size: 0.7rem; letter-spacing: .07em; opacity: 0.55; font-weight: 700; }
  .agent-card .nm { font-weight: 650; margin: 0.15rem 0 0.3rem 0; }
  .agent-card .ds { font-size: 0.8rem; opacity: 0.72; line-height: 1.4; }
  .badge {
    display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px;
    font-size: 0.7rem; font-weight: 600;
  }
  .badge.ai { background: rgba(66,133,244,0.18); color: #4285F4; }
  .badge.calc { background: rgba(53,104,84,0.2); color: #2e8b6a; }
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


def sidebar() -> tuple[GeminiClient | None, str, bool]:
    with st.sidebar:
        st.markdown('### Gemini')

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
        if client is None:
            st.error('No API key. Add GEMINI_API_KEY to .env or paste one above.')
        else:
            if st.button('Test connection', width='stretch'):
                try:
                    st.session_state['gemini_status'] = f'Connected via {client.check()}'
                except GeminiError as exc:
                    st.session_state['gemini_status'] = f'Failed: {exc}'
            if st.session_state['gemini_status']:
                status = st.session_state['gemini_status']
                (st.success if status.startswith('Connected') else st.error)(status)
            else:
                st.caption('Key loaded. Ready.')

        st.divider()
        st.markdown('### Narrative')
        style = st.radio('Writing style', list(narrative_agent.STYLES),
                         index=list(narrative_agent.STYLES).index(narrative_agent.DEFAULT_STYLE),
                         help='How the narrative agent should rewrite the prose. '
                              'Numbers never change.')
        rewrite = st.toggle('Rewrite narrative with Gemini', value=True,
                            help='Off, the report keeps the deterministic wording.')

        st.divider()
        st.markdown('### Progress')
        current = st.session_state['step']
        for i, (name, _) in enumerate(STEPS, start=1):
            mark = '✓' if i < current else ('▸' if i == current else '·')
            st.markdown(f"{mark} **{name}**" if i == current else f"{mark} {name}")

        if st.session_state['run'] is not None or st.session_state['info'] is not None:
            st.divider()
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
            f"<div class='step {cls}'><div class='n'>STEP {i}</div>"
            f"<div class='t'>{name}</div><div class='s'>{sub}</div></div>")
    st.markdown(f"<div class='stepper'>{''.join(cells)}</div>", unsafe_allow_html=True)


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
    st.markdown("<div class='hero-title'>Path to Conversion Copilot</div>"
                "<div class='hero-sub'>Upload a Campaign Manager 360 path-to-conversion "
                "export. Two Gemini agents and a deterministic analysis between them "
                "turn it into a written report.</div>",
                unsafe_allow_html=True)

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
                st.write('')
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
                    hide_index=True, width='stretch')
            preview = pd.read_csv(info.path, skiprows=info.header_row, nrows=8,
                                  low_memory=False)
            st.dataframe(preview, width='stretch')

        st.divider()
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
    st.markdown("<div class='hero-title'>Context for the narrative</div>"
                "<div class='hero-sub'>Whatever you write here is given to the narrative "
                "agent as background. It shapes the framing and vocabulary; it can never "
                "change a number.</div>", unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap='large')

    with left:
        context = st.text_area(
            f"Background on {st.session_state['client_name'] or 'the client'}",
            value=st.session_state['context'], height=340,
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

    st.divider()
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
            hide_index=True, width='stretch', key='campaign_editor',
            column_config={
                'Campaign': st.column_config.TextColumn(disabled=True),
                'Channel': st.column_config.SelectboxColumn(options=channels, required=True),
            })
    with right:
        st.markdown('**Sites to platforms**')
        sites = st.data_editor(
            pd.DataFrame(st.session_state['site_rows']),
            hide_index=True, width='stretch', key='site_editor',
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

    st.markdown("<div class='hero-title'>Generate the report</div>"
                "<div class='hero-sub'>The mapping agent proposes the taxonomy, you "
                "approve it, then the analysis computes the numbers and the narrative "
                "agent writes them up.</div>", unsafe_allow_html=True)

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

        st.divider()
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

    st.divider()
    st.markdown('#### Analysis and narrative agent')
    st.write('The analysis computes the metrics and charts in plain Python, with no AI '
             'involved. The narrative agent then writes the prose around those numbers, '
             'and any figure it cannot verify against them is rejected.')

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
        st.markdown(f"<div class='hero-title'>{spec.client_name} · report ready</div>"
                    f"<div class='hero-sub'>{spec.subtitle}</div>",
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
