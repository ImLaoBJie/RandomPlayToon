"""EEVEE scene irradiance for shared toon shaders, independent of virtual light.

Adapted from the Vivian scene_response experiment. Only reflected-light paths
are tinted; authored emission, directional patches, outlines and AOV wiring
stay outside this operation. No lamps, controls or scene quality settings change.
"""
import json
import bpy
from .. import style_panel as ui
from .style_upgrade import Graph, source, output

REVISION = 3
PREFIXES = ('ZZZ_ToonSurface_v1', 'ZZZ_FaceDirection_v1')


def probe(q, normal):
    diffuse = q.node('ShaderNodeBsdfDiffuse', 'RPT scene irradiance probe')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    q.put(normal, diffuse.inputs['Normal'])
    rgb = q.node('ShaderNodeShaderToRGB', 'RPT scene irradiance RGB')
    q.put(diffuse.outputs[0], rgb.inputs[0])
    return rgb.outputs['Color']


def chroma(q, rgb, peak=None):
    """Colour only; never multiply raw shadow energy into the cel result again.

    Regularization makes black samples neutral and avoids amplifying tiny RGB
    differences in shadow. White illumination remains exactly white at any power.
    Brightness and occlusion belong exclusively to the existing toon band.
    """
    if peak is None:
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
    return strength, chroma(q, rgb, peak)


def lighting_band(q, g, strength, body):
    i = g.nodes['Inputs'].outputs
    threshold = q.math('ADD', .22, q.math('MULTIPLY', i['Threshold'], .25))
    softness = q.math('MAXIMUM', i['Softness'], .001)
    band_value = strength
    if body:
        bias = q.math('MULTIPLY', q.math('SUBTRACT', i['Shadow Bias'], .5), i['Bias Strength'])
        band_value = q.math('ADD', strength, bias, 'RPT scene authored shadow bias')
    else:
        masks = g.nodes.get('R nose / G chin / B valid UV')
        if masks:
            correction = q.math('ADD', q.math('MULTIPLY', masks.outputs[0], i['Nose Strength']),
                                q.math('MULTIPLY', masks.outputs[1], i['Chin Strength']))
            band_value = q.math('SUBTRACT', strength, q.math('MULTIPLY', correction, .25),
                                'RPT scene face feature correction')
    return q.smooth(band_value, q.math('SUBTRACT', threshold, softness),
                    q.math('ADD', threshold, softness), 'RPT scene toon band')


def update_experimental_band(g):
    selector = g.nodes.get('Scene / studio band')
    if selector is None or 'RPT scene toon band' in g.nodes:
        return
    q = Graph(g)
    # The experiment switched only the visible albedo mix, leaving Lit Factor
    # and the original nose/chin/LightMap controls on a different lighting path.
    lit = lighting_band(q, g, g.nodes['Scene irradiance exposure'].outputs[0], g.name.startswith(PREFIXES[0]))
    q.put(lit, selector.inputs[1])
    studio = source(selector.inputs[2])
    for link in list(studio.links):
        if link.to_node != selector:
            q.put(selector.outputs[0], link.to_socket)


def contains_toon_colour(socket, seen=None):
    """Find an already tinted colour, not a scalar Lit Factor dependency."""
    seen = set() if seen is None else seen
    for link in socket.links:
        node = link.from_node
        if node.as_pointer() in seen:
            continue
        if node.type == 'GROUP':
            if node.node_tree and node.node_tree.name.startswith(PREFIXES) and link.from_socket.name == 'Color':
                return True
            continue
        seen.add(node.as_pointer())
        if any(contains_toon_colour(i, seen) for i in node.inputs):
            return True
    return False


def single_scene_tint(tree, glob):
    # Some pre-existing hair gain/peak-limit branches wrap the whole surface.
    # Its shared toon base already receives scene chroma. Preserve the exact
    # old studio factor, but do not multiply scene chroma over the surface again.
    q = Graph(tree)
    for node in list(tree.nodes):
        if (node.name.startswith(('RPT tint supplementary reflected light', 'RPT authored highlight light colour'))
                and contains_toon_colour(node.inputs[0])):
            factor = source(node.inputs[1])
            if isinstance(factor, bpy.types.NodeSocket) and factor.node.name.startswith('RPT prevent repeated scene tint'):
                continue
            q.put(q.mix((1, 1, 1, 1), factor, output(q, glob, 'Studio Mode'),
                        'RPT prevent repeated scene tint'), node.inputs[1])


