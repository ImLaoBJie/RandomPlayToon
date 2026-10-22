"""Narrow, source-verified Vivian swimsuit gem/heart repairs.

The PMX keeps the two untextured faceted gems in slot 11, the heart insert
inside slot 6 and the neck frame inside the mixed hair/accessory slot 14.
No material slots, source geometry, UVs or existing control values change.
"""
import json
import hashlib
import struct
from pathlib import Path

import bpy
import numpy as np

from .. import style_panel as ui
from .graph import Graph
from .style_upgrade import add, source
from .controls import output
from .feature_extension import stabilize_control_paths
from .decoder import image_node
from .vivian_parity import color_value

IDENTITY = 'Generic_9f9d072c5986'
REVISION = 2
METAL_MAP_SHA256 = '5bd230503a5e3d9a48de1373943417191418dbea6aa2602d27534c68ececce8e'
HEART_FACES = (3688, 3689, 3701, 3702, 3720, 3721, 3733, 3734,
               3762, 3763, 12712, 12720)
HAIR_FACE_RANGES = ((24815, 33440), (33445, 33677), (35496, 35605))
HAIR_SOURCE_CORNERS_SHA256 = 'd7eaf61ee0cd5346a748e365c7fe8ebafa580a17f1dbc6076de5211f8bb6d3bb'


def _region(mesh, name, indices):
    """Per-corner constants isolate complete source faces without splitting them."""
    attribute = mesh.attributes.get(name)
    if attribute is None:
        attribute = mesh.attributes.new(name, 'FLOAT', 'CORNER')
    if attribute.domain != 'CORNER' or attribute.data_type != 'FLOAT':
        raise ValueError('Unexpected attribute: ' + name)
    values = np.zeros(len(mesh.loops), dtype=np.float32)
    for index in indices:
        values[list(mesh.polygons[index].loop_indices)] = 1
    attribute.data.foreach_set('value', values)


def _mask(q, name):
    node = q.node('ShaderNodeAttribute', name)
    node.attribute_name = name
    return node.outputs['Fac']


def _authored_hair_region(entry, mesh):
    """Exact HairB/C position+UV matches; HairA is the mixed accessory draw."""
    faces = [i for start, end in HAIR_FACE_RANGES for i in range(start, end + 1)]
    uv = mesh.uv_layers['UVMap'].data
    evidence = bytearray()
    for index in faces:
        p = mesh.polygons[index]
        if len(p.vertices) != 3 or p.material_index != entry['slot']:
            raise ValueError('Vivian swimsuit authored hair material changed')
        evidence.extend(struct.pack('<8i6f', p.index, p.material_index,
            *p.loop_indices, *p.vertices, *(v for i in p.loop_indices for v in uv[i].uv)))
    if hashlib.sha256(evidence).hexdigest() != HAIR_SOURCE_CORNERS_SHA256:
        raise ValueError('Vivian swimsuit authored hair topology changed')
    name = 'rpt_swimsuit_authored_hair'
    _region(mesh, name, faces)
    mat = bpy.data.materials[entry['material']]
    channels = mat.node_tree.nodes.get('RPT authored LightMap B')
    if channels:
        q = Graph(mat.node_tree)
        original = channels.outputs['Blue']
        targets = [link.to_socket for link in original.links]
        selected = q.math('MULTIPLY', original, _mask(q, name),
                          'RPT exact authored hair draw coverage')
        for target in targets:
            q.put(selected, target)
    return len(faces)


def _decoded_hair_class(entry):
    """The verified atlas also contains cloth/metal in the PMX hair slot."""
    mat = bpy.data.materials[entry['material']]
    decoder = mat.node_tree.nodes.get('已审核的控制通道')
    if decoder is None:
        return
    q = Graph(mat.node_tree)
    original = decoder.outputs['Specular Mask']
    targets = [link.to_socket for link in original.links]
    hair = q.math('MULTIPLY', q.math('GREATER_THAN', decoder.outputs['Material ID Raw'], .8),
                  q.math('LESS_THAN', decoder.outputs['Metal Mask'], .05))
    hair = q.math('MULTIPLY', hair, _mask(q, 'rpt_swimsuit_authored_hair'))
    selected = q.math('MULTIPLY', original, hair, 'RPT verified swimsuit hair class')
    for target in targets:
        q.put(selected, target)


