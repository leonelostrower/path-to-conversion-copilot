"""Exercise every Streamlit screen without a browser.

Runs offline: the narrative agent is skipped, so the report screen is rendered
from the deterministic baseline and no API key is needed.
"""

import os

os.environ.setdefault('MPLCONFIGDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '.mplcache'))

from streamlit.testing.v1 import AppTest

import report_core as rc
from agents import orchestrator

CSV = '2026-08-17_path_to_conversion_2751751_RDC (1).csv'


def check(at: AppTest, label: str):
    if at.exception:
        for exc in at.exception:
            print(f'  FAIL {label}: {exc.value}')
        raise SystemExit(1)
    print(f'  ok   {label}')


def main():
    info = rc.inspect_export(CSV)

    print('== Step 1: upload screen ==')
    at = AppTest.from_file('app.py', default_timeout=120).run()
    check(at, 'renders with no upload')
    print(f'  headings: {[h.value for h in at.title] or "(styled markdown)"}')
    print(f'  text inputs: {len(at.text_input)}, buttons: {len(at.button)}')

    print('\n== Step 1: with an export loaded ==')
    at = AppTest.from_file('app.py', default_timeout=120)
    at.session_state['info'] = info
    at.session_state['csv_path'] = info.path
    at.session_state['csv_name'] = os.path.basename(info.path)
    at.session_state['client_name'] = 'Rates.ca'
    at.run()
    check(at, 'shows detected metadata')
    print(f'  metrics: {[(m.label, m.value) for m in at.metric]}')

    print('\n== Step 2: context screen ==')
    at.session_state['step'] = 2
    at.run()
    check(at, 'renders context textarea')
    print(f'  text areas: {len(at.text_area)}')

    print('\n== Step 3: mapping screen, before running the mapping agent ==')
    at.session_state['step'] = 3
    at.run()
    check(at, 'offers the mapping button')

    print('\n== Step 3: mapping screen, with a heuristic taxonomy ==')
    from agents.mapping_agent import MappingResult
    tax = rc.heuristic_taxonomy(info.campaigns, info.sites)
    at.session_state['mapping'] = MappingResult(taxonomy=tax, source='heuristic',
                                                notes=tax.notes)
    at.session_state['campaign_rows'] = None
    at.run()
    check(at, 'renders the editable taxonomy')
    print(f'  data editors: {len(at.session_state["campaign_rows"] or [])} campaign rows, '
          f'{len(at.session_state["site_rows"] or [])} site rows')

    print('\n== Step 4: report screen (no Gemini, baseline wording) ==')
    run = orchestrator.run_report(
        info, tax, client_name='Rates.ca',
        subtitle='2026 Q3: Quarterly Business Review', client=None,
        context='', rewrite_narrative=False)
    at.session_state['run'] = run
    at.session_state['step'] = 4
    at.run()
    check(at, 'renders the full report')
    print(f'  KPI metrics: {[(m.label, m.value) for m in at.metric]}')
    print(f'  tabs: {[t.label for t in at.tabs]}')
    print(f'  dataframes: {len(at.dataframe)}')
    print(f'  pdf: {os.path.basename(run.pdf_path)} '
          f'({os.path.getsize(run.pdf_path):,} bytes)')

    print('\nAll screens rendered without exceptions.')


if __name__ == '__main__':
    main()
