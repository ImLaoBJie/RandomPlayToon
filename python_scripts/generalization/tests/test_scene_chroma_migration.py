"""Render saved revision-1 styles before/after colour-only migration.

Original files are read-only. Checks idempotence, saved controls, studio pixels,
and captures the identical face closeup at the original sampling quality.
"""
import sys, json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'addons'))
from random_play_toon import style_panel as ui
from random_play_toon.materials.scene_response import apply

OUT = ROOT / 'experiments/SceneResponseDelivery/Migration'
OUT.mkdir(exist_ok=True)
reports = []

def render(scene, path):
    ui.refresh(scene)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(im.pixels[:]).reshape(im.size[1], im.size[0], 4)
    bpy.data.images.remove(im)
    return pixels

for path in sys.argv[sys.argv.index('--')+1:]:
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), use_scripts=False)
    s = bpy.context.scene
    assert s.get('rpt_scene_response_revision') == 1
    name = Path(path).stem
    audit = json.loads(s['rpt_nose_audit'])
    mesh = bpy.data.objects[ui.registry(s).get('mesh_object', 'Vivian_Mapping')]
    center = mesh.matrix_world @ (Vector(audit['tip']) + Vector((0, 0, audit['face_width'] * .15)))
    s.camera.data.type = 'ORTHO'
    s.camera.data.ortho_scale = audit['face_width'] * 1.8
    s.camera.location = center + Vector((0, -2, 0))
    s.camera.rotation_euler = (center - s.camera.location).to_track_quat('-Z', 'Y').to_euler()
    s.render.resolution_x = s.render.resolution_y = 480
    s.render.resolution_percentage = 100
    quality = {k: getattr(s.eevee, k) for k in ['taa_render_samples', 'fast_gi_ray_count', 'shadow_ray_count']}
    defaults = s['zzz_stage6_defaults']
    links = [(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in s.compositing_node_group.links]
    ui.lighting_set(s, 1)
    studio_before = render(s, OUT / (name + '_studio_before.png'))
    ui.lighting_set(s, 0)
    before = render(s, OUT / (name + '_before.png'))
    controls = ui.capture(s)
    apply(s)
    assert ui.capture(s) == controls and s['zzz_stage6_defaults'] == defaults
    assert links == [(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in s.compositing_node_group.links]
    counts = {g.name: len(g.nodes) for g in bpy.data.node_groups}
    apply(s)
    assert counts == {g.name: len(g.nodes) for g in bpy.data.node_groups}
    after = render(s, OUT / (name + '_after.png'))
    ui.lighting_set(s, 1)
    studio_after = render(s, OUT / (name + '_studio_after.png'))
    delta = np.abs(studio_before - studio_after)
    assert delta.mean() < .00002 and delta.max() < .02, (delta.mean(), delta.max())
    assert quality == {k: getattr(s.eevee, k) for k in quality}
    reports.append({'file': path, 'revision': s['rpt_scene_response_revision'], 'studio_mean_error': float(delta.mean()), 'studio_max_error': float(delta.max()), 'quality_unchanged': quality, 'controls_defaults_compositor_preserved': True, 'idempotent': True})
    print('CHROMA_MIGRATION_PASS', name, flush=True)
(OUT / 'validation.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf8')
