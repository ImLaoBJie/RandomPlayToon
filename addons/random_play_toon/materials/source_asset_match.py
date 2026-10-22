"""Conservative UV evidence for optional controls on uncalibrated PMX models.

An asset name alone is never a binding. Original PMX albedo and geometry stay
untouched; equal diffuse files must also have equal companion controls. Existing
projects opt into the narrow highlight repair, without rerunning refinements.
"""
import hashlib
import json
from pathlib import Path

import bpy
import numpy as np


KINDS = ('Diffuse', 'NormalMap', 'LightMap', 'MaterialMap')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pixels(path):
    # Temporary images cannot change the color space of the scene's albedo.
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        width, height = image.size
        if not width or not height:
            raise ValueError('Cannot decode texture: ' + str(path))
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(height, width, 4)
    finally:
        bpy.data.images.remove(image)


def _sample(pixels, uv):
    height, width = pixels.shape[:2]
    xy = uv * (width, height) - .5
    ij = np.floor(xy).astype(np.int64)
    fraction = xy - ij
    x, y = ij.T
    fx, fy = fraction[:, 0, None], fraction[:, 1, None]
    return ((pixels[y % height, x % width] * (1-fx)
             + pixels[y % height, (x+1) % width] * fx) * (1-fy)
            + (pixels[(y+1) % height, x % width] * (1-fx)
               + pixels[(y+1) % height, (x+1) % width] * fx) * fy)


def _bundles(asset_root):
    try:
        root = Path(asset_root).expanduser().resolve()
        if not root.is_dir():
            return []
        diffuse = sorted(root.glob('*Diffuse.dds'))
        if not diffuse:
            diffuse = sorted(root.rglob('*Diffuse.dds'))
    except OSError:
        return []
    # An entire game library is not a useful implicit search scope. Callers may
    # supply the character's asset folder; no model-specific name is required.
    if len(diffuse) > 256:
        return []
    groups = {}
    for path in diffuse:
        try:
            groups.setdefault(_sha(path), []).append(path)
        except OSError:
            continue
    result = []
    for digest, paths in groups.items():
        bundles = []
        for path in paths:
            prefix = path.name[:-len('Diffuse.dds')]
            maps = {kind: path.with_name(prefix + kind + '.dds') for kind in KINDS}
            try:
                maps = {kind: p for kind, p in maps.items() if p.is_file()}
                hashes = {kind: _sha(p) for kind, p in maps.items()}
            except OSError:
                # An unreadable alias cannot prove equality of companion maps.
                # Reject its whole same-diffuse group rather than pick a peer.
                bundles = []
                break
            bundles.append((maps, hashes))
        if not bundles:
            continue
        signatures = {json.dumps(hashes, sort_keys=True) for _, hashes in bundles}
        result.append({'diffuse': paths[0], 'maps': bundles[0][0],
                       'hashes': bundles[0][1], 'aliases': [str(p) for p in paths],
                       'ambiguous': len(signatures) != 1})
    return result


