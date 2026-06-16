"""Deterministic worklist samplers for human annotation.

Each sampler reads a frozen corpus, computes per-dialogue strata, and emits a
reproducible worklist JSON assigning dialogues to labeler slots. No DB, no
network, no wall-clock — re-running with the same seed yields an identical file.
"""
