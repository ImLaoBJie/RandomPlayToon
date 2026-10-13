"""Rendered face regression for eye reveal, nose and shadow controls after upgrade."""
import sys
import json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'addons'))
from random_play_toon import style_panel as ui

path = Path(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else ROOT/'experiments/SceneResponseRelease/Templates/Vivian_Reference2_CrispCel_SceneResponse.blend'
OUT = ROOT/'experiments/SceneResponseRelease/Effects'/path.stem
OUT.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(path.resolve()), use_scripts=False)
s = bpy.context.scene
ui.register()
registry = ui.registry(s)
glob = registry['global']


def setkey(key, value):
    label = next(x['label'] for x in glob['entries'] if x['key'] == key)
    ui.node(glob).inputs[label].default_value = value


def render(name):
    ui.refresh(s)
    path = OUT/(name+'.png');s.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:]).reshape(image.size[1], image.size[0], 4)[..., :3]
    bpy.data.images.remove(image)
    print('SCENE_EFFECT_RENDER', name, flush=True)
    return pixels


audit = json.loads(s['rpt_nose_audit'])
obj = bpy.data.objects[registry.get('mesh_object', 'Vivian_Mapping')]
center = obj.matrix_world @ (Vector(audit['tip'])+Vector((0, 0, audit['face_width']*.15)))
s.camera.data.type = 'ORTHO';s.camera.data.ortho_scale = audit['face_width']*1.8
s.camera.location = center+Vector((0, -2, 0))
s.camera.rotation_euler = (center-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.render.resolution_x = 384;s.render.resolution_y = 384;s.render.resolution_percentage = 100
s.eevee.taa_render_samples = 64
# Put irradiance inside the toon transition range: a strongly lit face can be
# fully in the bright band at BOTH tested thresholds, which is not a dead knob.
for light in s.objects:
    if light.type == 'LIGHT':light.hide_render = True
world = bpy.data.worlds.new('Effects QA black world');world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
s.world = world
light = bpy.data.objects.new('Effects QA sun', bpy.data.lights.new('Effects QA sun', 'SUN'))
s.collection.objects.link(light);light.data.energy = .4
light.rotation_euler = Vector((0, 1, -1)).to_track_quat('-Z', 'Y').to_euler()
ui.lighting_set(s, 0)
setkey('Nose Enabled', False);setkey('Eye Reveal Enabled', True);setkey('Eye Reveal Strength', 1.)
baseline = render('baseline')
setkey('Eye Reveal Enabled', False)
no_eyes = render('eye_reveal_off')
assert np.count_nonzero(np.max(np.abs(baseline-no_eyes), axis=2) > 2/255) > 20
setkey('Eye Reveal Enabled', True);setkey('Nose Enabled', True)
setkey('Nose Opacity', .9);setkey('Nose Direction', 35.)
nose = render('nose_on')
assert np.count_nonzero(np.max(np.abs(baseline-nose), axis=2) > 2/255) > 20
setkey('Nose Enabled', False)
thresholds = [ui.node(e).inputs[x['label']] for e in registry['materials'] for x in e['entries'] if x['key'] == 'Face Threshold']
assert thresholds
old_thresholds = [socket.default_value for socket in thresholds]
for socket in thresholds:socket.default_value = 1.
shadow = render('shadow_threshold')
assert np.count_nonzero(np.max(np.abs(baseline-shadow), axis=2) > 2/255) > 20
for socket, value in zip(thresholds, old_thresholds):socket.default_value = value
softness = [ui.node(e).inputs[x['label']] for e in registry['materials'] for x in e['entries'] if x['key'] == 'Face Softness']
old_softness = [socket.default_value for socket in softness]
for socket in softness:socket.default_value = .6
soft_shadow = render('shadow_softness')
assert np.count_nonzero(np.max(np.abs(baseline-soft_shadow), axis=2) > 2/255) > 20
for socket, value in zip(softness, old_softness):socket.default_value = value
# Keep exact non-style values across all existing mode/style buttons.
before = ui.capture(s)
for preset in ['BASELINE', 'DISPLAY', 'SOFT', 'CONTRAST', 'NIGHT']:
    planned = ui.make_preset(s, preset)
    assert bpy.ops.rpt.style_preset(preset=preset) == {'FINISHED'}
    actual = ui.capture(s)
    for material, values in before.items():
        for label, value in values.items():
            if any(word in label for word in ['透眼', '鼻影', '亮块', '眼白', '瞳孔']):
                assert actual[material][label] == value, label
result = {'eye_reveal_changed_pixels': int(np.count_nonzero(np.max(np.abs(baseline-no_eyes), axis=2) > 2/255)),
          'nose_changed_pixels': int(np.count_nonzero(np.max(np.abs(baseline-nose), axis=2) > 2/255)),
          'shadow_threshold_changed_pixels': int(np.count_nonzero(np.max(np.abs(baseline-shadow), axis=2) > 2/255)),
          'shadow_softness_changed_pixels': int(np.count_nonzero(np.max(np.abs(baseline-soft_shadow), axis=2) > 2/255)),
          'presets_preserved_effect_controls': True}
(OUT/'validation.json').write_text(json.dumps(result, indent=2), encoding='utf8')
print('SCENE_EFFECTS_PASS', result, flush=True)