def _gem(entry, glob):
    mat = bpy.data.materials[entry['material']]
    q = Graph(mat.node_tree)
    geo = mat.node_tree.nodes['Surface']
    # Reuse the established Vivian cobalt/deep-blue cut-plane palette.  The
    # swimsuit PMX genuinely has no diffuse image for these source gem faces.
    # Reuse Vivian's existing optical normal field, normalized over the exact
    # authored GemA UV extent.  This adds interior cuts to its coplanar front
    # faces while retaining the PMX UV data and the actual exterior normals.
    uv = mat.node_tree.nodes['Original PMX UV'].outputs[0]
    coords = q.vec('MULTIPLY', q.vec('SUBTRACT', uv, (.21429899335, .12664800882, 0)),
                   (1 / .05388700962, 1 / .08475697041, 1))
    field = image_node(mat.node_tree, Path(__file__).parents[1] /
                       'specializations/vivian/resources/textures/crystal_facets.png', data=True)
    field.name = 'RPT existing Vivian optical facet field';field.image.pack()
    field.extension = 'EXTEND';q.put(coords, field.inputs['Vector'])
    internal = q.node('ShaderNodeNormalMap', 'RPT swimsuit internal optical cuts')
    internal.uv_map = 'UVMap';internal.inputs['Strength'].default_value = .95
    q.put(field.outputs['Color'], internal.inputs['Color'])
    facing = q.math('ABSOLUTE', q.vec('DOT_PRODUCT', internal.outputs[0],
                                    geo.outputs['Incoming']))
    facets = q.smooth(facing, .20, .96, 'RPT swimsuit gem actual cut planes')
    blue = q.mix((.003, .004, .025, 1), (.009, .025, .39, 1), facets,
                 'RPT swimsuit cobalt gem interior')
    direction = mat.node_tree.nodes['Independent light / head pose'].outputs['Light Direction']
    half = q.vec('NORMALIZE', q.vec('ADD', direction, geo.outputs['Incoming']))
    nh = q.math('MAXIMUM', q.vec('DOT_PRODUCT', internal.outputs[0], half), 0.)
    flash = q.smooth(q.math('POWER', nh, 20.), .04, .6, 'RPT swimsuit optical cut flash')
    flash = q.math('MULTIPLY', flash, q.math('MULTIPLY',
                   ui.node(entry).outputs['Local Specular'], output(q, glob, 'Global Specular')))
    blue = q.vec('ADD', blue, q.vec('SCALE', (.12, .24, .95), flash))
    q.put(blue, mat.node_tree.nodes['原色乘色'].inputs[1])
    toon = mat.node_tree.nodes['共享 EEVEE 卡通着色']
    q.put(geo.outputs['True Normal'], toon.inputs['Normal'])
    q.put(1., toon.inputs['Specular Mask'])
    q.put(.9, toon.inputs['Smoothness'])
    mat['rpt_swimsuit_gem_source'] = 'GemA: all 264 PMX corners match authored UV and X-mirrored game positions exactly; no PMX diffuse'


def _heart(entry, mesh):
    # Validated isolated connected component: 12 faces / 14 source vertices,
    # PMX UV x .51331.. .55923, y .12253.. .16216; pink insert only, no frame.
    uv = mesh.uv_layers.get('UVMap')
    for index in HEART_FACES:
        poly = mesh.polygons[index]
        if poly.material_index != entry['slot']:
            raise ValueError('Vivian swimsuit heart source material changed')
        for loop in poly.loop_indices:
            x, y = uv.data[loop].uv
            if not (.51330 < x < .55924 and .12252 < y < .16217):
                raise ValueError('Vivian swimsuit heart source UV changed')
    name = 'rpt_swimsuit_heart_inner'
    _region(mesh, name, HEART_FACES)
    add(entry, 'Heart Inner Glow', '心形内芯发光强度', 0., 0, 10,
        '05 发光', '只调节腿环心形装饰中间的粉色内芯；0保留原有明暗，不影响金属边框和其他衣物。')
    mat = bpy.data.materials[entry['material']]
    q = Graph(mat.node_tree)
    control = ui.node(entry)
    base = mat.node_tree.nodes['原色乘色'].outputs[0]
    strength = q.math('MULTIPLY', _mask(q, name), control.outputs['Heart Inner Glow'])
    glow = q.vec('SCALE', base, strength, 'RPT isolated heart inner emission')
    emission = mat.node_tree.nodes['Final stylized surface']
    q.put(q.vec('ADD', source(emission.inputs['Color']), glow,
               'RPT preserve surface plus heart glow'), emission.inputs['Color'])


