"""Real EEVEE regression: scene hue/energy/direction and studio preservation.

Run with Blender --background --factory-startup --python-exit-code 1 --python
this_file -- input.blend [...]. Inputs are read-only; outputs go to experiments.
"""
import sys
import json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'addons'))
import random_play_toon as addon
from random_play_toon import style_panel as ui
from random_play_toon.materials.scene_response import apply

OUT = ROOT / 'experiments/SceneResponseRelease'
OUT.mkdir(parents=True, exist_ok=True)
addon.register()


def links(tree):
    return sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links)


def render(scene, folder, name):
    ui.refresh(scene)
    path = folder / (name + '.png')
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape(image.size[1], image.size[0], 4)[..., :3]
    bpy.data.images.remove(image)
    print('SCENE_RESPONSE_RENDER', name, flush=True)
    return pixels


for path in sys.argv[sys.argv.index('--')+1:]:
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), use_scripts=False)
    s = bpy.context.scene
    folder = OUT / Path(path).stem
    folder.mkdir(exist_ok=True)
    r = ui.registry(s)
    before = ui.capture(s)
    defaults = s['zzz_stage6_defaults']
    compositor = links(s.compositing_node_group)
    frame = s.frame_current
    # A reproducible front/upper scene light in a black world.
    for obj in s.objects:
        if obj.type == 'LIGHT':
            obj.hide_render = True
    world = bpy.data.worlds.new('QA black world');world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
    s.world = world
    mesh = bpy.data.objects[r.get('mesh_object', 'Vivian_Mapping')]
    points = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    height = hi.z - lo.z
    center = (lo + hi) * .5
    center.z = hi.z - height * .28
    s.camera.data.type = 'ORTHO';s.camera.data.ortho_scale = height * .63
    s.camera.location = center + Vector((0, -height * 2, 0))
    s.camera.rotation_euler = (center-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
    lamp = bpy.data.objects.new('QA area', bpy.data.lights.new('QA area', 'AREA'))
    s.collection.objects.link(lamp)
    lamp.data.energy = 500;lamp.data.shape = 'DISK';lamp.data.size = height * .6
    lamp.location = center + Vector((height * .4, -height, height * .6))
    lamp.rotation_euler = (center-lamp.location).to_track_quat('-Z', 'Y').to_euler()
    s.render.resolution_x = 256;s.render.resolution_y = 320;s.render.resolution_percentage = 100
    s.eevee.taa_render_samples = 32
    ui.lighting_set(s, 1)
    studio_before = render(s, folder, 'studio_before')
    capture = ui.capture(s)
    assert bpy.ops.rpt.upgrade_scene_response() == {'FINISHED'}
    assert ui.capture(s) == capture and s['zzz_stage6_defaults'] == defaults
    assert links(s.compositing_node_group) == compositor
    counts = {g.name: len(g.nodes) for g in bpy.data.node_groups}
    apply(s)
    assert counts == {g.name: len(g.nodes) for g in bpy.data.node_groups}
    assert not bpy.ops.rpt.upgrade_scene_response.poll()
    studio_after = render(s, folder, 'studio_after')
    difference = np.abs(studio_after - studio_before)
    # Recompiled EEVEE shaders can alter a few sampled silhouette/eye pixels.
    # Bound both peak error (5/255) and affected area; do not allow a broad tint.
    assert difference.max() < .02 and difference.mean() < .00002, (difference.max(), difference.mean())
    assert np.mean(difference.max(axis=2) > 1.01/255) < .0002
    ui.lighting_set(s, 0)
    for _ in range(3):
        ui.lighting_set(s, 1);ui.lighting_set(s, 0)
    after = ui.capture(s)
    for material, values in capture.items():
        for label, value in values.items():
            if label != '独立展示光照':
                assert after[material][label] == value, label
    white = render(s, folder, 'scene_white')
    lamp.data.color = (1, .025, .025)
    red = render(s, folder, 'scene_red')
    lamp.data.color = (.025, .025, 1)
    blue = render(s, folder, 'scene_blue')
    assert red[..., 0].mean() > blue[..., 0].mean() * 1.15
    assert blue[..., 2].mean() > red[..., 2].mean() * 1.15
    lamp.data.color = (1, 1, 1)
    lamp.rotation_euler.rotate_axis('X', 3.14159265)
    away = render(s, folder, 'scene_away')
    assert white.mean() > away.mean() * 1.10, (white.mean(), away.mean())
    lamp.rotation_euler = (center-lamp.location).to_track_quat('-Z', 'Y').to_euler()
    lamp.data.energy = 0
    dark = render(s, folder, 'scene_off')
    assert white.mean() > dark.mean() * 1.10
    lamp.data.energy = 500
    lamp.location.x *= -1
    lamp.rotation_euler = (center-lamp.location).to_track_quat('-Z', 'Y').to_euler()
    side = render(s, folder, 'scene_other_side')
    assert np.abs(white-side).mean() > .003
    assert links(s.compositing_node_group) == compositor and s.frame_current == frame
    invalid = [(g.name, f.data_path) for g in list(bpy.data.node_groups)+[m.node_tree for m in bpy.data.materials if m.use_nodes]
               for f in (g.animation_data.drivers if g.animation_data else []) if not f.is_valid]
    assert not invalid, invalid
    # Save ONLY a new QA artifact, then verify the stored graph reopens.
    target = folder / 'SceneResponse_QA.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(target), compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(target), use_scripts=False)
    s = bpy.context.scene
    assert s['rpt_scene_response_revision'] == 1
    reopened = render(s, folder, 'reopened')
    assert np.abs(side-reopened).max() < .01
    result = {'source': path, 'studio_max_error': float(difference.max()), 'studio_mean_error': float(difference.mean()),
              'red_mean': red.mean(axis=(0,1)).tolist(), 'blue_mean': blue.mean(axis=(0,1)).tolist(),
              'white_mean': float(white.mean()), 'off_mean': float(dark.mean()), 'away_mean': float(away.mean()),
              'direction_mean_difference': float(np.abs(white-side).mean()),
              'preserved_controls_defaults_compositor': True, 'idempotent': True, 'drivers_valid': True, 'reopened': True}
    (folder/'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print('SCENE_RESPONSE_PASS', path, flush=True)
