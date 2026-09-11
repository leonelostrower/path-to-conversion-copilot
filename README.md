# Path to Conversion Copilot

A Streamlit app that turns a raw Campaign Manager 360 path-to-conversion export
into a written client report. Upload the CSV, name the client, add some written
context, and three Gemini-backed agents produce the report on screen and as a
`.docx`.

## Why it is built this way

The interesting problem is not "ask an LLM to describe a spreadsheet". It is
producing a client-facing document where the prose reads like an analyst wrote it
and every number is still correct. So the work is split by what each component is
actually good at:

| Stage | Who does it | What it decides |
| --- | --- | --- |
| 1. Mapping | Gemini | Which campaigns are Search vs mid-funnel, and the clean platform name for each site |
| 2. Analysis | Plain Python | Every metric and all eight charts |
| 3. Narrative | Gemini | The wording, framing and emphasis |

Gemini handles naming and language. It never does arithmetic. Between stages 1
and 2 the user approves the taxonomy, because a wrong channel assignment would
distort every number downstream and is far cheaper to fix before the analysis
runs than to explain afterwards.

## The guarantee on the numbers

Prompting a model to "not make up numbers" is not a guarantee. This is enforced
after the fact, in `agents/narrative_agent.py`:

- Each section carries `facts`, its verified numbers pre-formatted as strings.
- After a rewrite, every numeric token in the new text must already appear in
  that section's facts, its original draft, or its tables.
- A rewrite that invents a figure, or re-rounds one (`14.2%` becoming `14%`), is
  sent back once with the offending tokens named.
- A rewrite that drops more than 40% of the figures it was given is also
  rejected, since losing the numbers turns analysis into assertion.
- If the second attempt still fails, the deterministic baseline wording is kept
  for that section and the report says so.

The worst case is therefore the original wording, never a wrong number. The
Audit tab shows the per-section result, and `test_pipeline.py` re-opens the
finished `.docx` and re-checks every paragraph in it.

## Setup

Requires Python 3.12 (Streamlit 1.62 has dropped 3.9, which is what macOS ships).

```bash
uv venv .venv --python 3.12
uv pip install -r requirements.txt
```

Or with plain pip:

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Put your key in `.env`:

```
GEMINI_API_KEY=your-key-here
```

Optional, for the Sankey diagram. Plotly renders it through Kaleido, which needs
a Chrome binary; without it the app falls back to a matplotlib flow matrix
showing the same first-touch-to-last-touch counts.

```bash
./.venv/bin/plotly_get_chrome -y
```

## Run

```bash
./.venv/bin/streamlit run app.py
```

Then: upload the export, enter the client name, paste context, run the agents,
read the report.

### Context

The context box is free text and is given to the narrative agent as background:
what the client does, the business question the report should answer, platform
launches or pauses in the period, the vocabulary the client uses. It shapes
framing and terminology. It cannot change a number, because the numbers are
computed before the narrative is written.

## Model selection

Verified against the Gemini API, the flash tier is what this key can use:
`gemini-3.5-flash`, `gemini-2.5-flash`, `gemini-3-flash-preview`,
`gemini-3.1-flash-lite` and `gemini-3.6-flash`. The Pro models answer 429, and
`gemini-3.7-flash` is often overloaded.

Because 503s and read timeouts are common on this tier, every request walks the
chain in `agents/gemini_client.py` and only fails once all of them have been
tried. Runs routinely start on one model and finish on another; that is normal.

## Layout

```
app.py                      Streamlit UI, the four-step flow
report_core.py              Data pipeline: load, reshape, metrics, charts
report_spec.py              The report as data: sections, blocks, facts
docx_builder.py             ReportSpec -> .docx in the .monks styling
agents/
  gemini_client.py          google-genai wrapper with the model fallback chain
  mapping_agent.py          Agent 1
  analysis_agent.py         Agent 2
  narrative_agent.py        Agent 3, including the numeric validation
  orchestrator.py           Runs the three in order
generate_report.py          The original single-client script, kept for reference
test_pipeline.py            End-to-end run plus the .docx figure audit
test_ui.py                  Renders every screen headlessly, no API key needed
output/                     Generated charts, reports and uploads
```

`generate_report.py` is unchanged and unused by the app. It was the starting
point: a script with the Rates.ca taxonomy hardcoded, `sys.argv` read at import
time, and the narrative embedded in f-strings interleaved with `python-docx`
calls. `report_core.py` and `report_spec.py` are that logic reorganised so the
pipeline can be driven with a taxonomy discovered at runtime and prose that can
be rewritten without editing Python.

## Tests

```bash
./.venv/bin/python test_ui.py        # every screen, offline
./.venv/bin/python test_pipeline.py  # all three agents + .docx audit, needs the key
```

`test_pipeline.py` prints the inferred taxonomy, the per-section narrative
outcome, and then re-reads the generated `.docx` to confirm every figure in it
traces back to the deterministic pipeline. It exits non-zero if any does not.

## What the report contains

Ten sections, eight figures: mid-funnel timeseries, path-type mix, a DV360-style
top-converting-paths chevron chart, a platform transition heatmap, path length
and time-to-convert by path type, touch-position distribution, a first-to-last
touch Sankey, and the assist-lag histogram.

The analysis window is derived from the data rather than hardcoded. Conversions
before the first mid-funnel touch are Search-only by construction, not by
consumer behaviour, so including them drags every mid-funnel metric toward zero;
the app trims them and says so in the methodology section. You can override the
window under Advanced on the generate step.
