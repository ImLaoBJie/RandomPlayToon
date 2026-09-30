"""Portable VMD camera sampling. No dependency on MMD Tools or runtime handlers.

Raw MMD coordinates use (x,z,y) in Blender, unlike the already converted
right-handed physics cache consumed by core.py. Curves belong to the right key.
"""
import bisect
import hashlib
import json
import math
import struct
from pathlib import Path


def read_vmd(path):
    data = Path(path).read_bytes()
    if not data.startswith(b'Vocaloid Motion Data 0002'):
        raise ValueError('只支持 VMD 0002 格式。')
    offset = 50

    def count_and_skip(size):
        nonlocal offset
        if offset+4 > len(data):
            raise ValueError('VMD 不完整：缺少轨道计数。')
        count, = struct.unpack_from('<I', data, offset)
        offset += 4
        begin = offset
        offset += count*size
        if offset > len(data):
            raise ValueError('VMD 不完整：轨道数据被截断。')
        return count, begin

    bones, _ = count_and_skip(111)
    morphs, _ = count_and_skip(23)
    count, begin = count_and_skip(61)
    if not count:
        raise ValueError(f'此 VMD 没有相机轨道（骨骼 {bones}、表情 {morphs}）。请选择作者的相机 VMD。')
    keys = {}
    for n in range(count):
        row = struct.unpack_from('<I7f24BIB', data, begin+n*61)
        frame, distance = row[:2]
        loc, rot = list(row[2:5]), list(row[5:8])
        curve, angle, perspective = list(row[8:32]), row[32], row[33] == 0
        if not all(math.isfinite(v) for v in [distance]+loc+rot) or not 0 < angle < 180 or any(v > 127 for v in curve):
            raise ValueError(f'相机第 {frame} 帧有无效数值或插值。')
        keys[frame] = dict(frame=frame, distance=distance, location=loc, rotation=rot,
                           curve=curve, angle=angle, perspective=perspective)
    return dict(schema=1, path=str(Path(path).resolve()), sha256=hashlib.sha256(data).hexdigest(),
                keys=[keys[k] for k in sorted(keys)], duplicate_keys=count-len(keys))


def bezier(x, controls):
    # VMD stores x1,x2,y1,y2, each in [0,127]. Solve x(t), then evaluate y(t).
    a, b, c, d = [v/127 for v in controls]
    if a == c and b == d:
        return x
    lo, hi = 0., 1.
    for _ in range(32):
        t = (lo+hi)*.5
        xt = 3*(1-t)**2*t*a+3*(1-t)*t*t*b+t**3
        if xt < x:
            lo = t
        else:
            hi = t
    return 3*(1-t)**2*t*c+3*(1-t)*t*t*d+t**3


def evaluate(keys, frame, detect_cuts=True, key_frames=None):
    frames = key_frames if key_frames is not None else [k['frame'] for k in keys]
    index = bisect.bisect_right(frames, frame)
    if index == 0:
        return keys[0]
    if index == len(keys):
        return keys[-1]
    a, b = keys[index-1:index+1]
    if detect_cuts and b['frame']-a['frame'] <= 1:
        return a
    x = (frame-a['frame'])/(b['frame']-a['frame'])
    weights = [bezier(x, b['curve'][i:i+4]) for i in range(0, 24, 4)]
    def lerp(a, b, w):
        return a+(b-a)*w
    return dict(location=[lerp(a['location'][i], b['location'][i], weights[i]) for i in range(3)],
                rotation=[lerp(a['rotation'][i], b['rotation'][i], weights[3]) for i in range(3)],
                distance=lerp(a['distance'], b['distance'], weights[4]),
                angle=lerp(a['angle'], b['angle'], weights[5]), perspective=a['perspective'])


