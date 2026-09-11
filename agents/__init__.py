"""Gemini agents driving the report pipeline.

mapping_agent   (Agent 1) infers the campaign/site taxonomy for a new client.
analysis_agent  (Agent 2) computes metrics and charts deterministically.
narrative_agent (Agent 3) rewrites the report prose, grounded in those numbers.
orchestrator              runs the three in order and reports progress.
"""
