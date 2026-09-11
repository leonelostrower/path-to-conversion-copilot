"""Streamlit front end for Path to Conversion Copilot.

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
from theme import STYLESHEET

st.set_page_config(page_title='Path to Conversion Copilot',
                   page_icon='✦', layout='wide',
                   initial_sidebar_state='collapsed')

STEPS = [
    ('Upload', 'Export and client'),
    ('Context', 'Background for the narrative'),
    ('Generate', 'Mapping, analysis, narrative'),
    ('Report', 'Read and download'),
]

# Vendors offered in the rail. Gemini is the only one wired to the runtime, so
# picking another swaps the model list and locks the connection test.
GEMINI = 'gemini'
PROVIDERS = [
    {'key': GEMINI, 'glyph': 'G', 'name': 'Gemini', 'models': SELECTABLE_MODELS},
    {'key': 'anthropic', 'glyph': 'C', 'name': 'Claude',
     'models': ['claude-opus-4.5', 'claude-sonnet-4.5', 'claude-haiku-4.5']},
    {'key': 'openai', 'glyph': 'O', 'name': 'GPT',
     'models': ['gpt-5.2', 'gpt-5.2-mini', 'gpt-5.2-nano']},
    {'key': 'xai', 'glyph': 'X', 'name': 'Grok',
     'models': ['grok-4.6', 'grok-4.6-fast']},
    {'key': 'meta', 'glyph': 'L', 'name': 'Llama',
     'models': ['llama-4-maverick', 'llama-4-scout']},
]

LOCKED_TO_GEMINI = 'Gemini is the only provider available at the moment.'


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
    'provider': GEMINI,
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
# Shared chrome
# ---------------------------------------------------------------------------

def app_header():
    st.markdown(
        "<div class='mf-navbar'>"
        "<div class='mf-brand'>"
        "<div class='mf-mark'>✦</div>"
        "<div><div class='mf-brand-name'>Path to Conversion Copilot</div>"
        "<div class='mf-brand-meta'>Campaign intelligence workspace</div></div>"
        "</div>"
        "<div class='mf-chip'>Analysis engine ready</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def stepper():
    current = st.session_state['step']
    cells = []
    for i, (name, _) in enumerate(STEPS, start=1):
        cls = 'done' if i < current else ('active' if i == current else '')
        cells.append(f"<div class='step {cls}'><div class='n'>{'✓' if i < current else i}</div>"
                     f"<div class='t'>{escape(name)}</div></div>")
    st.markdown(f"<div class='stepper'>{''.join(cells)}</div>", unsafe_allow_html=True)


def page_hero(eyebrow: str, title: str, subtitle: str):
    st.markdown(
        "<section class='mf-hero'><div class='mf-hero-content'>"
        f"<div class='mf-eyebrow'>{escape(eyebrow)}</div>"
        f"<div class='hero-title'>{escape(title)}</div>"
        f"<div class='hero-sub'>{escape(subtitle)}</div>"
        "</div></section>",
        unsafe_allow_html=True,
    )


def section_header(title: str, note: str = ''):
    st.markdown(
        f"<div class='mf-section'><div class='mf-section-title'>{escape(title)}</div>"
        + (f"<div class='mf-section-note'>{escape(note)}</div>" if note else '')
        + "</div>",
        unsafe_allow_html=True,
    )


def centered(width: float = 1.3):
    """A centred column, so primary actions sit on the page's axis."""
    side = max((3 - width) / 2, 0.1)
    return st.columns([side, width, side])[1]


# ---------------------------------------------------------------------------
# Settings rail
# ---------------------------------------------------------------------------

def make_client(api_key: str, model: str) -> GeminiClient | None:
    try:
        return GeminiClient.create(api_key=api_key or None, model=model)
    except GeminiAuthError:
        return None


def provider_picker() -> dict:
    """Vendor list. Selecting one drives the credential fields underneath."""
    st.markdown("<div class='mf-rail-label'>Model provider</div>", unsafe_allow_html=True)
    active = st.session_state['provider']
    for provider in PROVIDERS:
        chosen = provider['key'] == active
        if st.button(f"{provider['glyph']}   {provider['name']}",
                     key=f"provider_{provider['key']}", width='stretch',
                     type='primary' if chosen else 'secondary'):
            st.session_state['provider'] = provider['key']
            st.rerun()
    return next(p for p in PROVIDERS if p['key'] == st.session_state['provider'])


