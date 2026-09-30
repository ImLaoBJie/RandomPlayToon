"""Incremental virtual-light colour and bounded authored-hair response.

No UV offsets, new highlight masks, frame handlers or source image edits.
The frozen Vivian library is migrated in memory, never written back.
"""
import json
import bpy
from .. import style_panel as ui
from .style_upgrade import Graph, add, source, output
from .vivian_parity import color_value

REVISION = 1
REMOVED = {'Hair Ring Fill', 'Hair Ring Height', 'Hair Ring Width'}


def depends(socket, keys, seen=None):
    """Trace scalar control provenance within a material, stopping at groups."""
    if not isinstance(socket, bpy.types.NodeSocket):
        return False
    seen = set() if seen is None else seen
    if socket.as_pointer() in seen:
        return False
    seen.add(socket.as_pointer())
    n = socket.node
    if socket.name in keys or n.name in keys or n.name.removeprefix('全局 · ') in keys:
        return True
    if n.type in {'GROUP', 'GROUP_INPUT'}:
        return False
    return any(depends(l.from_socket, keys, seen) for s in n.inputs for l in s.links)


def light_tint(q, glob):
    return q.mix((1, 1, 1, 1), color_value(q, glob, 'Light Color'),
                 output(q, glob, 'Studio Mode'), 'RPT virtual light colour')


def multiply_input(q, socket, tint, name):
    q.put(q.vec('MULTIPLY', source(socket), tint, name), socket)


def remove_ring(entry):
    n = ui.node(entry)
    for item in list(entry['entries']):
        if item['key'] not in REMOVED:
            continue
        # Disconnect before removing the interface; the disabled branch becomes zero.
        if item['key'] == 'Hair Ring Fill':
            for link in list(n.outputs[item['key']].links):
                sink = link.to_socket
                n.id_data.links.remove(link)
                sink.default_value = 0.
        entry.setdefault('retired_labels', []).append(item['label'])
        for s in list(n.node_tree.interface.items_tree):
            if s.item_type == 'SOCKET' and ((s.in_out == 'INPUT' and s.name == item['label']) or
                                           (s.in_out == 'OUTPUT' and s.name == item['key'])):
                n.node_tree.interface.remove(s)
        entry['entries'].remove(item)


def scene_chroma(q, normal, entry, glob):
    """EEVEE irradiance colour only: neither its exposure nor shadows reach beauty.

    Shader-to-RGB samples lights and EEVEE-provided indirect illumination. Dark
    samples tend to neutral. A neutral sample is EXACTLY white after normalization.
    """
    d = q.node('ShaderNodeBsdfDiffuse', 'RPT hair scene colour probe')
    d.inputs['Color'].default_value = (1, 1, 1, 1)
    q.put(normal, d.inputs['Normal'])
    sr = q.node('ShaderNodeShaderToRGB', 'RPT hair scene irradiance')
    q.put(d.outputs[0], sr.inputs[0])
    sep = q.node('ShaderNodeSeparateColor', 'RPT hair scene RGB')
    q.put(sr.outputs['Color'], sep.inputs[0])
    peak = q.math('MAXIMUM', q.math('MAXIMUM', sep.outputs[0], sep.outputs[1]), sep.outputs[2])
    # Regularised normalization: no black sample can blacken the highlight.
    chroma = q.vec('SCALE', q.vec('ADD', sr.outputs['Color'], (.03, .03, .03)),
                   q.math('DIVIDE', 1., q.math('ADD', peak, .03)))
    amount = q.math('MULTIPLY', ui.node(entry).outputs['Hair Scene Tint'], output(q, glob, 'Studio Mode'))
    return q.mix((1, 1, 1, 1), chroma, amount,
                 'RPT subtle scene colour only')


