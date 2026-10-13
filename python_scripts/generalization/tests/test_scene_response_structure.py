"""Preservation checks and fresh PMX builds; no supplied source is saved."""
import sys
import json
import hashlib
import uuid
from pathlib import Path
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'addons'))
from random_play_toon import style_panel as ui
from random_play_toon.materials.scene_response import apply
from random_play_toon.materials.feature_extension import role
from random_play_toon.core import build
from random_play_toon.portable import embed_panel

OUT = ROOT/'experiments/SceneResponseRelease'
OUT.mkdir(exist_ok=True)


def state():
    meshes = {}
    for mesh in bpy.data.meshes:
        parts = []
        for seq, prop, size, dtype in [(mesh.vertices, 'co', 3, np.float32), (mesh.loops, 'vertex_index', 1, np.int32)]:
            a = np.empty(len(seq)*size, dtype=dtype);seq.foreach_get(prop, a);parts.append(a.tobytes())
        for uv in mesh.uv_layers:
            a = np.empty(len(uv.data)*2, dtype=np.float32);uv.data.foreach_get('uv', a);parts.append(a.tobytes())
        meshes[mesh.name] = hashlib.sha256(b''.join(parts)).hexdigest()
    return {'mesh': meshes, 'objects': {o.name: [list(row) for row in o.matrix_world] for o in bpy.context.scene.objects},
            'lights': {o.name: (o.data.type, o.data.energy, tuple(o.data.color)) for o in bpy.context.scene.objects if o.type == 'LIGHT'}}


def protected_links():
    records = []
    for mat in bpy.data.materials:
        if not mat.use_nodes:continue
        for node in mat.node_tree.nodes:
            if (node.type in {'OUTPUT_AOV', 'EMISSION', 'OUTPUT_MATERIAL'} or
                node.name.startswith(('RPT Directional colored patch', 'RPT isolated ', 'RPT Nose', 'RPT nose'))):
                records.append((mat.name, node.name, [(socket.identifier, [(l.from_node.name, l.from_socket.identifier) for l in socket.links]) for socket in node.inputs]))
    tree = bpy.context.scene.compositing_node_group
    records.append(('compositor', [(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links]))
    return records


def validate():
    s = bpy.context.scene
    before, links, controls, defaults = state(), protected_links(), ui.capture(s), s['zzz_stage6_defaults']
    report = apply(s)
    assert state() == before
    assert protected_links() == links
    assert ui.capture(s) == controls and s['zzz_stage6_defaults'] == defaults
    assert apply(s) == report
    for mode in [0, 1, 0, 1]:
        ui.lighting_set(s, mode)
        for mat, values in controls.items():
            for label, value in values.items():
                if label != '独立展示光照':assert ui.capture(s)[mat][label] == value, label
    for entry in ui.all_entries(s):
        for socket in ui.node(entry).inputs:socket.default_value = controls[entry['material']][socket.name]
    ui.refresh(s)
    assert ui.capture(s) == controls
    return report


reports = []
for name in ['Vivian', 'Yuzuha', 'Alice', 'SunnaMaid', 'AriaDiscordant', 'Remielle', 'YeShunguang', 'NangongYuRapsody']:
    path = ROOT/f'experiments/NoseShadow/CleanBuild/{name}_new.blend'
    bpy.ops.wm.open_mainfile(filepath=str(path), use_scripts=False)
    reports.append({'character': name, 'audit': validate()})
    print('SCENE_STRUCTURE_PASS', name, flush=True)

for path in [ROOT/'experiments/VivianReferenceStyles/Vivian_Reference1_CoolGlow.blend',
             ROOT/'experiments/VivianReferenceStyles/Vivian_Reference2_CrispCel.blend',
             ROOT/'experiments/NoseShadow/Animation/BassShake_EEVEE_Stage_NoseShadow.blend']:
    bpy.ops.wm.open_mainfile(filepath=str(path), use_scripts=False)
    report = validate()
    if 'Reference2' in path.name:assert len(report['adopted_experimental_groups']) == 2
    folder = OUT/'Templates';folder.mkdir(exist_ok=True)
    embed_panel()
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/(path.stem+'_SceneResponse.blend')), compress=True)
    reports.append({'template': path.name, 'audit': report})
    print('SCENE_TEMPLATE_PASS', path.name, flush=True)

for name in ['Vivian', 'SunnaMaid']:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    profile = json.loads((ROOT/f'addons/random_play_toon/specializations/profiles/{name}.json').read_text(encoding='utf8'))
    pmx = ROOT/'assets_preprocessed'/profile['pmx']
    folder = OUT/'FreshBuild'/uuid.uuid4().hex;folder.mkdir(parents=True)
    target = folder/(name+'.blend')
    build(str(pmx), str(pmx.parent), str(ROOT/'assets_preprocessed'/profile['asset_directory']), str(target))
    assert bpy.context.scene['rpt_scene_response_revision'] == 2
    bpy.ops.wm.open_mainfile(filepath=str(target), use_scripts=False)
    assert bpy.context.scene['rpt_scene_response_revision'] == 2
    reports.append({'fresh_pmx': name, 'reopened': True})
    print('SCENE_FRESH_BUILD_PASS', name, flush=True)
(OUT/'structure_validation.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf8')
