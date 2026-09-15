"""Optional AI helpers shared by the annotation tools.

Nothing in here is imported at start-up: the tools ask for it the first time
somebody turns the AI tool on, so a machine without onnxruntime or numpy
starts and runs exactly as before.
"""

from __future__ import annotations

from .masks import mask_to_box, mask_to_polygon                     # noqa: F401

__all__ = ["mask_to_box", "mask_to_polygon"]
