# Copyright 2012 MMD Tools authors
# This file is part of MMD Tools, GPL-3.0-or-later; see LICENSE.
# Modified by RandomPlayToon, 2026-10-01: isolated PMX import runtime only.
"""Import-only subset of MMD Tools. See UPSTREAM.json for provenance."""
import importlib
from pathlib import Path

PACKAGE_NAME = __package__
PACKAGE_PATH = str(Path(__file__).parent)
MMD_TOOLS_VERSION = '4.5.14'
_registered = False


def register_import_properties():
    """Register only data needed by PMXImporter, inside a clean worker."""
    global _registered
    if _registered:
        return
    import bpy
    if not bpy.app.background:
        raise RuntimeError('The bundled PMX runtime is worker-only.')
    if hasattr(bpy.types.Object, 'mmd_root'):
        raise RuntimeError('PMX worker must start with --factory-startup.')
    from . import auto_load
    modules = [importlib.import_module('.properties.' + name, __package__)
               for name in ('camera', 'material', 'morph', 'pose_bone',
                            'rigid_body', 'root', 'translations')]
    classes = auto_load.get_ordered_classes_to_register(modules)
    registered = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            registered.append(cls)
    except Exception:
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        raise
    _registered = True
