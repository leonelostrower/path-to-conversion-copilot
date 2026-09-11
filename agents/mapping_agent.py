"""
Agent 1 — Mapping.

The original script hardcoded the Rates.ca taxonomy:

    CHANNEL_MAP = {'DART Search': 'Search', 'Auto Mid-funnel 2026': 'Mid-funnel'}
    PLATFORM_MAP = {'DART Search : Google': 'Google Search', ...}

which meant a new client's export silently collapsed into 'Other'. This agent
derives that mapping instead: it hands Gemini the distinct campaign and site
values found in the upload and asks which are Search, which are mid-funnel, and
what the human-readable platform name is for each site.

Gemini is doing naming judgement here, not arithmetic. The result is shown to the
user for approval before any number is computed from it, and a naming-pattern
heuristic covers the case where the model is unavailable or returns something
unusable.
"""

from __future__ import annotations

from dataclasses import dataclass

from report_core import (
    CHANNEL_MID_FUNNEL, CHANNEL_OTHER, CHANNEL_SEARCH, ExportInfo,
    FALLBACK_COLORS, KNOWN_PLATFORM_COLORS, Taxonomy, heuristic_taxonomy,
)

from .gemini_client import GeminiClient, GeminiError

SYSTEM_INSTRUCTION = """\
You are a digital media analyst who classifies Campaign Manager 360 (CM360) \
taxonomy values.

You will receive the distinct campaign names and site names found in one \
advertiser's path-to-conversion export. Classify each one.

Channels:
- "Search": paid search / SEM campaigns and search-engine sites (Google, Bing, \
MSN, Yahoo, SA360, DART Search).
- "Mid-funnel": awareness, consideration, prospecting, social, display, video and \
programmatic campaigns that build interest earlier in the funnel (Facebook, \
Instagram, Reddit, TikTok, StackAdapt, Pinterest, YouTube, LinkedIn, Snapchat, \
The Trade Desk, DV360).
- "Other": anything that is genuinely neither, such as internal test or \
placeholder values.

For every site, also give a short human-readable platform name. Site values \
usually embed the advertiser and the platform, for example \
"Rates.ca - Reddit" is the Reddit platform and "DART Search : Google" is \
Google Search. Strip the advertiser prefix and keep a clean platform name. \
Use "Google Search" and "MSN Search" (not bare "Google"/"MSN") for search \
engines so they read correctly in a report.

Rules:
- Classify every value you are given, exactly once, reusing the input string \
verbatim so it can be matched back.
- Give the same platform name to sites that are the same platform.
- funnel_role for a site must agree with the channel of the campaigns it runs on.
- Prefer a recognisable brand name over an internal code.
"""

TAXONOMY_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'campaigns': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'campaign': {'type': 'STRING',
                                 'description': 'The input campaign name, verbatim.'},
                    'channel': {'type': 'STRING',
                                'enum': [CHANNEL_SEARCH, CHANNEL_MID_FUNNEL, CHANNEL_OTHER]},
                },
                'required': ['campaign', 'channel'],
            },
        },
        'sites': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'site': {'type': 'STRING',
                             'description': 'The input site value, verbatim.'},
                    'platform': {'type': 'STRING',
                                 'description': 'Clean human-readable platform name.'},
                    'funnel_role': {'type': 'STRING',
                                    'enum': [CHANNEL_SEARCH, CHANNEL_MID_FUNNEL, CHANNEL_OTHER]},
                },
                'required': ['site', 'platform', 'funnel_role'],
            },
        },
        'notes': {
            'type': 'STRING',
            'description': 'One or two sentences on anything ambiguous.',
        },
    },
    'required': ['campaigns', 'sites'],
}


@dataclass
class MappingResult:
    taxonomy: Taxonomy
    source: str          # 'gemini' | 'heuristic'
    notes: str = ''
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def build_prompt(info: ExportInfo, client_name: str, context: str = '') -> str:
    lines = [
        f"Advertiser / client: {client_name or 'unknown'}",
        f"Floodlight activity: {info.activity}",
        '',
        'Distinct campaign names in the export:',
    ]
    lines += [f"  - {c}" for c in info.campaigns] or ['  (none)']
    lines += ['', 'Distinct site (CM360) values in the export:']
    lines += [f"  - {s}" for s in info.sites] or ['  (none)']

    if context.strip():
        lines += ['', 'Additional context supplied by the analyst (use it to resolve '
                      'ambiguous names, but do not invent values that are not listed above):',
                  context.strip()[:4000]]

    lines += ['', 'Classify every campaign and every site listed above.']
    return '\n'.join(lines)