def timing(source_fps, target_fps, speed, warmup, origin):
    if not all(math.isfinite(v) for v in [source_fps, target_fps, speed, warmup, origin]):
        raise ValueError('时间设置必须为有限数值。')
    if not 1 <= source_fps <= 240 or not 1 <= target_fps <= 240 or not .01 <= speed <= 100 or warmup < 0:
        raise ValueError('帧率、时长倍数或预热时间超出范围。')
    return target_fps/source_fps*speed, warmup*target_fps+origin


def bake(scene, track, source_fps=30., duration_scale=1., warmup_seconds=0.,
         start_frame=0., spatial_scale=None, detect_cuts=True):
    import bpy
    import numpy as np
    from .core import action_curves
    fps = scene.render.fps/scene.render.fps_base
    transfer = json.loads(scene.get('rpc_transfer', '{}'))
    if transfer and abs(transfer['fps']-fps) > 1e-5:
        raise ValueError('场景帧率已手动更改，头部控制尚未同步。请先点击“同步 ABC 时间轴到当前帧率”。')
    factor, offset = timing(source_fps, fps, duration_scale, warmup_seconds, start_frame)
    scale = spatial_scale if spatial_scale is not None else transfer.get('meters_per_pmx_unit', .1)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('相机空间比例必须大于零。')
    keys = track['keys']
    key_frames = [k['frame'] for k in keys]
    mapped = [f*factor+offset for f in key_frames]
    # Include exact mapped keys/cuts as well as integer output frames. Padding
    # holds the initial camera during warmup instead of extrapolating motion.
    lo, hi = min(scene.frame_start, math.floor(mapped[0])), max(scene.frame_end, math.ceil(mapped[-1]))
    if hi-lo > 250000:
        raise ValueError('相机输出超过 250000 帧，请检查帧率和时长倍数。')
    frames = sorted(set([float(f) for f in range(lo, hi+1)]+mapped))
    samples = [evaluate(keys, (f-offset)/factor, detect_cuts, key_frames) for f in frames]
    cuts = [mapped[i] for i in range(1,len(keys)) if detect_cuts and key_frames[i]-key_frames[i-1] <= 1]
    # Stage a new rig; only replace the previous tool-owned rig after success.
    root = bpy.data.objects.new('RPC_CameraTarget', None)
    data = bpy.data.cameras.new('RPC_VMD_Camera')
    camera = bpy.data.objects.new('RPC_VMD_Camera', data)
    scene.collection.objects.link(root)
    scene.collection.objects.link(camera)
    camera.parent = root
    root.rotation_mode = 'YXZ'
    camera.rotation_euler = (math.pi/2, 0, 0)
    data.sensor_fit = 'VERTICAL'
    data.clip_start = max(.001, scale*.1)
    data.clip_end = max(100., scale*500)
    root['rpc_camera_owned'] = True
    camera['rpc_camera_owned'] = True

    def curve(owner, path, values, constant=False):
        owner.keyframe_insert(path, frame=frames[0])
        for fc in action_curves(owner):
            if fc.data_path != path:
                continue
            vals = values if np.ndim(values) == 1 else np.array(values)[:,fc.array_index]
            points = fc.keyframe_points
            points.clear()
            points.add(len(frames))
            points.foreach_set('co', np.column_stack([frames, vals]).astype(np.float32).ravel())
            for i, p in enumerate(points):
                p.interpolation = 'CONSTANT' if constant or (i+1 < len(frames) and any(frames[i] < c <= frames[i+1] for c in cuts)) else 'LINEAR'
            fc.update()
    try:
        curve(root, 'location', [[s['location'][i]*scale for i in (0,2,1)] for s in samples])
        curve(root, 'rotation_euler', [[s['rotation'][i] for i in (0,2,1)] for s in samples])
        curve(camera, 'location', [[0,s['distance']*scale,0] for s in samples])
        curve(camera, 'rotation_euler', [[math.pi/2, math.pi if not s['perspective'] and s['distance'] > 1e-5 else 0,0] for s in samples], True)
        curve(data, 'lens', [data.sensor_height/(2*math.tan(math.radians(s['angle'])/2)) for s in samples])
        curve(data, 'ortho_scale', [max(.00001,25*abs(s['distance']*scale)/45) for s in samples])
        curve(data, 'type', [0 if s['perspective'] else 1 for s in samples], True)
    except Exception:
        bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.objects.remove(root, do_unlink=True)
        bpy.data.cameras.remove(data)
        raise
    old = json.loads(scene.get('rpc_camera', '{}'))
    old_actions, old_data = [], []
    for name in [old.get('camera'), old.get('root')]:
        ob = bpy.data.objects.get(name) if name else None
        if ob and ob.get('rpc_camera_owned') and ob not in [root, camera]:
            if ob.animation_data and ob.animation_data.action:
                old_actions.append(ob.animation_data.action)
            if ob.type == 'CAMERA':
                old_data.append(ob.data)
                if ob.data.animation_data and ob.data.animation_data.action:
                    old_actions.append(ob.data.animation_data.action)
            bpy.data.objects.remove(ob, do_unlink=True)
    for data_block in old_data:
        if data_block.users == 0:
            bpy.data.cameras.remove(data_block)
    for action in set(old_actions):
        if action.users == 0:
            bpy.data.actions.remove(action)
    text = bpy.data.texts.get(old.get('text','')) or bpy.data.texts.new('RPC_原始相机轨道.json')
    text.clear()
    text.write(json.dumps(track, ensure_ascii=False))
    scene.camera = camera
    report = dict(camera=camera.name, root=root.name, text=text.name, source=track['path'],
                  source_sha256=track['sha256'], source_fps=source_fps, target_fps=fps,
                  duration_scale=duration_scale, warmup_seconds=warmup_seconds, start_frame=start_frame,
                  spatial_scale=scale, detect_cuts=detect_cuts, total_frame_multiplier=factor,
                  offset_frames=offset, source_keys=len(keys), sampled_frames=len(frames), cuts=len(cuts),
                  motion_frame_range=[mapped[0], mapped[-1]])
    scene['rpc_camera'] = json.dumps(report, ensure_ascii=False)
    scene.frame_set(scene.frame_current)
    return report