def resolve(profile, inputs, asset_root, *, slots=None):
    """Fill absent map bindings only after UV-sampled albedo correspondence.

    Call after resolving original textures, before building new materials. Known
    profiles are deliberately excluded. Missing/uncertain evidence is a fallback,
    never a build error. Returns an audit and mutates only accepted bindings.
    """
    if not profile.get('uncalibrated') or not asset_root:
        return []
    bundles = _bundles(asset_root)
    if not bundles:
        return []
    from .._vendor.mmd_tools.core import pmx
    try:
        model = pmx.load(inputs['pmx'])
    except (OSError, pmx.InvalidFileError, pmx.UnsupportedVersionError, ValueError, IndexError):
        return []
    vertices = np.asarray([v.uv for v in model.vertices], dtype=np.float64)
    vertices[:, 1] = 1 - vertices[:, 1]  # Blender's imported PMX UV convention.
    faces = np.asarray(model.faces, dtype=np.int64)
    rows = []
    for material in profile['materials']:
        slot = material['index']
        if material.get('maps') or (slots is not None and slot not in slots):
            continue
        path = inputs.get('textures', {}).get(str(slot))
        if not path or not material.get('face_count'):
            continue
        triangles = faces[material['face_start']:material['face_start'] + material['face_count']]
        triangles = triangles[np.linspace(0, len(triangles)-1, min(800, len(triangles)), dtype=int)]
        uv = np.einsum('sk,tkj->tsj', np.array([[1/3]*3, [.6,.2,.2], [.2,.6,.2]]),
                       vertices[triangles]).reshape(-1, 2)
        try:
            color = _sample(_pixels(path), uv)
            source_sha256 = _sha(Path(path))
        except (OSError, RuntimeError, ValueError):
            continue
        visible = color[:, 3] > .5
        if visible.sum() < 64:
            continue
        rows.append({'material': material, 'uv': uv, 'color': color,
                     'visible': visible, 'source_sha256': source_sha256, 'candidates': []})
    for bundle in bundles:
        try:
            pixels = _pixels(bundle['diffuse'])
        except (OSError, RuntimeError, ValueError):
            continue
        for row in rows:
            visible = row['visible']
            for flip in (False, True):
                uv = row['uv'].copy()
                if flip:
                    uv[:, 1] = 1 - uv[:, 1]
                error = np.abs(row['color'][visible, :3] - _sample(pixels, uv)[visible, :3]).mean(1) * 255
                row['candidates'].append({'bundle': bundle, 'flip_v': flip,
                    'mean': float(error.mean()), 'p95': float(np.quantile(error, .95)),
                    'below12': float((error < 12).mean())})
    audit = []
    for row in rows:
        candidates = sorted(row['candidates'], key=lambda c: c['mean'])
        if not candidates:
            continue
        best = candidates[0]
        bundle = best['bundle']
        variation = float(row['color'][row['visible'], :3].std(axis=0).mean() * 255)
        next_error = candidates[1]['mean'] if len(candidates) > 1 else 255.
        accepted = (not bundle['ambiguous'] and 'LightMap' in bundle['maps']
                    and best['mean'] < 5 and best['below12'] > .9 and variation > 7
                    and next_error > max(best['mean'] + 4, best['mean'] * 2 + 1))
        evidence = {key: value for key, value in best.items() if key != 'bundle'}
        evidence.update(slot=row['material']['index'], accepted=accepted,
                        source_sha256=row['source_sha256'], texture_rgb_std=variation,
                        sample_count=int(row['visible'].sum()), next_error=next_error,
                        ambiguous_companions=bundle['ambiguous'],
                        diffuse_aliases=bundle['aliases'])
        audit.append(evidence)
        if not accepted:
            continue
        material = row['material']
        material.update(matching='uv_sample_verified', dds_flip_v=best['flip_v'],
                        source_asset_evidence=evidence,
                        maps={kind: {'file': path.name, 'sha256': bundle['hashes'][kind]}
                              for kind, path in bundle['maps'].items()})
        inputs['maps'][str(material['index'])] = {kind: str(path) for kind, path in bundle['maps'].items()}
    return audit


def _hair_target(control):
    # Locate the previously empty texture-mask branch through the existing
    # strength output, not through generated Math.001 names or all POWER nodes.
    strength = control.outputs.get('Hair Highlights')
    if strength is None:
        return None
    for link in strength.links:
        first = link.to_node
        if first.type != 'MATH' or first.operation != 'MULTIPLY':
            continue
        for next_link in first.outputs[0].links:
            band = next_link.to_node
            if band.type != 'MATH' or band.operation != 'MULTIPLY':
                continue
            other = band.inputs[1] if next_link.to_socket == band.inputs[0] else band.inputs[0]
            if not other.is_linked:
                continue
            maximum = other.links[0].from_node
            if maximum.type != 'MATH' or maximum.operation != 'MAXIMUM' or not maximum.inputs[0].is_linked:
                continue
            power = maximum.inputs[0].links[0].from_node
            if power.type != 'MATH' or power.operation != 'POWER' or abs(power.inputs[1].default_value-.7) > .0001:
                continue
            if not power.inputs[0].is_linked:
                continue
            clamp = power.inputs[0].links[0].from_node
            if (clamp.type == 'MATH' and clamp.operation == 'MAXIMUM'
                    and not clamp.inputs[0].is_linked and not clamp.inputs[1].is_linked
                    and clamp.inputs[0].default_value == 0 and clamp.inputs[1].default_value == 0):
                return clamp.inputs[0]
    return None


