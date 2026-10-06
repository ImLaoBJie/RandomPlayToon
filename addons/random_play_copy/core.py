"""Transfer a calibrated scene to a verified, topology-preserving Alembic.

No dependency on random_play_toon, MMD Tools or the motion exporter.
Only a new background-process scene is changed. Original sources are read-only.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

VERSION = '0.8.4'
PROFILES = {
    'Vivian': 'c6b0f02794a1cc89a1aeef1e3cc1f5a20891e3c2f25370981dffe1f6b827cc6f',
    'SunnaMaid': '545a9ba0d601cfc5209dc9029a805a38f752d5ab8e3b4a819dca9c79d9ff394e',
}
C = np.array([[1., 0, 0], [0, 0, -1.], [0, 1., 0]])


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def array(data, prop, size=1, dtype=np.float32):
    a = np.empty(len(data)*size, dtype)
    data.foreach_get(prop, a)
    return a.reshape(-1, size) if size > 1 else a


def registry(scene):
    return json.loads(scene.get('zzz_stage6_registry', '{}'))


def source_object(scene):
    return bpy.data.objects.get(registry(scene).get('mesh_object', 'Vivian_Mapping'))


def controls(scene):
    r = registry(scene)
    return {e['material']: {s.name: s.default_value if isinstance(s.default_value, (float, int, bool, str)) else list(s.default_value)
                           for s in bpy.data.materials[e['material']].node_tree.nodes[e['node']].inputs if hasattr(s, 'default_value')}
            for e in r.get('materials', [])+[r['global']]}


def rigid_fit(rest, target):
    a, b = rest.mean(0), target.mean(0)
    x, y = rest-a, target-b
    u, _, vt = np.linalg.svd(x.T@y)
    sign = np.eye(3)
    sign[2, 2] = np.sign(np.linalg.det(vt.T@u.T))
    rot = vt.T@sign@u.T
    scale = float(np.sum((x@rot.T)*y)/np.sum(x*x))
    offset = b-scale*(rot@a)
    error = float(np.max(np.linalg.norm(scale*(rest@rot.T)+offset-target, axis=1)))
    return rot, offset, scale, error


def head_anchors(obj):
    arm = obj.find_armature()
    if not arm or '頭' not in arm.data.bones or '頭' not in obj.vertex_groups:
        raise ValueError('模板缺少頭骨及顶点权重，无法验证头部方向。')
    rest = array(obj.data.vertices, 'co', 3)
    group = obj.vertex_groups['頭'].index
    ids = np.array([v.index for v in obj.data.vertices if any(g.group == group and g.weight > .9999 for g in v.groups)])
    unchanged = np.ones(len(rest), bool)
    if obj.data.shape_keys:
        for key in obj.data.shape_keys.key_blocks:
            unchanged &= np.max(np.abs(array(key.data, 'co', 3)-rest), axis=1) < 1e-6
    ids = ids[unchanged[ids]]
    if len(ids) < 20 or np.linalg.matrix_rank(rest[ids]-rest[ids].mean(0), tol=1e-5) < 3:
        raise ValueError('缺少足够的无表情变形头部锚点。')
    # Distributed deterministic subsampling bounds fallback fitting cost.
    ids = ids[np.linspace(0, len(ids)-1, min(512, len(ids))).astype(int)]
    bone = arm.data.bones['頭']
    return ids, rest, np.array(arm.matrix_world@bone.matrix_local)


def action_curves(obj):
    action = obj.animation_data.action
    slot = obj.animation_data.action_slot
    for layer in action.layers:
        for strip in layer.strips:
            bag = strip.channelbag(slot)
            if bag:
                yield from bag.fcurves


def bake_head(scene, head, matrices, frames):
    head.constraints.clear()
    head.parent = None
    head.animation_data_clear()
    head.rotation_mode = 'QUATERNION'
    locations, rotations = [], []
    previous = None
    for matrix in matrices:
        loc, q, _ = Matrix(matrix.tolist()).decompose()
        if previous is not None and q.dot(previous) < 0:
            q.negate()
        previous = q.copy()
        locations.append(tuple(loc))
        rotations.append(tuple(q))
    head.location = locations[0]
    head.rotation_quaternion = rotations[0]
    for path in ['location', 'rotation_quaternion']:
        head.keyframe_insert(path, frame=float(frames[0]))
    for fc in action_curves(head):
        values = locations if fc.data_path == 'location' else rotations
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(frames))
        data = np.column_stack([frames, np.array(values)[:, fc.array_index]]).astype(np.float32)
        fc.keyframe_points.foreach_set('co', data.ravel())
        for key in fc.keyframe_points:
            key.interpolation = 'LINEAR'
        fc.update()


def head_motion(meta, qa, ids, rest, bone_rest, cache_obj, scene, force_fit=False):
    frames = np.arange(meta['sample_count'], dtype=float)+meta['start_seconds']*meta['fps']
    if len(frames) != round((meta['end_seconds']-meta['start_seconds'])*meta['fps'])+1:
        raise ValueError('当前版本需要每帧一个 Alembic 样本。')
    physics = Path(meta['input'].get('cache', ''))
    matrices = []
    method = 'ABC rigid-head fit'
    errors = []
    if physics.is_file() and not force_fit:
        if digest(physics) != meta['input']['cache_sha256']:
            raise ValueError('原动作控制缓存校验失败；请恢复正确文件。')
        with np.load(physics, allow_pickle=False) as p:
            names = p['bone_names'].tolist()
            times = p['times']
            indices = np.searchsorted(times, frames/meta['fps']-1e-7)
            if np.any(indices >= len(times)) or np.max(abs(times[indices]*meta['fps']-frames)) > 1e-4:
                raise ValueError('头部控制缓存时间与 Alembic 不一致。')
            h = p['global_matrices'][indices, names.index('頭')].astype(np.float64)
        method = 'verified baked bone matrices (no physics recomputation)'
        rotations = C@h[:, :3, :3]@C.T
        translations = h[:, :3, 3]@C.T*meta['meters_per_pmx_unit']
        scales = []
        for i, time in enumerate(qa['times']):
            n = round((time-meta['start_seconds'])*meta['fps'])
            target = qa['positions'][i, ids]@C.T
            x = (rest[ids]-bone_rest[:3, 3])@rotations[n].T
            y = target-translations[n]
            scale = float(np.sum(x*y)/np.sum(x*x))
            scales.append(scale)
            errors.append(float(np.max(np.linalg.norm(x*scale-y, axis=1))))
        scale = float(np.median(scales))
        if max(errors) > 2e-5 or max(abs(np.array(scales)-scale)) > 1e-4:
            raise ValueError('头部骨骼轨迹与 ABC 顶点不一致。')
        for rot, trans in zip(rotations, translations):
            matrix = np.eye(4)
            matrix[:3, :3] = rot@bone_rest[:3, :3]
            matrix[:3, 3] = trans
            matrices.append(matrix)
    else:
        # Self-contained fallback: read ABC only, using rest-space rigid vertices.
        scale = None
        for frame in frames:
            scene.frame_set(int(frame))
            dg = bpy.context.evaluated_depsgraph_get()
            ev = cache_obj.evaluated_get(dg)
            me = ev.to_mesh()
            target = array(me.vertices, 'co', 3)[ids]
            rot, trans, current_scale, error = rigid_fit(rest[ids], target)
            ev.to_mesh_clear()
            scale = current_scale if scale is None else scale
            if error > 2e-5 or abs(current_scale-scale) > 1e-4:
                raise ValueError(f'帧 {frame} 的头部无法可靠拟合：{error:.6g} m')
            matrix = np.eye(4)
            matrix[:3, :3] = rot@bone_rest[:3, :3]
            matrix[:3, 3] = rot@(bone_rest[:3, 3]*scale)+trans
            matrices.append(matrix)
            errors.append(error)
            if int(frame) % 500 == 0:
                print('HEAD FIT', int(frame), '/', len(frames), flush=True)
    return np.array(matrices), frames, dict(method=method, anchor_count=len(ids), maximum_anchor_error_m=max(errors),
                                           source_to_cache_scale=scale, baked_frames=len(frames))


def uv_bridge():
    group = bpy.data.node_groups.new('RPC · Alembic UV → 原材质 UV', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    inp, out = group.nodes.new('NodeGroupInput'), group.nodes.new('NodeGroupOutput')
    attr = group.nodes.new('GeometryNodeInputNamedAttribute')
    attr.data_type = 'FLOAT_VECTOR'
    attr.inputs['Name'].default_value = 'uv'
    store = group.nodes.new('GeometryNodeStoreNamedAttribute')
    store.data_type = 'FLOAT2'
    store.domain = 'CORNER'
    store.inputs['Name'].default_value = 'UVMap'
    group.links.new(inp.outputs['Geometry'], store.inputs['Geometry'])
    group.links.new(attr.outputs['Attribute'], store.inputs['Value'])
    group.links.new(store.outputs['Geometry'], out.inputs['Geometry'])
    return group


def set_camera(scene, qa):
    positions = qa['positions'].reshape(-1, 3)@C.T
    lo, hi = positions.min(0), positions.max(0)
    center = Vector(((lo+hi)*.5).tolist())
    aspect = scene.render.resolution_x/scene.render.resolution_y
    span = float(max(hi[2]-lo[2], (hi[0]-lo[0])/aspect)*1.18)
    camera = scene.camera
    camera.constraints.clear()
    camera.parent = None
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = span
    camera.location = center+Vector((0, -max(span*3, 5), 0))
    camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
    return {'policy': 'fixed inspection camera, union of seven sampled bounds; not source choreography camera',
            'sampled_bounds_m': [lo.tolist(), hi.tolist()]}


def build(template, abc, output, force_head_fit=False, verify_hash=True, output_fps=None, camera_warmup_seconds=0):
    from .paths import output_path
    output = output_path(output)
    template, abc = (Path(x).expanduser().resolve() for x in (template, abc))
    if not template.is_file() or not abc.is_file() or abc.suffix.lower() != '.abc':
        raise ValueError('请选择存在的材质模板 .blend 和动画 .abc。')
    if output.suffix.lower() != '.blend' or output.exists() or output.with_suffix('.report.json').exists():
        raise ValueError('输出必须是尚不存在的 .blend，已有文件不会覆盖。')
    if output.parent == abc.parent:
        raise ValueError('请使用独立输出目录，保留原 Alembic 交付目录。')
    folder = abc.parent
    for name in ['metadata.json', 'verification.npz', 'material_animation.npz']:
        if not (folder/name).is_file():
            raise ValueError('缺少缓存配套文件：'+name)
    meta = json.loads((folder/'metadata.json').read_text(encoding='utf8'))
    target_fps = float(output_fps or meta['fps'])
    if not math.isfinite(target_fps) or not 1 <= target_fps <= 240:
        raise ValueError('输出帧率必须为 1–240。')
    if not math.isfinite(camera_warmup_seconds) or not 0 <= camera_warmup_seconds <= 3600:
        raise ValueError('ABC 已含预热时间必须为 0–3600 秒。')
    print('RPC 1/6 验证缓存与输入', flush=True)
    if meta.get('schema_version') != 1 or meta.get('mesh_path') != '/character/mesh':
        raise ValueError('未校准的缓存结构，当前支持本项目 phase3 Alembic 交付。')
    if abc.stat().st_size != meta['alembic_bytes'] or (verify_hash and digest(abc) != meta['alembic_sha256']):
        raise ValueError('Alembic 文件大小或 SHA256 与元数据不符。')
    template_hash = digest(template)
    with np.load(folder/'verification.npz', allow_pickle=False) as a:
        qa = {k: a[k] for k in a.files}
    with np.load(folder/'material_animation.npz', allow_pickle=False) as a:
        if np.any(a['values'] != a['values'][0]) or not np.all(a['visible']):
            raise ValueError('缓存含动态材质或可见性；当前版本拒绝静默丢弃此类动画。')
    # Calibrated secondary UVs/rest-space fields are static. Reject UV morphs
    # until their authored data-space mapping has separately been calibrated.
    if np.max(abs(qa['uv']-qa['uv'][0])) > 1e-6:
        raise ValueError('抽样检测到 UV 动画，需单独校准控制图 UV 迁移。')
    bpy.ops.wm.open_mainfile(filepath=str(template), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    identity = scene.get('rpt_identity', scene.get('rpt_character'))
    if identity not in PROFILES or meta['input']['pmx_sha256'] != PROFILES[identity]:
        raise ValueError('材质模板与缓存的源角色指纹不匹配。')
    if scene.get('rpc_transfer'):
        raise ValueError('请选择静态着色模板，不能把已迁移结果再次作为模板。')
    obj = source_object(scene)
    if obj is None:
        raise ValueError('模板缺少角色网格。')
    mesh = obj.data
    faces = array(mesh.loops, 'vertex_index', dtype=np.int32).reshape(-1, 3)
    if len(mesh.vertices) != qa['positions'].shape[1] or not np.array_equal(faces, qa['faces']):
        raise ValueError('顶点或面顺序不匹配，不能按索引套用。')
    material_ids = array(mesh.polygons, 'material_index', dtype=np.int32)
    expected_ids = np.repeat(np.arange(len(qa['material_counts'])), qa['material_counts'])
    if not np.array_equal(material_ids, expected_ids) or len(mesh.materials) != len(meta['materials']):
        raise ValueError('材质分区不一致。')
    uv_error = float(np.max(abs(array(mesh.uv_layers['UVMap'].data, 'uv', 2)-qa['uv'][0][faces.ravel()])))
    if uv_error > 2e-6:
        raise ValueError(f'模板与缓存 UV 不一致：{uv_error}')
    ids, rest, bone_rest = head_anchors(obj)
    before_controls = controls(scene)
    members = [o for o in scene.objects if o.type == 'MESH' and o.data == mesh]
    source_attributes = [(a.name, a.domain, a.data_type) for a in mesh.attributes if not a.name.startswith('.')]
    print('RPC 2/6 读取 Alembic，保留材质与辅助效果', flush=True)
    before_objects = set(bpy.data.objects)
    bpy.ops.wm.alembic_import(filepath=str(abc), scale=1, set_frame_range=False, validate_meshes=False,
                             always_add_cache_reader=True, as_background_job=False)
    imported = list(set(bpy.data.objects)-before_objects)
    imported_meshes = [o for o in imported if o.type == 'MESH']
    if len(imported_meshes) != 1:
        raise ValueError('缓存必须包含一个角色网格。')
    cache_obj = imported_meshes[0]
    cache_obj.hide_render = True
    scene.render.fps = round(meta['fps'])
    scene.render.fps_base = round(meta['fps'])/meta['fps']
    scene.frame_start = round(meta['start_seconds']*meta['fps'])
    scene.frame_end = round(meta['end_seconds']*meta['fps'])
    reader = next(m for m in cache_obj.modifiers if m.type == 'MESH_SEQUENCE_CACHE')
    cache_file = reader.cache_file
    cache_file.filepath = str(abc)
    cache_file.frame_offset = 0
    cache_file.override_frame = False
    print('RPC 3/6 烘焙头部方向控制（不重算动作）', flush=True)
    matrices, frames, head_report = head_motion(meta, qa, ids, rest, bone_rest, cache_obj, scene, force_head_fit)
    scene.render.fps = round(target_fps)
    scene.render.fps_base = round(target_fps)/target_fps
    scene.frame_start = round(meta['start_seconds']*target_fps)
    scene.frame_end = round(meta['end_seconds']*target_fps)
    frames = frames * target_fps/meta['fps']
    head = bpy.data.objects.get('RPT_HeadFrame') or bpy.data.objects.get('ZZZ_HeadFrame')
    if head is None:
        raise ValueError('模板缺少头部方向控制物体。')
    bake_head(scene, head, matrices, frames)
    # Replace armature deformation, not the calibrated mesh or its shaders.
    # POLY is necessary even for identical topology: Blender's Alembic reader
    # otherwise uses the wrong corner order for UVs and custom normals.
    mesh.shape_keys and obj.shape_key_clear()
    bridge = uv_bridge()
    for member in members:
        world = member.matrix_world.copy()
        member.parent = None
        member.matrix_world = Matrix.Identity(4)
        for m in list(member.modifiers):
            if m.type in {'ARMATURE', 'MESH_SEQUENCE_CACHE'}:
                member.modifiers.remove(m)
        m = member.modifiers.new('RPC · Alembic 动作', 'MESH_SEQUENCE_CACHE')
        m.cache_file = cache_file
        m.object_path = reader.object_path
        m.read_data = {'VERT', 'POLY', 'UV'}
        member.modifiers.move(len(member.modifiers)-1, 0)
        m = member.modifiers.new('RPC · 动画 UV', 'NODES')
        m.node_group = bridge
        member.modifiers.move(len(member.modifiers)-1, 1)
    # Keep absolute dimensions from the cache. Scale only scene-unit outline
    # width so the visual proportion matches the original .08-scale template.
    r = registry(scene)
    global_node = bpy.data.materials[r['global']['material']].node_tree.nodes[r['global']['node']]
    width = next((s for s in global_node.inputs if '描边厚度' in s.name), None)
    if width:
        width.default_value *= head_report['source_to_cache_scale']
    print('RPC 4/6 校验几何、UV、材质与辅助网格', flush=True)
    # A temporary unfiltered reader validates the original mesh before the
    # deliberately topology-changing outline/bangs modifiers run.
    probe = obj.copy()
    probe.data = mesh
    scene.collection.objects.link(probe)
    for m in list(probe.modifiers)[2:]:
        probe.modifiers.remove(m)
    probe.constraints.clear()
    probe.hide_render = True
    checks = []
    for i, time in enumerate(qa['times']):
        frame = float(time*target_fps)
        scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
        dg = bpy.context.evaluated_depsgraph_get()
        ev = probe.evaluated_get(dg)
        me = ev.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
        try:
            error = float(np.max(abs(array(me.vertices, 'co', 3)-qa['positions'][i]@C.T)))
            uv = array(me.uv_layers['UVMap'].data, 'uv', 2)
            uv_error_frame = float(np.max(abs(uv-qa['uv'][i][faces.ravel()])))
            normal = array(me.corner_normals, 'vector', 3)
            normal_error = float(np.max(np.linalg.norm(normal-qa['normals'][i][faces.ravel()]@C.T, axis=1)))
            raw = cache_obj.evaluated_get(dg)
            raw_mesh = raw.to_mesh()
            imported_normal_error = float(np.max(np.linalg.norm(normal-array(raw_mesh.corner_normals, 'vector', 3), axis=1)))
            raw.to_mesh_clear()
            attrs_ok = all(me.attributes.get(n) is not None for n, _, _ in source_attributes)
            parts_ok = np.array_equal(array(me.polygons, 'material_index', dtype=np.int32), material_ids)
            topology_ok = np.array_equal(array(me.loops, 'vertex_index', dtype=np.int32), faces.ravel())
            check = dict(frame=frame, max_position_error_m=error, max_uv_error=uv_error_frame,
                         max_normal_vector_error=normal_error, normal_difference_from_direct_import=imported_normal_error,
                         attributes_present=attrs_ok, parts_preserved=bool(parts_ok),
                         topology_preserved=bool(topology_ok))
            check['passed'] = bool(error < 2e-6 and uv_error_frame < 2e-6 and imported_normal_error < 2e-6 and attrs_ok and parts_ok and topology_ok)
            checks.append(check)
        finally:
            ev.to_mesh_clear()
    bpy.data.objects.remove(probe, do_unlink=True)
    for ob in imported:
        bpy.data.objects.remove(ob, do_unlink=True)
    if not all(c['passed'] for c in checks):
        raise ValueError('迁移后的几何校验失败：'+str(checks))
    camera_report = set_camera(scene, qa)
    scene.frame_set(scene.frame_start)
    scene.render.engine = 'BLENDER_EEVEE'
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    after_controls = controls(scene)
    changes = [(m, k, v, after_controls[m][k]) for m, values in before_controls.items() for k, v in values.items() if v != after_controls[m][k]]
    if any('描边厚度' not in k for _, k, _, _ in changes):
        raise ValueError('非预期的材质参数变化。')
    report = dict(status='success', version=VERSION, character=identity, template=str(template), template_sha256=template_hash,
                  alembic=str(abc), alembic_sha256=meta['alembic_sha256'], hash_verified=bool(verify_hash),
                  output=str(output), frame_range=[scene.frame_start, scene.frame_end], fps=target_fps,
                  source_fps=meta['fps'], meters_per_pmx_unit=meta['meters_per_pmx_unit'], head_object=head.name,
                  camera_warmup_seconds=camera_warmup_seconds,
                  source_pmx_sha256=meta['input']['pmx_sha256'], head=head_report, camera=camera_report,
                  surfaces=[o.name for o in members], original_attributes=source_attributes,
                  sample_checks=checks, parameter_changes=changes, source_quality=meta.get('source_quality'),
                  limitations=['Existing physics review flags remain; physics is not recomputed.',
                               'Blender archive-normal decoding deviations are measured, not claimed repaired.',
                               'Fixed inspection camera covers sampled bounds, not guaranteed all-frame framing.',
                               'Only calibrated constant-topology phase3 caches of Vivian and SunnaMaid are accepted.',
                               'Material animation is rejected; UV animation is checked at supplied verification samples.'])
    scene['rpc_transfer'] = json.dumps(report, ensure_ascii=False)
    text = bpy.data.texts.get('02_ABC渲染套用报告') or bpy.data.texts.new('02_ABC渲染套用报告')
    text.clear()
    text.write(json.dumps(report, ensure_ascii=False, indent=2))
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'SOLID'
                area.spaces.active.shading.use_compositor = 'DISABLED'
    print('RPC 5/6 打包贴图与保存新场景', flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output.parent/'render.png')
    trees, images = set(), set()
    def collect_images(tree):
        if tree is None or tree in trees:
            return
        trees.add(tree)
        for node in tree.nodes:
            if getattr(node, 'image', None):
                images.add(node.image)
            collect_images(getattr(node, 'node_tree', None))
    for member in members:
        for slot in member.material_slots:
            if slot.material:
                collect_images(slot.material.node_tree)
    collect_images(scene.world.node_tree if scene.world else None)
    collect_images(scene.compositing_node_group)
    for image in images:
        if image.source == 'FILE' and not image.packed_file:
            if not Path(bpy.path.abspath(image.filepath)).is_file():
                raise ValueError('渲染使用的贴图缺失：'+image.name)
            image.pack()
    report['render_images_packed'] = len(images)
    scene['rpc_transfer'] = json.dumps(report, ensure_ascii=False)
    text.clear()
    text.write(json.dumps(report, ensure_ascii=False, indent=2))
    # ABC remains external; no 28 GiB duplication. Saved controls need no NPZ.
    cache_file.filepath = str(abc)
    saved = bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True)
    if 'FINISHED' not in saved or Path(bpy.data.filepath).resolve() != output or not output.is_file():
        raise RuntimeError('Blender 实际保存路径与请求不一致，未报告成功：'+bpy.data.filepath)
    if digest(template) != template_hash:
        raise RuntimeError('源模板意外变化。')
    output.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('RPC 6/6 COMPLETE', str(output), flush=True)
    return report
