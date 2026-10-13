"""Blender regression for editing nasal controls without explicit refresh.

Run in a factory-startup background Blender with --python-exit-code 1, passing
one or more nose-enabled template/ABC .blend paths after --. No file is saved.
This deliberately exercises the same RNA setters used by the panel, then reads
actual shader driver results. Calling ui.refresh here would hide the regression.
"""
import sys
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'addons'))
from random_play_toon import style_panel as toon
from random_play_copy import style_panel as copy

VALUES = {
    'Nose Enabled': True, 'Nose Opacity': .82,
    'Nose Tint': (.15, .45, .75, 1.), 'Nose Width': 2.1,
    'Nose Length': 1.6, 'Nose Offset X': .004, 'Nose Offset Z': -.006,
    'Nose Softness': .23, 'Nose Direction': -32.,
    'Nose View Follow': .6, 'Nose Transition': 11., 'Nose Profile Fade': 62.,
}


def consumers(scene, key, expected):
    count = 0
    for entry in toon.registry(scene)['materials']:
        tree = bpy.data.materials[entry['material']].node_tree
        for node in tree.nodes:
            if node.name not in ['全局 · ' + key, 'Control color · ' + key]:
                continue
            actual = node.outputs[0].default_value
            if isinstance(expected, tuple):
                assert max(abs(a-b) for a, b in zip(actual, expected)) < 1e-5
            else:
                assert abs(actual-expected) < 1e-5, (key, actual, expected)
            count += 1
    assert count > 0, ('Missing shader consumers', key)


paths = sys.argv[sys.argv.index('--')+1:]
assert paths, 'Provide at least one nose-enabled .blend'
for path in paths:
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), use_scripts=False)
    scene = bpy.context.scene
    for panel in [toon, copy]:
        panel.register()
        try:
            frame = scene.frame_current
            for key, value in VALUES.items():
                setattr(scene, panel.nose_property_name(key), value)
                consumers(scene, key, value)
                assert scene.frame_current == frame
            for key, value in [('Nose Enabled', False), ('Nose Width', .7)]:
                setattr(scene, panel.nose_property_name(key), value)
                consumers(scene, key, value)
            before = toon.capture(scene)
            op = bpy.ops.rpt.style_preset if panel is toon else bpy.ops.rpcstyle.style_preset
            for preset in ['BASELINE', 'DISPLAY', 'SOFT', 'CONTRAST', 'NIGHT']:
                assert op(preset=preset) == {'FINISHED'}
                after = toon.capture(scene)
                for material, values in before.items():
                    for label, value in values.items():
                        if '鼻影' in label:
                            assert after[material][label] == value
        finally:
            panel.unregister()
    print('NOSE_LIVE_CONTROLS_PASS', path, flush=True)
