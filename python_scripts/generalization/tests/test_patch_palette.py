"""Blender background test: source UV/area selection and default/preset precedence."""
import json
import sys
from pathlib import Path
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'addons'))
from random_play_toon.materials.patch_palette import choose, infer, linear
from random_play_toon import style_panel as ui
from random_play_toon.core import build

out = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
out.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.filepaths.file_preview_type = 'NONE'
bpy.context.preferences.filepaths.save_version = 0

# Small accents must not tint a mostly neutral character. Transparent samples
# and warm skin in a mixed body atlas must not beat a character's purple cloth.
assert choose([[.8, .8, .8], [1, .1, .1]], [100, 1], [False, False])['srgb_hex'] == '#FFFFFF'
result = choose([[1, .8, .7], [.5, .3, .8], [0, 1, 0]], [100, 10, 0], [False] * 3)
assert result['linear_rgba'][2] == 1 and result['linear_rgba'][1] < result['linear_rgba'][0]
assert choose([], [], [])['srgb_hex'] == '#FFFFFF'
assert choose([[.9, .7, .45]], [1], [True])['srgb_hex'] != '#FFFFFF'

# Only a red corner of an otherwise blue texture is actually mapped to the mesh.
# The tiny green part has its own material. Neither unused pixels nor material
# count may override the red surface's area.
bpy.ops.wm.read_factory_settings(use_empty=True)
image = bpy.data.images.new('UV test', width=16, height=16)
image.colorspace_settings.name = 'Non-Color'
pixels = np.tile(np.array([.05, .05, 1., 1.], dtype=np.float32), (16, 16, 1))
pixels[:4, :4] = [1., .05, .05, 1.]
image.pixels.foreach_set(pixels.ravel())
image.filepath_raw = str(out / 'uv_test.png'); image.file_format = 'PNG'; image.save()
bpy.data.images.remove(image)
mesh = bpy.data.meshes.new('source')
mesh.from_pydata([(0, 0, 0), (2, 0, 0), (0, 2, 0), (3, 0, 0), (3.1, 0, 0), (3, .1, 0)], [], [(0, 1, 2), (3, 4, 5)])
obj = bpy.data.objects.new('source', mesh); bpy.context.scene.collection.objects.link(obj)
for name in ['large red', 'small green']:mesh.materials.append(bpy.data.materials.new(name))
mesh.polygons[1].material_index = 1
uv = mesh.uv_layers.new(name='UVMap')
for loop in uv.data:loop.uv = (.1, .1)
profile = {'materials': [{'index': 0, 'name': 'red', 'role': 'cloth', 'diffuse': [1]*4},
                         {'index': 1, 'name': 'green', 'role': 'cloth', 'diffuse': [0, 1, 0, 1]}]}
result = infer(obj, profile, {'textures': {'0': str(out / 'uv_test.png')}})
assert result['linear_rgba'][0] == 1 and result['linear_rgba'][2] < .5, result
assert mesh.polygons[1].material_index == 1 and len(mesh.vertices) == 6

# Exercise the real unknown-character builder and reopening with automatic color,
# then a user preset whose patch color must win over the inferred default.
checks = []
for character, custom in [('Anby', None), ('LucySummer', [.12, .25, .8, 1.])]:
    info = json.loads((ROOT / 'assets_preprocessed/characters' / character / 'character.json').read_text('utf8'))
    model = next(m for m in info['models'] if m['model_id'] == info['default_model_id'])
    pmx = ROOT / 'assets_preprocessed' / model['pmx']
    preset = None
    if custom:
        # Use a complete user preset from the existing fixture, as the UI does.
        baseline = ROOT / 'experiments/SummerValidation_20261020/90_中间文件/基线工程/LucySummer_base.blend'
        if not baseline.is_file():baseline = ROOT / 'experiments/SummerValidation_20261020/LucySummer_base.blend'
        bpy.ops.wm.open_mainfile(filepath=str(baseline), use_scripts=False)
        preset = ui.capture(bpy.context.scene)
        preset[ui.registry(bpy.context.scene)['global']['material']]['亮块颜色'] = custom
    bpy.ops.wm.read_factory_settings(use_empty=True)
    destination = out / (character + '.blend')
    report = build(str(pmx), str(pmx.parent), '', str(destination), personal_preset=preset)
    assert all(report['source_preserved'].values())
    bpy.ops.wm.open_mainfile(filepath=str(destination), use_scripts=False)
    scene = bpy.context.scene
    selected = json.loads(scene['rpt_patch_palette'])
    color = ui.node(ui.registry(scene)['global']).inputs['亮块颜色'].default_value[:]
    assert np.allclose(color, custom or selected['linear_rgba']), (color, selected)
    assert selected['srgb_hex'] != '#FFFFFF'
    reset = ui.make_preset(scene, 'RESET')[ui.registry(scene)['global']['material']]['亮块颜色']
    assert np.allclose(reset, selected['linear_rgba'])
    # A regular refresh/open does not overwrite the personal value.
    ui.refresh(scene)
    assert np.allclose(ui.node(ui.registry(scene)['global']).inputs['亮块颜色'].default_value, color)
    checks.append({'character': character, 'source_preserved': True, 'saved_reopened': True,
                   'personal_preset': bool(custom), 'palette': selected})
(out / 'validation.json').write_text(json.dumps({'passed': True, 'synthetic_uv_area_alpha_skin': True,
                                               'builds': checks}, ensure_ascii=False, indent=2), encoding='utf8')
print('PATCH_PALETTE_PASS', flush=True)
