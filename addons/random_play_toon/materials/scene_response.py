"""EEVEE scene irradiance for shared toon shaders, independent of virtual light.

Adapted from the Vivian scene_response experiment. Only reflected-light paths
are tinted; authored emission, directional patches, outlines and AOV wiring
stay outside this operation. No lamps, controls or scene quality settings change.
"""
import json
import bpy
from .. import style_panel as ui
from .style_upgrade import Graph, source, output

REVISION = 2
PREFIXES = ('ZZZ_ToonSurface_v1', 'ZZZ_FaceDirection_v1')


def probe(q, normal):
    diffuse = q.node('ShaderNodeBsdfDiffuse', 'RPT scene irradiance probe')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    q.put(normal, diffuse.inputs['Normal'])
    rgb = q.node('ShaderNodeShaderToRGB', 'RPT scene irradiance RGB')
    q.put(diffuse.outputs[0], rgb.inputs[0])
    return rgb.outputs['Color']


def chroma(q, rgb):
    """Colour only; never multiply raw shadow energy into the cel result again.

    Regularization makes black samples neutral and avoids amplifying tiny RGB
    differences in shadow. White illumination remains exactly white at any power.
    Brightness and occlusion belong exclusively to the existing toon band.
    """
    sep = q.node('ShaderNodeSeparateColor', 'RPT scene chroma channels')
    q.put(rgb, sep.inputs[0])
    peak = q.math('MAXIMUM', q.math('MAXIMUM', sep.outputs[0], sep.outputs[1]), sep.outputs[2])
    return q.vec('SCALE', q.vec('ADD', rgb, (.03, .03, .03)),
                 q.math('DIVIDE', 1., q.math('ADD', peak, .03)), 'RPT scene colour only')


def response(q, rgb):
    sep = q.node('ShaderNodeSeparateColor', 'RPT scene irradiance channels')
    q.put(rgb, sep.inputs[0])
    peak = q.math('MAXIMUM', q.math('MAXIMUM', sep.outputs[0], sep.outputs[1]), sep.outputs[2])
    strength = q.math('MULTIPLY', peak, 3., 'RPT scene irradiance exposure')
    return strength, chroma(q, rgb)


def migrate_colour(tree):
    """Repair revision 1 and adopted experiments without stacking lighting bands."""
    old = [n for n in tree.nodes if n.name.startswith('RPT scene colour and energy')]
    legacy = tree.nodes.get('Scene colour / neutral studio')
    if legacy and legacy.inputs[1].is_linked:
        node = source(legacy.inputs[1]).node
        if not node.name.startswith('RPT scene colour only'):
            old.append(node)
    for node in old:
        if node.type != 'VECT_MATH' or node.operation != 'SCALE':
            raise ValueError('场景颜色旧节点结构不匹配：' + tree.name)
        rgb = source(node.inputs[0])
        sinks = [link.to_socket for link in node.outputs[0].links]
        tint = chroma(Graph(tree), rgb)
        for sink in sinks:
            Graph(tree).put(tint, sink)
        tree.nodes.remove(node)
    return len(old)


def face_normal(g):
    """Find the head-frame normal at N dot L, never by Blender's numeric suffix.

    In the frozen library NORMALIZE.001 is L, not N. The original experiment
    accidentally sampled diffuse with that light vector as its surface normal.
    """
    light = g.nodes['Inputs'].outputs['Light Direction']
    for link in light.links:
        normalizer = link.to_node
        if normalizer.type != 'VECT_MATH' or normalizer.operation != 'NORMALIZE':
            continue
        for cosine_link in normalizer.outputs['Vector'].links:
            cosine = cosine_link.to_node
            if (cosine.type == 'VECT_MATH' and cosine.operation == 'DOT_PRODUCT'
                    and cosine_link.to_socket == cosine.inputs[1] and cosine.inputs[0].is_linked):
                return source(cosine.inputs[0])
    raise ValueError('缺少脸部头坐标法线：' + g.name)


def group_plan(g):
    # Recognize the shipped experiment so applying the add-on does not stack
    # exposure/tint a second time on an already scene-responsive Vivian file.
    if 'Actual scene light colour and energy' in g.nodes and 'Scene / studio band' in g.nodes:
        if g.name.startswith(PREFIXES[1]):
            face_normal(g)  # Validate the experimental probe repair as well.
            if 'Scene authored face irradiance probe' not in g.nodes:
                raise ValueError('缺少实验版脸部采样节点：' + g.name)
        return None
    body = g.name.startswith(PREFIXES[0])
    shade = g.nodes.get('Art-directed shadow tint' if body else 'Mix.001')
    target = g.nodes.get('RPT tint reflected light; preserve emission')
    normal = g.nodes.get('EEVEE scene visibility') if body else None
    if not shade or not target or (body and not normal) or not shade.inputs[0].is_linked:
        raise ValueError('场景响应着色结构不匹配：' + g.name)
    if body and normal.bl_idname != 'ShaderNodeShaderToRGB':
        raise ValueError('缺少 EEVEE 场景采样：' + g.name)
    return shade, target.inputs[0], normal.outputs[0] if body else face_normal(g), body


