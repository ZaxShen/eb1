"""Dataset-adapter layer for the universal UFL pipeline.

Adapters normalize public bot-human chat corpora into the pipeline's existing
internal message shape so the core segmentation architecture runs unchanged.
See ``base`` for the normalized-message contract.
"""

from __future__ import annotations

from pipeline.adapters.base import ConversationLoader, normalize_role
from pipeline.adapters.lmsys import LMSYSLoader
from pipeline.adapters.superdialseg import SuperDialsegLoader
from pipeline.adapters.wildchat import WildChatLoader

LOADERS: dict[str, type] = {
    WildChatLoader.name: WildChatLoader,
    LMSYSLoader.name: LMSYSLoader,
    SuperDialsegLoader.name: SuperDialsegLoader,
}


def get_loader(name: str) -> ConversationLoader:
    """Return an instantiated adapter for ``name`` (e.g. ``"wildchat"``)."""
    try:
        return LOADERS[name]()
    except KeyError:
        raise ValueError(
            f"Unknown dataset adapter: {name!r}. Known: {sorted(LOADERS)}"
        ) from None


__all__ = [
    "ConversationLoader",
    "LMSYSLoader",
    "LOADERS",
    "SuperDialsegLoader",
    "WildChatLoader",
    "get_loader",
    "normalize_role",
]