def _taxonomy_from_payload(payload: dict, info: ExportInfo) -> tuple[Taxonomy, list[str]]:
    warnings: list[str] = []

    valid_campaigns = set(info.campaigns)
    valid_sites = set(info.sites)

    channel_map: dict[str, str] = {}
    for row in payload.get('campaigns', []):
        campaign = str(row.get('campaign', '')).strip()
        channel = str(row.get('channel', '')).strip()
        if campaign not in valid_campaigns:
            warnings.append(f"Ignored campaign not present in the export: {campaign!r}")
            continue
        if channel not in (CHANNEL_SEARCH, CHANNEL_MID_FUNNEL, CHANNEL_OTHER):
            warnings.append(f"Unexpected channel {channel!r} for campaign {campaign!r}")
            continue
        channel_map[campaign] = channel

    platform_map: dict[str, str] = {}
    search: list[str] = []
    mid: list[str] = []
    for row in payload.get('sites', []):
        site = str(row.get('site', '')).strip()
        platform = str(row.get('platform', '')).strip()
        role = str(row.get('funnel_role', '')).strip()
        if site not in valid_sites:
            warnings.append(f"Ignored site not present in the export: {site!r}")
            continue
        if not platform:
            warnings.append(f"No platform name returned for site {site!r}")
            continue
        platform_map[site] = platform
        if role == CHANNEL_SEARCH and platform not in search:
            search.append(platform)
        elif role == CHANNEL_MID_FUNNEL and platform not in mid:
            mid.append(platform)

    for campaign in valid_campaigns - set(channel_map):
        warnings.append(f"Campaign left unclassified by the model: {campaign!r}")
    for site in valid_sites - set(platform_map):
        warnings.append(f"Site left unclassified by the model: {site!r}")

    colors: dict[str, str] = {}
    for i, platform in enumerate(dict.fromkeys(search + mid)):
        colors[platform] = KNOWN_PLATFORM_COLORS.get(
            platform, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])

    tax = Taxonomy(channel_map=channel_map, platform_map=platform_map,
                   mid_funnel_platforms=mid, search_platforms=search,
                   platform_colors=colors,
                   notes=str(payload.get('notes', '') or ''))
    return tax, warnings


def run(info: ExportInfo, client_name: str, client: GeminiClient | None,
        context: str = '') -> MappingResult:
    """Infer the taxonomy for this export. Never raises: falls back to heuristics."""
    if client is None:
        tax = heuristic_taxonomy(info.campaigns, info.sites)
        return MappingResult(taxonomy=tax, source='heuristic', notes=tax.notes,
                             warnings=['Gemini was not configured, so the taxonomy '
                                       'came from naming patterns.'])

    try:
        payload = client.generate_json(
            build_prompt(info, client_name, context),
            TAXONOMY_SCHEMA,
            label='mapping',
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.0,
        )
    except GeminiError as exc:
        tax = heuristic_taxonomy(info.campaigns, info.sites)
        return MappingResult(taxonomy=tax, source='heuristic', notes=tax.notes,
                             warnings=[f'Mapping agent fell back to naming patterns: {exc}'])

    tax, warnings = _taxonomy_from_payload(payload, info)

    # A taxonomy where nothing resolved to a real channel would send every touch
    # into 'Other' and produce an empty report, so prefer the heuristic.
    if not tax.is_usable():
        fallback = heuristic_taxonomy(info.campaigns, info.sites)
        warnings.append('The model classified no campaign as Search or Mid-funnel, '
                        'so naming patterns were used instead.')
        return MappingResult(taxonomy=fallback, source='heuristic',
                             notes=fallback.notes, warnings=warnings)

    return MappingResult(taxonomy=tax, source='gemini', notes=tax.notes,
                         warnings=warnings)