def hair_motion(q, directions, coordinate, entry, reference):
    # Broad modulation INSIDE the existing authored mask, never a new stripe.
    elevation = q.vec('DOT_PRODUCT', directions.outputs['Light Direction'], directions.outputs['Head Up'])
    delta = q.math('SUBTRACT', elevation, reference)
    shift = q.math('MULTIPLY', delta, .025)
    def envelope(center):
        x = q.math('DIVIDE', q.math('SUBTRACT', coordinate, center), .18)
        return q.math('EXPONENT', q.math('MULTIPLY', q.math('MULTIPLY', x, x), -1))
    difference = q.math('SUBTRACT', envelope(q.math('ADD', .52, shift)), envelope(.52))
    return q.math('ADD', 1., q.math('MULTIPLY', difference, ui.node(entry).outputs['Hair Highlight Motion']),
                  'RPT bounded authored highlight drift')


def apply(scene):
    if scene.get('rpt_light_color_revision') == REVISION:
        return json.loads(scene['rpt_light_color_audit'])
    r = ui.registry(scene)
    if not r.get('global'):
        raise ValueError('当前文件没有 RandomPlayToon 参数注册表')
    if r.get('generic') and scene.get('rpt_detail_revision') != 1:
        raise ValueError('请先使用 0.7.6 或更高版本的已校准场景')
    glob = r['global']
    # Validate known graph shapes before adding any controls. The UI operator
    # must not leave a partially upgraded custom/unsupported shader on failure.
    for entry in r['materials']:
        for n in bpy.data.materials[entry['material']].node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith('ZZZ_ToonSurface_v1'):
                go = next(x for x in n.node_tree.nodes if x.type == 'GROUP_OUTPUT' and x.is_active_output)
                final = source(go.inputs['Color'])
                if not isinstance(final,bpy.types.NodeSocket) or final.node.type != 'VECT_MATH' or final.node.operation != 'ADD':
                    raise ValueError('卡通组已经自定义修改，不能自动升级：'+n.node_tree.name)
    old_defaults = json.loads(scene['zzz_stage6_defaults'])
    for entry in [glob] + r['materials']:
        entry.setdefault('legacy_label_sets', []).append([s.name for s in ui.node(entry).inputs])
    add(glob, 'Light Color', '角色受光颜色', (1., 1., 1., 1.), 0, 1, '00 光照方式',
        '仅独立虚拟光照：给受光、阴影及反光乘色；白色保留原效果。原贴图、自发光、描边与后期分别控制。')
    item = glob['entries'].pop()
    index = next(i for i, e in enumerate(glob['entries']) if e['key'] == 'Display Light')
    glob['entries'].insert(index + 1, item)
    gn = ui.node(glob)
    socket = next(s for s in gn.node_tree.interface.items_tree if s.item_type == 'SOCKET' and s.in_out == 'INPUT' and s.name == '角色受光颜色')
    brightness = next(s for s in gn.node_tree.interface.items_tree if s.item_type == 'SOCKET' and s.in_out == 'INPUT' and s.name == '展示亮面亮度')
    gn.node_tree.interface.move_to_parent(socket, brightness.parent, brightness.position + 1)
    # One shared change covers body, face, skin, stockings and both neck seam shaders.
    groups = set()
    for entry in r['materials']:
        for n in bpy.data.materials[entry['material']].node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith(('ZZZ_ToonSurface_v1', 'ZZZ_FaceDirection_v1')):
                groups.add(n.node_tree)
    for g in groups:
        q = Graph(g)
        go = next(n for n in g.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
        target = go.inputs['Color']
        if g.name.startswith('ZZZ_ToonSurface'):
            final = source(target).node
            if final.type != 'VECT_MATH' or final.operation != 'ADD':
                raise ValueError('不支持的卡通组输出结构：' + g.name)
            # Last ADD adds candidate self-emission. Tint only the preceding light.
            target = final.inputs[0]
        multiply_input(q, target, light_tint(q, glob), 'RPT tint reflected light; preserve emission')
    counts = []
    for entry in r['materials']:
        mat = bpy.data.materials[entry['material']]
        q = Graph(mat.node_tree)
        nodes = list(mat.node_tree.nodes)
        tint = light_tint(q, glob)
        is_hair = entry.get('role') == 'hair' or (not r.get('generic') and entry['slot'] == 14)
        remove_ring(entry)
        hair_band = []
        scale_keys = {'Key Gain', 'Metal Reflection', 'Broad Metal Reflection', 'Stocking Sheen', 'Curl Sheen'}
        for n in nodes:
            if n.type == 'VECT_MATH' and n.operation == 'SCALE':
                scalar = source(n.inputs['Scale'])
                if depends(scalar, {'Hair Highlights'}):
                    hair_band.append(n)
                elif depends(scalar, scale_keys):
                    multiply_input(q, n.inputs[0], tint, 'RPT tint supplementary reflected light')
            # Scene/virtual reflection selector; only virtual branch gets global colour.
            if n.type == 'MIX_RGB' and n.blend_type == 'MIX' and n.inputs[1].is_linked:
                if n.inputs[1].links[0].from_node.type == 'SHADER_TO_RGB' and n.inputs[2].is_linked:
                    multiply_input(q, n.inputs[2], tint, 'RPT tint virtual reflection')
        if is_hair and hair_band:
            add(entry, 'Hair Scene Tint', '高光环境染色', .08, 0, .25, '05 头发',
                '仅独立展示：原贴图发束高光少量接收真实灯光和 EEVEE 环境照明颜色；不继承其亮度。0关闭，默认0.08。')
            add(entry, 'Hair Highlight Motion', '发束亮点微移', .08, 0, .2, '05 头发',
                '随虚拟光相对头部的俯仰，轻微调整原贴图高光内部的亮度重心；不移动UV和边界。0关闭。')
            toon = next(n for n in nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith('ZZZ_ToonSurface'))
            d = mat.node_tree.nodes.get('Independent light / head pose') or mat.node_tree.nodes['Shared style / animated directions']
            normal = source(toon.inputs['Normal'])
            chroma = scene_chroma(q, normal, entry, glob)
            if r.get('generic'):
                a = q.node('ShaderNodeAttribute', 'RPT authored highlight height');a.attribute_name = 'RPT_HairBandHeight'
                coordinate = a.outputs['Fac']
            else:
                coordinate = q.math('DIVIDE', q.math('SUBTRACT', mat.node_tree.nodes['Hair height'].outputs['Z'], 1.46), .12)
            # Fixed neutral reference from the DEFAULT virtual light, not the upgrade
            # frame/pose. Thus rebuilding and migrating reproduce identical nodes.
            import math
            reference = math.sin(math.radians(old_defaults[glob['material']]['虚拟光俯仰角（度）']))
            motion = hair_motion(q, d, coordinate, entry, reference)
            for n in hair_band:
                multiply_input(q, n.inputs[0], q.vec('MULTIPLY', tint, chroma), 'RPT authored highlight light colour')
                q.put(q.math('MULTIPLY', source(n.inputs['Scale']), motion), n.inputs['Scale'])
        counts.append({'slot': entry['slot'], 'hair_branches': len(hair_band)})
    scene['zzz_stage6_registry'] = json.dumps(r, ensure_ascii=False)
    # Keep the saved baseline and user edits separate; never turn a tuned scene
    # into the new factory preset when adding controls.
    defaults = ui.capture(scene)
    for mat, values in defaults.items():
        for label in values.keys() & old_defaults.get(mat, {}).keys():
            values[label] = old_defaults[mat][label]
    scene['zzz_stage6_defaults'] = json.dumps(defaults, ensure_ascii=False)
    audit = {'revision': REVISION, 'groups': sorted(g.name for g in groups), 'materials': counts,
             'hair_motion': 'bounded brightness redistribution inside the existing mask; no UV shift',
             'scene_tint': 'EEVEE diffuse irradiance chromaticity only; max influence 0.25'}
    scene['rpt_light_color_revision'] = REVISION
    scene['rpt_light_color_audit'] = json.dumps(audit, ensure_ascii=False)
    ui.refresh(scene)
    return audit