def _frame(entry, mesh, glob, asset_root):
    # Geometry is only a broad safety boundary; the authored LightMap.G is
    # the actual metal mask.  Hair, bow fabric and back decorations are excluded.
    selected = []
    for poly in mesh.polygons:
        if poly.material_index != entry['slot']:
            continue
        if all(abs(mesh.vertices[v].co.x) < .065 and
               -.13 < mesh.vertices[v].co.y < -.02 and
               1.23 < mesh.vertices[v].co.z < 1.33 for v in poly.vertices):
            selected.append(poly.index)
    name = 'rpt_swimsuit_front_gem_frame'
    _region(mesh, name, selected)
    mat = bpy.data.materials[entry['material']]
    q = Graph(mat.node_tree)
    tex = image_node(mat.node_tree, asset_root / 'VivianSummerBodyCLightMap.dds', data=True)
    tex.name = 'RPT verified swimsuit metal mask';tex.label = tex.name
    tex.image.pack()
    uv = mat.node_tree.nodes['Original PMX UV'].outputs[0]
    xyz = q.node('ShaderNodeSeparateXYZ', 'RPT swimsuit DDS sampling')
    q.put(uv, xyz.inputs[0])
    corrected = q.node('ShaderNodeCombineXYZ', 'RPT swimsuit DDS V correction')
    q.put(xyz.outputs[0], corrected.inputs[0])
    q.put(q.math('SUBTRACT', 1., xyz.outputs[1]), corrected.inputs[1])
    q.put(corrected.outputs[0], tex.inputs['Vector'])
    channels = q.node('ShaderNodeSeparateColor', 'RPT authored swimsuit metal channel')
    q.put(tex.outputs['Color'], channels.inputs[0])
    metal = q.math('MULTIPLY', _mask(q, name), channels.outputs['Green'])
    control = ui.node(entry)
    geo = mat.node_tree.nodes['Surface']
    glossy = q.node('ShaderNodeBsdfAnisotropic', 'RPT swimsuit metal scene reflection')
    glossy.inputs['Color'].default_value = (.72, .78, .9, 1)
    glossy.inputs['Roughness'].default_value = .13
    q.put(geo.outputs['Normal'], glossy.inputs['Normal'])
    rgb = q.node('ShaderNodeShaderToRGB', 'RPT swimsuit metal reflected RGB')
    q.put(glossy.outputs[0], rgb.inputs[0])
    light = mat.node_tree.nodes['Independent light / head pose'].outputs['Light Direction']
    half = q.vec('NORMALIZE', q.vec('ADD', light, geo.outputs['Incoming']))
    nh = q.math('MAXIMUM', q.vec('DOT_PRODUCT', geo.outputs['Normal'], half), 0.)
    nv = q.math('ABSOLUTE', q.vec('DOT_PRODUCT', geo.outputs['Normal'], geo.outputs['Incoming']))
    virtual = q.math('ADD', q.math('MULTIPLY', q.math('POWER', nh, 38.), 3.2),
                     q.math('MULTIPLY', q.math('POWER', q.math('SUBTRACT', 1., nv), 3.), .6))
    virtual_color = q.vec('MULTIPLY', q.vec('SCALE', (.72, .78, .9), virtual),
                         color_value(q, glob, 'Light Color'))
    reflection = q.mix(rgb.outputs['Color'], virtual_color,
                       output(q, glob, 'Studio Mode'), 'RPT swimsuit scene or virtual metal reflection')
    # Match the existing bounded toon response: strong area-light specular
    # peaks must not turn the entire silver frame into a clipped bloom patch.
    reflected_channels = q.node('ShaderNodeSeparateColor', 'RPT swimsuit reflection peak channels')
    q.put(reflection, reflected_channels.inputs[0])
    peak = q.math('MAXIMUM', q.math('MAXIMUM', reflected_channels.outputs[0],
                                  reflected_channels.outputs[1]), reflected_channels.outputs[2])
    reflection = q.vec('SCALE', reflection, q.math('MINIMUM', 1.,
                         q.math('DIVIDE', 1.25, q.math('MAXIMUM', peak, .0001))),
                         'RPT swimsuit bounded metal reflection')
    amount = q.math('MULTIPLY', metal, q.math('MULTIPLY', control.outputs['Metal Reflection'], 2.5))
    emission = mat.node_tree.nodes['Final stylized surface']
    color = q.vec('ADD', source(emission.inputs['Color']), q.vec('SCALE', reflection, amount),
                  'RPT isolated front gem metal reflection')
    q.put(color, emission.inputs['Color'])
    return len(selected)