def sidebar() -> tuple[GeminiClient | None, str, bool]:
    with st.sidebar:
        st.markdown("<div class='mf-rail-title'>Settings</div>", unsafe_allow_html=True)

        provider = provider_picker()
        live = provider['key'] == GEMINI

        st.markdown("<div class='mf-rail-label'>Credentials</div>", unsafe_allow_html=True)
        env_key = os.environ.get('GEMINI_API_KEY', '')
        api_key = st.text_input(
            'API key', value='', type='password', disabled=not live,
            placeholder=('Loaded from .env' if env_key else f"{provider['name']} API key")
            if live else LOCKED_TO_GEMINI,
            help=None if live else LOCKED_TO_GEMINI)

        models = provider['models']
        model = st.selectbox(
            'Model', models,
            index=models.index(DEFAULT_MODEL) if live else 0,
            disabled=not live,
            help=None if live else LOCKED_TO_GEMINI)

        client = make_client(api_key if live else '', model if live else DEFAULT_MODEL)
        if st.button('Test connection', width='stretch',
                     disabled=not live or client is None,
                     help=None if live else LOCKED_TO_GEMINI):
            try:
                st.session_state['gemini_status'] = f'Connected via {client.check()}'
            except GeminiError as exc:
                st.session_state['gemini_status'] = f'Failed: {exc}'

        if client is None:
            st.error('No API key found. Add GEMINI_API_KEY to .env or paste one above.')
        elif st.session_state['gemini_status']:
            status = st.session_state['gemini_status']
            (st.success if status.startswith('Connected') else st.error)(status)

        st.markdown("<div class='mf-rail-label'>Narrative</div>", unsafe_allow_html=True)
        style = st.radio('Writing style', list(narrative_agent.STYLES),
                         index=list(narrative_agent.STYLES).index(narrative_agent.DEFAULT_STYLE))
        rewrite = st.toggle('Rewrite with the narrative agent', value=True)

        if st.session_state['run'] is not None or st.session_state['info'] is not None:
            if st.button('Start over', width='stretch'):
                for key in DEFAULTS:
                    st.session_state[key] = DEFAULTS[key]
                st.rerun()

        return client, style, rewrite


# ---------------------------------------------------------------------------
# Step 1 — upload
# ---------------------------------------------------------------------------

STAGES = [
    ('1', 'Mapping agent', 'Sorts campaigns into Search and mid-funnel, and names '
                           'every platform. You approve it before anything counts.',
     'Gemini', True),
    ('2', 'Analysis', 'Computes every metric and draws all eight charts in plain '
                      'Python, so the arithmetic is reproducible.', 'No AI', False),
    ('3', 'Narrative agent', 'Writes the prose and conclusions around those numbers. '
                             'Any figure it cannot verify is rejected.', 'Gemini', True),
]


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
        'Upload a Campaign Manager 360 export and two agents, with a deterministic '
        'analysis between them, produce a client-ready report.',
    )

    left, right = st.columns(2, gap='large')

    with left:
        section_header('The export')
        uploaded = st.file_uploader('CM360 path-to-conversion CSV', type=['csv'])

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

    with right:
        section_header('The client')
        client_name = st.text_input(
            'Client name', value=st.session_state['client_name'],
            placeholder='Rates.ca')
        subtitle = st.text_input(
            'Report subtitle', value=st.session_state['subtitle'],
            placeholder='2026 Q3 · Quarterly Business Review')
        if client_name != st.session_state['client_name']:
            st.session_state['client_name'] = client_name
        st.session_state['subtitle'] = subtitle

    info = st.session_state['info']

    if info is None:
        for col, (glyph, name, desc, tag, is_ai) in zip(st.columns(3, gap='medium'), STAGES):
            col.markdown(
                f"<div class='mf-stage{' is-ai' if is_ai else ''}'>"
                f"<div class='mf-stage-glyph'>{escape(glyph)}</div>"
                f"<div class='mf-stage-name'>{escape(name)}</div>"
                f"<div class='mf-stage-desc'>{escape(desc)}</div>"
                f"<div class='mf-stage-tag'>{escape(tag)}</div></div>",
                unsafe_allow_html=True)
        return

    summary, detail = st.columns([1, 1], gap='large')
    with summary:
        c1, c2 = st.columns(2)
        c1.metric('Conversion rows', f"{info.n_rows:,}")
        c2.metric('Interaction slots', info.n_slots)
    with detail:
        rows = [
            ('Activity', info.activity),
            ('Date range', f"{info.date_min:%b %d, %Y} — {info.date_max:%b %d, %Y}"),
            (f'Campaigns ({len(info.campaigns)})', ', '.join(info.campaigns)),
            (f'Sites ({len(info.sites)})', ', '.join(info.sites)),
        ]
        st.markdown(
            "<div class='mf-detail'>"
            + ''.join(f"<div class='mf-detail-row'>"
                      f"<div class='mf-detail-key'>{escape(key)}</div>"
                      f"<div class='mf-detail-val'>{escape(str(value))}</div></div>"
                      for key, value in rows)
            + "</div>",
            unsafe_allow_html=True)

    with st.expander('Export metadata and first rows'):
        if info.meta:
            st.dataframe(
                pd.DataFrame({'Field': list(info.meta), 'Value': list(info.meta.values())}),
                hide_index=True, width='stretch', height=180)
        preview = pd.read_csv(info.path, skiprows=info.header_row, nrows=8,
                              low_memory=False)
        st.dataframe(preview, width='stretch', height=200)

    ready = bool(st.session_state['client_name'].strip())
    with centered():
        if st.button('Continue to context', type='primary', width='stretch',
                     disabled=not ready,
                     help=None if ready else 'Add a client name to continue.'):
            goto(2)
            st.rerun()


