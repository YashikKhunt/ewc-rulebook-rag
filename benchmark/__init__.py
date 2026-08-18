"""Measurement layer for the EWC Rulebook RAG.

Read-only with respect to the pipeline: this package imports `graph` and drives
its nodes. It never monkeypatches, never sets a seed, and never mutates
`FUSED_K` / `ACCOUNTABLE_RANK`. `eval/run.py` remains the only build gate;
nothing here changes an exit code on the strength of a metric value.
"""