def prune_scene_orphans(tree):
    """Remove only disconnected scene-response arithmetic/probes, never controls."""
    live = set()
    def visit(node):
        if node.as_pointer() in live:
            return
        live.add(node.as_pointer())
        for socket in node.inputs:
            for link in socket.links:
                visit(link.from_node)
    for node in tree.nodes:
        if node.type in {'GROUP_OUTPUT', 'OUTPUT_MATERIAL', 'OUTPUT_AOV'}:
            visit(node)
    allowed = {'MATH', 'VECT_MATH', 'SEPARATE_COLOR', 'BSDF_DIFFUSE', 'SHADER_TO_RGB'}
    pending = [n for n in tree.nodes if n.name.startswith('RPT scene ') or n.name in {'Scene exposure shoulder', 'Scene toon lighting band'}]
    remove = set()
    while pending:
        node = pending.pop()
        if node in remove or node.as_pointer() in live or node.type not in allowed:
            continue
        remove.add(node)
        pending.extend(l.from_node for s in node.inputs for l in s.links)
        pending.extend(l.to_node for s in node.outputs for l in s.links)
    for node in remove:
        tree.nodes.remove(node)
    return len(remove)


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
        return json.loads(scene['rpt_scene_response_audit'])
    r = ui.registry(scene)
    if not r.get('global') or scene.get('rpt_light_color_revision') != 1:
        raise ValueError('请先使用带角色受光颜色控制的新版角色材质')
    glob = r['global']
    materials = [bpy.data.materials[e['material']] for e in r['materials']]
    groups = {n.node_tree for mat in materials for n in mat.node_tree.nodes
              if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith(PREFIXES)}
    if not groups:
        raise ValueError('缺少可更新的角色卡通着色组')
    upgrading = scene.get('rpt_scene_response_revision') in {1, 2}
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
        rgb = sampled if body else probe(q, sampled)
        strength, tint = response(q, rgb)
        mode = output(q, glob, 'Studio Mode')
        lit = lighting_band(q, g, strength, body)
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
        selectors = [n for n in t.nodes if n.name.startswith('RPT virtual light colour') and n.outputs[0].is_linked]
        if not selectors:
            continue
        q = Graph(t)
        surface = next((n for n in t.nodes if n.type == 'GROUP' and n.node_tree
                        and n.node_tree.name.startswith(PREFIXES[0])), None)
        normal = source(surface.inputs['Normal']) if surface else q.node('ShaderNodeNewGeometry', 'RPT detail normal').outputs['Normal']
        tint = chroma(q, probe(q, normal))
        for selector in selectors:
            q.put(tint, selector.inputs[1])
    if upgrading:
        for tree in list(groups) + [mat.node_tree for mat in materials]:
            migrate_colour(tree)
    for g in groups:
        update_experimental_band(g)
        for node in g.nodes:
            if (node.type == 'MATH' and node.operation == 'MAXIMUM'
                    and node.inputs[0].is_linked and source(node.inputs[0]) == g.nodes['Inputs'].outputs['Softness']
                    and not node.inputs[1].is_linked and abs(node.inputs[1].default_value - .08) < 1e-6):
                node.inputs[1].default_value = .001
    for mat in materials:
        tree = mat.node_tree
        single_scene_tint(tree, glob)
        for node in tree.nodes:
            if node.name.startswith('RPT virtual light colour') and not node.outputs[0].is_linked:
                for link in list(node.inputs[1].links):
                    tree.links.remove(link)
                node.inputs[1].default_value = (1, 1, 1, 1)
    removed = sum(prune_scene_orphans(t) for t in list(groups) + [m.node_tree for m in materials])
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
             'removed_unused_scene_nodes': removed,
             'preserved': 'studio branch, controls, emission, patches, outlines, eye reveal, nose'}
    scene['rpt_scene_response_revision'] = REVISION
    scene['rpt_scene_response_audit'] = json.dumps(audit, ensure_ascii=False)
    assert ui.capture(scene) == before, '场景响应更新意外改变了参数'
    ui.refresh(scene)
    return audit