# ---------------------------------------------------------------------------
# Step 2 — context
# ---------------------------------------------------------------------------

CONTEXT_PLACEHOLDER = """\
What the client sells, and to whom.
The business question this report should answer.
Anything unusual in the period: launches, pauses, budget shifts.
The words the client uses for their channels and audiences.
"""


def step_context():
    page_hero(
        'Narrative intelligence',
        'Give the analysis a sharper point of view.',
        'Context shapes the framing and the vocabulary. Every reported number stays '
        'locked to the source data.',
    )

    left, right = st.columns([3, 2], gap='large')

    with left:
        context = st.text_area(
            f"Background on {st.session_state['client_name'] or 'the client'}",
            value=st.session_state['context'], height=190,
            placeholder=CONTEXT_PLACEHOLDER)
        if context != st.session_state['context']:
            st.session_state['context'] = context
            st.session_state['run'] = None
        st.caption(f'{len(context):,} characters')

    with right:
        section_header('Where it lands')
        st.markdown(
            "- **Mapping agent** — disambiguates campaign and site names.\n"
            "- **Narrative agent** — framing, terminology and emphasis.\n"
            "- **Every figure** — computed from the export alone."
        )

    back, fwd = st.columns([1, 2], gap='small')
    if back.button('Back', width='stretch'):
        goto(1)
        st.rerun()
    if fwd.button('Generate the report', type='primary', width='stretch'):
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
        section_header('Campaigns to channels')
        campaigns = st.data_editor(
            pd.DataFrame(st.session_state['campaign_rows']),
            hide_index=True, width='stretch', height=228, key='campaign_editor',
            column_config={
                'Campaign': st.column_config.TextColumn(disabled=True),
                'Channel': st.column_config.SelectboxColumn(options=channels, required=True),
            })
    with right:
        section_header('Sites to platforms')
        sites = st.data_editor(
            pd.DataFrame(st.session_state['site_rows']),
            hide_index=True, width='stretch', height=228, key='site_editor',
            column_config={
                'Site (CM360)': st.column_config.TextColumn(disabled=True),
                'Platform': st.column_config.TextColumn(),
                'Funnel role': st.column_config.SelectboxColumn(options=channels, required=True),
            })

    return rc.Taxonomy.from_rows(campaigns.to_dict('records'), sites.to_dict('records'),
                                notes=mapping.notes)


