"""Choose the initial patch color from original, area-weighted PMX colors.

Only new builds call this module. Existing projects and personal presets keep
their color; this is a default value, not a render-time color controller.
"""
import colorsys
import json
from pathlib import Path

import numpy as np

EXCLUDED = {'skin', 'face', 'eyes', 'eye_white', 'eye_highlight', 'eye_shadow',
            'brows_lashes', 'mouth', 'mouth_line', 'hair_overlay', 'weapon', 'emissive'}


def linear(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def srgb(rgb):
    rgb = np.maximum(np.asarray(rgb, dtype=float), 0)
    return np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - .055)


def hex_color(rgb):
    return '#' + ''.join(f'{int(round(v * 255)):02X}' for v in np.clip(rgb, 0, 1))


def choose(samples, weights, hair):
    """RGB samples are sRGB; weights include triangle area and source opacity."""
    rgb = np.clip(np.asarray(samples, dtype=float).reshape(-1, 3), 0, 1)
    weights = np.asarray(weights, dtype=float)
    hair = np.asarray(hair, dtype=bool)
    hsv = np.array([colorsys.rgb_to_hsv(*c) for c in rgb]).reshape(-1, 3)
    h, s, v = hsv.T
    valid = np.isfinite(rgb).all(axis=1) & np.isfinite(weights) & (weights > 0)
    # Mixed clothing/skin atlases are common in uncalibrated swimsuit models.
    skin = (~hair) & (h >= .025) & (h <= .115) & (s < .48) & (v > .58)
    surface_weight = float(weights[valid & ~skin].sum())
    valid &= (s >= .16) & (v >= .20) & ~skin
    chroma_weights = np.where(valid, weights * np.minimum(s / .4, 1), 0)
    total = float(chroma_weights.sum())
    coverage = total / max(surface_weight, 1e-10)
    if total <= 1e-10 or coverage < .08:
        return {'source_hex': '#FFFFFF', 'srgb_hex': '#FFFFFF',
                'linear_rgba': [1., 1., 1., 1.], 'cluster_share': 0., 'chromatic_coverage': round(coverage, 4),
                'method': 'neutral: no reliable chromatic surface'}
    bins = (np.floor(h * 36).astype(int) % 36)
    histogram = np.bincount(bins, weights=chroma_weights, minlength=36)
    smooth = sum(np.roll(histogram, offset) for offset in (-2, -1, 0, 1, 2))
    center = (int(np.argmax(smooth)) + .5) / 36
    distance = np.abs((h - center + .5) % 1 - .5)
    selected = valid & (distance <= 2.5 / 36)
    w = chroma_weights[selected]
    source = np.average(rgb[selected], axis=0, weights=w)
    hue, saturation, _ = colorsys.rgb_to_hsv(*source)
    # Retain the dominant hue while making a readable light-colored patch.
    color = colorsys.hsv_to_rgb(hue, float(np.clip(saturation * .65, .22, .48)), 1.)
    return {'source_hex': hex_color(source), 'srgb_hex': hex_color(color),
            'linear_rgba': [*linear(color).tolist(), 1.],
            'cluster_share': round(float(w.sum() / total), 4),
            'chromatic_coverage': round(coverage, 4),
            'method': 'PMX UV samples weighted by surface area and opacity'}


def infer(obj, profile, inputs):
    """Read only source geometry, albedo, diffuse and semantic material roles."""
    import bpy
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangles = list(mesh.loop_triangles)
    slots = np.array([t.material_index for t in triangles])
    areas = np.array([t.area for t in triangles], dtype=float)
    loops = np.array([t.loops[:] for t in triangles], dtype=int).reshape(-1, 3)
    layer = mesh.uv_layers.get('UVMap') or mesh.uv_layers.active
    uv = np.array([d.uv[:] for d in layer.data]) if layer else None
    barycentric = np.array([[1/3, 1/3, 1/3], [.6, .2, .2], [.2, .6, .2], [.2, .2, .6]])
    colors, weights, hairs, used = [], [], [], []
    for material in profile['materials']:
        role = material['role']
        diffuse = np.asarray(material.get('diffuse', [1, 1, 1, 1]), dtype=float)
        mask = (slots == material['index']) & (areas > 0)
        if role in EXCLUDED or diffuse[3] <= .0001 or not mask.any():
            continue
        area = np.repeat(areas[mask] / 4, 4)
        path = inputs.get('textures', {}).get(str(material['index']))
        if path and Path(path).is_file() and uv is not None:
            image = bpy.data.images.load(str(path), check_existing=True)
            width, height = image.size[:]
            if not width or not height:
                continue
            pixels = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            pixels = pixels.reshape(height, width, 4)
            points = np.einsum('ab,tbc->tac', barycentric, uv[loops[mask]]).reshape(-1, 2) % 1
            sampled = pixels[(points[:, 1] * height).astype(int), (points[:, 0] * width).astype(int)]
            # Blender file-backed sRGB image pixels retain their encoded values.
            rgb = srgb(linear(sampled[:, :3]) * diffuse[:3])
            opacity = sampled[:, 3] * diffuse[3]
        else:
            rgb = np.tile(srgb(diffuse[:3]), (len(area), 1))
            opacity = np.full(len(area), diffuse[3])
        colors.extend(rgb);weights.extend(area * opacity)
        hairs.extend([role == 'hair'] * len(area))
        used.append({'slot': material['index'], 'name': material['name'], 'role': role})
    result = choose(colors, weights, hairs)
    result['materials'] = used
    return result


def apply(scene, result):
    from .. import style_panel as ui
    entry = ui.registry(scene)['global']
    ui.node(entry).inputs['亮块颜色'].default_value = result['linear_rgba']
    if 'zzz_stage6_defaults' in scene:
        defaults = json.loads(scene['zzz_stage6_defaults'])
        defaults[entry['material']]['亮块颜色'] = result['linear_rgba']
        scene['zzz_stage6_defaults'] = json.dumps(defaults, ensure_ascii=False)
    scene['rpt_patch_palette'] = json.dumps(result, ensure_ascii=False)