def apply(scene):
    if scene.get('rpt_scene_response_revision') == REVISION:
        audit = json.loads(scene['rpt_scene_response_audit'])
        audit['adopted_experimental_groups'] = sorted(name for name in audit['groups']
            if name in bpy.data.node_groups and 'Scene colour / neutral studio' in bpy.data.node_groups[name].nodes)
        scene['rpt_scene_response_audit'] = json.dumps(audit, ensure_ascii=False)
        return audit
    r = ui.registry(scene)
    if not r.get('global') or scene.get('rpt_light_color_revision') != 1:
        raise ValueError('请先使用带角色受光颜色控制的新版角色材质')
    glob = r['global']
    materials = [bpy.data.materials[e['material']] for e in r['materials']]
    groups = {n.node_tree for mat in materials for n in mat.node_tree.nodes
              if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith(PREFIXES)}
    if not groups:
        raise ValueError('缺少可更新的角色卡通着色组')
    upgrading = scene.get('rpt_scene_response_revision') == 1
    plans = {} if upgrading else {g: group_plan(g) for g in groups}
    before = ui.capture(scene)
    for g, plan in plans.items():
        if plan is None:
            if g.name.startswith(PREFIXES[1]):
                Graph(g).put(face_normal(g), g.nodes['Scene authored face irradiance probe'].inputs['Normal'])
            migrate_colour(g)
            continue
        shade, target, sampled, body = plan
        q = Graph(g)
        i = g.nodes['Inputs'].outputs
        rgb = sampled if body else probe(q, sampled)
        strength, tint = response(q, rgb)
        mode = output(q, glob, 'Studio Mode')
        threshold = q.math('ADD', .22, q.math('MULTIPLY', i['Threshold'], .25))
        softness = q.math('MAXIMUM', i['Softness'], .08)
        band_value = strength
        if body:
            # Keep the authored LightMap bias in the scene band as well. The
            # .25 scale matches the scene threshold's conversion of toon units.
            bias = q.math('MULTIPLY', q.math('SUBTRACT', i['Shadow Bias'], .5), i['Bias Strength'])
            band_value = q.math('ADD', strength, bias, 'RPT scene authored shadow bias')
        else:
            # Retain the existing masked nose/chin correction, without importing
            # the virtual-light cosine that the actual irradiance replaces.
            masks = g.nodes.get('R nose / G chin / B valid UV')
            if masks:
                correction = q.math('ADD', q.math('MULTIPLY', masks.outputs[0], i['Nose Strength']),
                                    q.math('MULTIPLY', masks.outputs[1], i['Chin Strength']))
                band_value = q.math('SUBTRACT', strength, q.math('MULTIPLY', correction, .25),
                                    'RPT scene face feature correction')
        lit = q.smooth(band_value, q.math('SUBTRACT', threshold, softness),
                       q.math('ADD', threshold, softness), 'RPT scene toon band')
        # Include specular gating / Lit Factor consumers, retaining the complete
        # previous branch as the studio input. Capture consumers before linking.
        old = source(shade.inputs[0])
        sinks = [link.to_socket for link in old.links]
        selector = q.node('ShaderNodeMix', 'RPT scene / studio band')
        selector.data_type = 'FLOAT'
        q.put(mode, selector.inputs[0])
        q.put(lit, selector.inputs[2])
        q.put(old, selector.inputs[3])
        selected = selector.outputs[0]
        for sink in sinks:
            q.put(selected, sink)
        tint = q.mix(tint, (1, 1, 1, 1), mode, 'RPT scene colour / neutral studio')
        q.put(q.vec('MULTIPLY', source(target), tint, 'RPT actual scene reflected colour'), target)
    # Material-level authored hair bands, detail albedo and supplementary
    # reflections already have a non-emissive tint boundary from light_color.
    # Fill its previously-white scene branch; never tint the final beauty output.
    for mat in materials:
        if upgrading:
            continue
        t = mat.node_tree
        selectors = [n for n in t.nodes if n.name.startswith('RPT virtual light colour')]
        if not selectors:
            continue
        q = Graph(t)
        surface = next((n for n in t.nodes if n.type == 'GROUP' and n.node_tree
                        and n.node_tree.name.startswith(PREFIXES[0])), None)
        normal = source(surface.inputs['Normal']) if surface else q.node('ShaderNodeNewGeometry', 'RPT detail normal').outputs['Normal']
        _, tint = response(q, probe(q, normal))
        for selector in selectors:
            q.put(tint, selector.inputs[1])
    if upgrading:
        for tree in list(groups) + [mat.node_tree for mat in materials]:
            migrate_colour(tree)
    # Descriptions only: preserve every saved value and factory preset.
    for item in glob['entries']:
        if item['key'] == 'Studio Mode':
            item['description'] = '场景响应：真实灯光与 EEVEE 环境照明控制明暗和受光颜色；独立光源：保留虚拟光照风格。'
            socket = next(s for s in ui.node(glob).node_tree.interface.items_tree
                          if s.item_type == 'SOCKET' and s.in_out == 'INPUT' and s.name == item['label'])
            socket.description = item['description']
    scene['zzz_stage6_registry'] = json.dumps(r, ensure_ascii=False)
    audit = {'revision': REVISION, 'groups': sorted(g.name for g in groups),
             'adopted_experimental_groups': sorted(g.name for g in groups
                                                   if 'Scene colour / neutral studio' in g.nodes),
             'materials': [m.name for m in materials],
             'sampling': 'all EEVEE lights and available indirect illumination; no designated lamp',
             'colour_response': 'regularized chroma only; raw shadow energy is not multiplied after the toon band',
             'preserved': 'studio branch, controls, emission, patches, outlines, eye reveal, nose'}
    scene['rpt_scene_response_revision'] = REVISION
    scene['rpt_scene_response_audit'] = json.dumps(audit, ensure_ascii=False)
    assert ui.capture(scene) == before, '场景响应更新意外改变了参数'
    ui.refresh(scene)
    return audit