def step_generate(client: GeminiClient | None, style: str, rewrite: bool):
    info = st.session_state['info']

    # -- Stage 1: mapping ---------------------------------------------------
    if st.session_state['mapping'] is None:
        page_hero(
            'Human-guided AI',
            'Start with a taxonomy you can trust.',
            'The mapping agent reads your campaign and site names and proposes which '
            'are Search and which are mid-funnel.',
        )

        with centered():
            if st.button('Run the mapping agent', type='primary', width='stretch'):
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

            if st.button('Back', width='stretch'):
                goto(2)
                st.rerun()
        return

    mapping = st.session_state['mapping']

    page_hero(
        'Human-guided AI',
        'Approve the taxonomy, then build.',
        'Every number downstream rests on this mapping, so it is worth a glance '
        'before the analysis runs.',
    )

    if mapping.source == 'gemini':
        st.success(f'Classified {len(mapping.taxonomy.channel_map)} campaigns and '
                   f'{len(mapping.taxonomy.platform_map)} sites.')
    else:
        st.warning('Gemini was unavailable, so this came from naming patterns. '
                   'Check it carefully.')
    if mapping.notes:
        st.caption(mapping.notes)
    for warning in mapping.warnings:
        st.warning(warning)

    tax = taxonomy_editor(mapping)

    if not tax.is_usable():
        st.error('At least one campaign must be Search or Mid-funnel, otherwise every '
                 'touch falls into "Other" and the report will be empty.')
        return

    unmapped_campaigns = set(info.campaigns) - set(tax.channel_map)
    unmapped_sites = set(info.sites) - set(tax.platform_map)
    if unmapped_campaigns or unmapped_sites:
        st.warning('Left unmapped and counted as "Other": '
                   + ', '.join(sorted(unmapped_campaigns | unmapped_sites)))

    with st.expander('Analysis window'):
        trim = st.toggle(
            'Trim the pre-activation ramp-up', value=True,
            help='Conversions before the first mid-funnel touch are Search-only by '
                 'construction and drag every mid-funnel metric toward zero.')
        override = st.date_input(
            'Window start override', value=None,
            help='Leave empty to derive it from the first mid-funnel touch in the data.')
        steady = pd.Timestamp(override) if override else None

    back, fwd = st.columns([1, 2], gap='small')
    if back.button('Re-run mapping', width='stretch'):
        st.session_state['mapping'] = None
        st.session_state['campaign_rows'] = None
        st.rerun()

    if fwd.button('Build the report', type='primary', width='stretch'):
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
                st.error(f'{exc}\n\nTurn off the narrative rewrite in Settings to build '
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
    st.markdown(f"<h2>{escape(section.heading)}</h2>", unsafe_allow_html=True)

    if section.status == 'failed' and section.note:
        st.caption(section.note)

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

    st.markdown(
        "<div class='mf-page-head'>"
        "<div class='mf-eyebrow'>Report ready</div>"
        f"<div class='mf-page-title'>{escape(spec.client_name)}</div>"
        f"<div class='mf-page-meta'>{escape(spec.subtitle)}</div>"
        "</div>",
        unsafe_allow_html=True)

    for col, kpi in zip(st.columns(len(spec.kpis)), spec.kpis):
        col.metric(kpi.label, kpi.value, help=kpi.help)

    left, mid, right = st.columns([1, 1, 1], gap='small')
    show_baseline = left.toggle('Show pre-rewrite wording', value=False)
    if mid.button('Back to mapping', width='stretch'):
        goto(3)
        st.rerun()
    with right:
        with open(run.docx_path, 'rb') as f:
            st.download_button(
                'Download .docx', f.read(), file_name=os.path.basename(run.docx_path),
                mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                type='primary', width='stretch')

    for warning in run.warnings:
        st.warning(warning)

    tab_report, tab_charts, tab_audit = st.tabs(['Report', 'Charts', 'Audit'])

    with tab_report:
        st.markdown("<div class='report-shell'>", unsafe_allow_html=True)
        st.markdown("<div class='report-cover'>"
                    f"<div class='cover-title'>{escape(spec.title)}</div>"
                    f"<div class='cover-sub'>{escape(spec.subtitle)}</div>"
                    "<div class='cover-meta'>"
                    + '<br>'.join(escape(line) for line in spec.cover_lines)
                    + "</div></div>",
                    unsafe_allow_html=True)
        for section in spec.sections:
            render_section(section, show_baseline)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab_charts:
        figures = [(s.heading, fig) for s in spec.sections for fig in s.figures()]
        for i in range(0, len(figures), 2):
            for col, (heading, fig) in zip(st.columns(2), figures[i:i + 2]):
                with col:
                    section_header(heading)
                    st.image(fig.path, caption=fig.caption, width='stretch')

    with tab_audit:
        section_header('Narrative validation')
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
            section_header(f'Evidence behind {outcome.heading}')
            st.dataframe(pd.DataFrame([
                {'Priority': str(r.get('priority', '')),
                 'Action': str(r.get('action', '')),
                 'Evidence relied on': ' · '.join(str(e) for e in r.get('evidence') or [])
                                       or '—'}
                for r in outcome.recommendations]), hide_index=True, width='stretch')

        section_header('Taxonomy used')
        st.dataframe(m.taxonomy, hide_index=True, width='stretch')

        section_header('Key figures')
        st.dataframe(pd.DataFrame(
            [{'Metric': k, 'Value': v}
             for section in spec.sections for k, v in section.facts.items()]
        ).drop_duplicates(subset=['Metric']), hide_index=True, width='stretch')


# ---------------------------------------------------------------------------

def main():
    init_state()
    st.markdown(STYLESHEET, unsafe_allow_html=True)
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
