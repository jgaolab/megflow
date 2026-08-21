# -*- coding: utf-8 -*-
"""Standalone Torch MEGFlow inference package."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import DeepRejectPrediction, DeepRejectPredictor

__all__ = ["DeepRejectPrediction", "DeepRejectPredictor"]


def __getattr__(name):
    """Load Torch-backed public classes only when they are requested."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .runtime import DeepRejectPrediction, DeepRejectPredictor

    exports = {
        "DeepRejectPrediction": DeepRejectPrediction,
        "DeepRejectPredictor": DeepRejectPredictor,
    }
    globals().update(exports)
    return exports[name]