def apply(scene, asset_root=None):
    """Apply once to the verified source fingerprint; preserve every old setting."""
    if scene.get('rpt_identity') != IDENTITY:
        return {'status': 'not_applicable'}
    if scene.get('rpt_swimsuit_detail_revision') == REVISION:
        return json.loads(scene['rpt_swimsuit_detail_audit'])
    r = ui.registry(scene)
    mesh = bpy.data.objects[r['mesh_object']].data
    if len(mesh.vertices) != 30121 or len(mesh.polygons) != 36019:
        raise ValueError('Vivian swimsuit source topology changed')
    root = Path(asset_root) if asset_root else None
    if root is not None and not (root / 'VivianSummerBodyCLightMap.dds').is_file():
        raise ValueError('VivianSummer authored LightMap is required for the isolated metal frame repair')
    if root is not None and hashlib.sha256((root / 'VivianSummerBodyCLightMap.dds').read_bytes()).hexdigest() != METAL_MAP_SHA256:
        raise ValueError('VivianSummer authored LightMap content changed')
    if scene.get('rpt_swimsuit_detail_revision') == 1:
        entry = next(e for e in r['materials'] if e['slot'] == 14)
        count = _authored_hair_region(entry, mesh)
        _decoded_hair_class(entry)
        audit = json.loads(scene['rpt_swimsuit_detail_audit'])
        audit.update(authored_hair_faces=count, authored_hair_draw_calls=['HairB', 'HairC'])
        scene['rpt_swimsuit_detail_revision'] = REVISION
        scene['rpt_swimsuit_detail_audit'] = json.dumps(audit, ensure_ascii=False)
        return audit
    before = ui.capture(scene)
    stabilize_control_paths(r)
    entries = {e['slot']: e for e in r['materials']}
    hair_faces = _authored_hair_region(entries[14], mesh)
    _decoded_hair_class(entries[14])
    heart_entry = entries[6]
    old_labels = list(before[heart_entry['material']])
    legacy = heart_entry.setdefault('legacy_label_sets', [])
    if old_labels not in legacy:
        legacy.append(old_labels)
    _gem(entries[11], r['global'])
    _heart(entries[6], mesh)
    faces = _frame(entries[14], mesh, r['global'], root) if root is not None else 0
    scene['zzz_stage6_registry'] = json.dumps(r, ensure_ascii=False)
    defaults = json.loads(scene['zzz_stage6_defaults'])
    defaults[heart_entry['material']]['心形内芯发光强度'] = 0.
    scene['zzz_stage6_defaults'] = json.dumps(defaults, ensure_ascii=False)
    after = ui.capture(scene)
    for material, values in before.items():
        for label, value in values.items():
            if after[material][label] != value:
                raise RuntimeError('Existing control changed: ' + label)
    audit = {'status': 'applied', 'gem_slot': 11, 'gem_faces': 88,
             'authored_hair_faces': hair_faces, 'authored_hair_draw_calls': ['HairB', 'HairC'],
             'heart_slot': 6, 'heart_faces': list(HEART_FACES),
             'heart_default': 0., 'metal_slot': 14, 'metal_region_faces': faces,
             'metal_map_available': root is not None,
             'existing_controls_preserved': True}
    scene['rpt_swimsuit_detail_revision'] = REVISION
    scene['rpt_swimsuit_detail_audit'] = json.dumps(audit, ensure_ascii=False)
    return audit