def bind_authored_highlight(scene, entry, binding, asset_root, *, lightmap_path=None,
                            mask_attribute=None, material_class=None):
    """Connect only LightMap.B to an empty authored hair/cap highlight mask.

    Existing albedo, normal, shadow bias, opacity and control values are untouched.
    A cap uses its existing local/global basic specular controls. Repeated calls
    are harmless; calibrated shaders and nonzero/custom masks are not replaced.
    """
    from .. import style_panel as ui
    from .decoder import image_node
    from .graph import Graph
    material = bpy.data.materials[entry['material']]
    tree = material.node_tree
    if tree.nodes.get('RPT verified authored highlight'):
        return {'slot': entry['slot'], 'status': 'already_bound'}
    if tree.nodes.get('已审核的控制通道'):
        return {'slot': entry['slot'], 'status': 'existing_decoder_preserved'}
    item = binding.get('maps', {}).get('LightMap')
    if not item:
        return {'slot': entry['slot'], 'status': 'no_verified_lightmap'}
    path = Path(lightmap_path) if lightmap_path else Path(asset_root) / item['file']
    if not path.is_file() or _sha(path) != item['sha256']:
        raise ValueError('Verified LightMap changed: ' + str(path))
    control = ui.node(entry)
    if entry.get('role') == 'hair':
        target = _hair_target(control)
    else:
        toon = tree.nodes.get('共享 EEVEE 卡通着色')
        target = toon.inputs.get('Specular Mask') if toon else None
        if target and (target.is_linked or target.default_value != 0):
            target = None
    if target is None:
        return {'slot': entry['slot'], 'status': 'custom_or_unrecognized_mask_preserved'}
    uv = tree.nodes.get('DDS V correction' if binding.get('dds_flip_v', True) else 'Original PMX UV')
    if uv is None:
        raise ValueError('Missing original DDS sampling coordinates: ' + material.name)
    graph = Graph(tree)
    tex = image_node(tree, str(path), data=True)
    tex.name = tex.label = 'RPT verified authored highlight'
    tex.image.pack()
    graph.put(uv.outputs[0], tex.inputs['Vector'])
    channels = graph.node('ShaderNodeSeparateColor', 'RPT authored LightMap B')
    graph.put(tex.outputs['Color'], channels.inputs['Color'])
    mask = channels.outputs['Blue']
    if mask_attribute:
        region = graph.node('ShaderNodeAttribute', 'RPT authored hair region')
        region.attribute_name = mask_attribute
        mask = graph.math('MULTIPLY', mask, region.outputs['Fac'])
    if material_class:
        # An explicitly audited material-ID class can exclude cloth/metal when
        # a PMX "hair" slot contains several semantic surfaces in one atlas.
        for channel, lower, upper in material_class:
            selection = graph.math('MULTIPLY',
                graph.math('GREATER_THAN', channels.outputs[channel], lower),
                graph.math('LESS_THAN', channels.outputs[channel], upper))
            mask = graph.math('MULTIPLY', mask, selection)
    graph.put(mask, target)
    material['rpt_authored_highlight'] = json.dumps({'file': path.name,
        'sha256': item['sha256'], 'channel': 'B', 'flip_v': binding.get('dds_flip_v', True),
        'matching': binding.get('matching'), 'mask_attribute': mask_attribute,
        'material_class': material_class, 'scope': 'highlight mask only'}, ensure_ascii=False)
    return {'slot': entry['slot'], 'status': 'bound', 'file': path.name, 'channel': 'B',
            'flip_v': binding.get('dds_flip_v', True)}