def synchronize_fps(scene):
    """Retiming the baked head preserves seconds; Alembic already uses seconds."""
    import bpy
    from .core import action_curves
    report = json.loads(scene.get('rpc_transfer', '{}'))
    if not report:
        raise ValueError('请先打开 ABC 套用结果。')
    fps = scene.render.fps/scene.render.fps_base
    ratio = fps/report['fps']
    head = bpy.data.objects.get(report.get('head_object','')) or bpy.data.objects.get('RPT_HeadFrame') or bpy.data.objects.get('ZZZ_HeadFrame')
    if head is None or not head.animation_data or not head.animation_data.action:
        raise ValueError('缺少已烘焙的头部方向控制。')
    old_frame = scene.frame_current_final
    for fc in action_curves(head):
        for p in fc.keyframe_points:
            p.co.x *= ratio
            p.handle_left.x *= ratio
            p.handle_right.x *= ratio
        fc.update()
    scene.frame_start = round(scene.frame_start*ratio)
    scene.frame_end = round(scene.frame_end*ratio)
    report.update(fps=fps, frame_range=[scene.frame_start, scene.frame_end])
    scene['rpc_transfer'] = json.dumps(report, ensure_ascii=False)
    cam = json.loads(scene.get('rpc_camera','{}'))
    if cam:
        track = json.loads(bpy.data.texts[cam['text']].as_string())
        kwargs = {k:cam[k] for k in ['source_fps','duration_scale','warmup_seconds','start_frame','spatial_scale','detect_cuts']}
        kwargs['start_frame'] *= ratio
        bake(scene, track, **kwargs)
        if hasattr(scene, 'rpc_camera_settings'):
            scene.rpc_camera_settings.start_frame = kwargs['start_frame']
    scene.frame_set(round(old_frame*ratio))
    return fps
