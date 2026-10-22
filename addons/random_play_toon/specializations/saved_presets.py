"""Fingerprint-bound defaults, applied only while constructing a new scene.

The existing JSON import remains the explicit way to apply another saved style.
No registration or file-load handler applies these defaults to an open project.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).with_name('presets')


def catalog():
    return json.loads((ROOT / 'catalog.json').read_text(encoding='utf8'))['characters']


def find(fingerprint):
    return next((item for item in catalog() if item['pmx_sha256'] == fingerprint), None)


def identify(profile):
    item = find(profile['pmx_sha256'])
    if item:
        actual = [(m['index'], m['name']) for m in profile['materials']]
        expected = [(m['slot'], m['name']) for m in item['materials']]
        if profile['id'] != item['identity'] or actual != expected:
            raise ValueError('角色预设与模型材质分区不匹配')
        profile['automatic_preset'] = item['character']
        profile['character'] = item['character']
    return profile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_inputs(profile, inputs, asset_root):
    """Keep the saved PMX-only shader; restore only the reviewed extra masks."""
    item = find(profile['pmx_sha256'])
    resolved = {}
    if asset_root:
        base = Path(asset_root).resolve()
        roots = [base, base / item['character'], base / 'PlayerCharacterData' / item['character'],
                 base / 'render_library/PlayerCharacterData' / item['character']]
        for binding in item['highlight_bindings']:
            slot = str(binding['index'])
            source = inputs['textures'].get(slot)
            source_hash = binding['source_asset_evidence']['source_sha256']
            if not source or digest(source) != source_hash:
                continue
            image = binding['maps']['LightMap']
            path = next((p / image['file'] for p in roots
                         if (p / image['file']).is_file() and digest(p / image['file']) == image['sha256']), None)
            if path:
                resolved[slot] = str(path)
    inputs['saved_preset_assets'] = resolved
    missing = [b['index'] for b in item['highlight_bindings'] if str(b['index']) not in resolved]
    if missing:
        inputs['warnings'].append({'reason': 'saved_preset_optional_maps_missing', 'slots': missing,
            'action': '角色默认参数仍会自动加载；选择对应渲染素材目录可恢复配套高光和材质细节。'})


def apply_face_details(s):
    """Add working face brightness and feature controls to generic materials.
    Keep each character's calibrated direction field. No Vivian-specific UVs.
    """
    from .. import style_panel as ui
    from ..materials import feature_extension, nose_shadow
    from ..materials.style_upgrade import add, source, Graph, output
    if s.get('transfer_face_adapter'): return
    r=ui.registry(s);g=r['global'];old=ui.capture(s)
    feature_extension.stabilize_control_paths(r)
    for key,label,value,lo,hi in [
        ('Face Key Follow Global','脸部受光亮度跟随全局',True,0,1),
        ('Face Key Gain','脸部角色受光亮度',1.,0,3),
        ('Face Display Follow Global','脸部亮面亮度跟随全局',True,0,1),
        ('Face Display Light','脸部展示亮面亮度',1.12,.5,2)]:
        add(g,key,label,value,lo,hi,'02 脸部独立亮度','参考风格迁移：仅脸部基础受光，不影响亮块和眼睛自发光。')
    for e in r['materials']:
        if e['role']!='face':continue
        n=ui.node(e);t=n.id_data;q=Graph(t);toon=t.nodes['共享 EEVEE 卡通着色']
        selected=q.mix(output(q,g,'Face Key Gain'),output(q,g,'Key Gain'),output(q,g,'Face Key Follow Global'),'Transfer face gain selection')
        q.put(q.math('MULTIPLY',selected,n.outputs['Local Gain']),toon.inputs['Key Gain'])
        old_display=next(x for x in t.nodes if x.name=='全局 · Display Light').outputs[0]
        targets=[l.to_socket for l in old_display.links]
        selected=q.mix(output(q,g,'Face Display Light'),old_display,output(q,g,'Face Display Follow Global'),'Transfer face display selection')
        for target in targets:q.put(selected,target)
        for key,label,value in [('Face Nose','脸部 · 鼻部阴影',.065),('Face Chin','脸部 · 下颌阴影',.14)]:
            add(e,key,label,value,0,1,'02 脸部特征','使用本角色归一化静止坐标估计局部特征范围，保留参考强度。')
        att=q.node('ShaderNodeAttribute','Transfer normalized face features');att.attribute_name=nose_shadow.ATTRIBUTE
        sep=q.node('ShaderNodeSeparateXYZ','Transfer face feature coordinates');q.put(q.vec('SUBTRACT',att.outputs['Vector'],(2,0,0)),sep.inputs[0])
        xx=q.math('POWER',q.math('DIVIDE',sep.outputs['X'],.065),2)
        zz=q.math('POWER',q.math('DIVIDE',sep.outputs['Z'],.078),2)
        nose=q.math('EXPONENT',q.math('MULTIPLY',q.math('ADD',xx,zz),-1))
        chin=q.math('SUBTRACT',1,q.smooth(sep.outputs['Z'],-.31,-.14))
        direction=t.nodes['Independent light / head pose']
        lateral=q.math('ABSOLUTE',q.vec('DOT_PRODUCT',direction.outputs['Light Direction'],direction.outputs['Head Right']))
        overhead=q.math('MAXIMUM',q.vec('DOT_PRODUCT',direction.outputs['Light Direction'],direction.outputs['Head Up']),0)
        extra=q.math('ADD',q.math('MULTIPLY',nose,q.math('MULTIPLY',lateral,n.outputs['Face Nose'])),q.math('MULTIPLY',chin,q.math('MULTIPLY',overhead,n.outputs['Face Chin'])))
        q.put(q.math('ADD',source(toon.inputs['Threshold']),extra,'Transfer face feature threshold'),toon.inputs['Threshold'])
    s['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    defaults=ui.capture(s)
    for mat,v in old.items():defaults[mat].update(v)
    s['zzz_stage6_defaults']=json.dumps(defaults,ensure_ascii=False)
    s['transfer_face_adapter']='Generic calibrated field + normalized nose/chin masks; independent face gain and display controls.'


def apply_material_details(scene, profile, inputs):
    from .. import style_panel as ui
    from ..materials.source_asset_match import bind_authored_highlight
    from ..materials.swim_material_repairs import apply as repair_swimsuit, IDENTITY
    import bpy
    apply_face_details(scene)
    item = find(profile['pmx_sha256'])
    entries = {e['slot']: e for e in ui.registry(scene)['materials']}
    actions = []
    assets = inputs['saved_preset_assets']
    for binding in item['highlight_bindings']:
        path = assets.get(str(binding['index']))
        if not path:
            continue
        extra = {'material_class': binding['material_class']} if binding.get('material_class') else {}
        actions.append(bind_authored_highlight(scene, entries[binding['index']], binding,
                       Path(path).parent, lightmap_path=path, **extra))
    if profile['id'] == IDENTITY:
        path = assets.get('14')
        actions.append(repair_swimsuit(scene, Path(path).parent if path else None))
    for slot in item.get('outline_dithered_slots', []):
        bpy.data.materials['RPT_Outline_' + str(slot)].surface_render_method = 'DITHERED'
    # Preserve the current project's other transparent outlines. The two repaired
    # cap/ribbon slots above retain their reviewed depth-tested surface mode.
    for slot in item.get('outline_blended_slots', []):
        bpy.data.materials['RPT_Outline_' + str(slot)].surface_render_method = 'BLENDED'
    return actions


def assign(block, values):
    """Data is shipped with this package and limited to writable RNA properties."""
    for name, value in values.items():
        prop = block.bl_rna.properties.get(name)
        if prop is None or prop.is_readonly:
            raise ValueError('预设场景属性不可写：' + name)
        setattr(block, name, value)


def apply_scene_setup(scene, data):
    import bpy
    from mathutils import Matrix
    # This function is called only in the isolated fresh-construction worker.
    for obj in list(scene.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    for spec in data['lights']:
        light = bpy.data.lights.new(spec['name'], spec['type'])
        assign(light, spec['data'])
        obj = bpy.data.objects.new(spec['name'], light)
        scene.collection.objects.link(obj)
        obj.matrix_world = Matrix(spec['matrix_world'])
        assign(obj, spec.get('object', {}))
    world = data['world']
    scene.world.use_nodes = True
    assign(scene.world, world.get('properties', {}))
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = world['color']
    background.inputs['Strength'].default_value = world['strength']
    camera = data['camera']
    assign(scene.camera.data, camera['data'])
    assign(scene.camera.data.dof, camera.get('dof', {}))
    scene.camera.matrix_world = Matrix(camera['matrix_world'])
    assign(scene.camera, camera.get('object', {}))
    for key in ['render', 'eevee', 'view_settings', 'display_settings']:
        assign(getattr(scene, key), data[key])
    assign(scene.render.image_settings, data['image_settings'])
    scene.frame_set(data['frame'])


def apply_defaults(scene, profile, style='CURRENT'):
    from .. import style_panel as ui
    item = find(profile['pmx_sha256'])
    name = item['default_style'] if style == 'CURRENT' else style
    if name not in item['styles']:
        raise ValueError('该角色没有此预设：' + name)
    entry = item['styles'][name]
    values = json.loads((ROOT / entry['values']).read_text(encoding='utf8'))['values']
    setup = json.loads((ROOT / entry['scene_setup']).read_text(encoding='utf8'))
    ui.apply_values(scene, values)
    apply_scene_setup(scene, setup)
    # Reset returns to the shipped character style, before personal overrides.
    scene['zzz_stage6_defaults'] = json.dumps(values, ensure_ascii=False)
    record = {'character': item['character'], 'style': name, 'pmx_sha256': item['pmx_sha256'],
              'scope': 'fresh build only', 'personal_overrides_applied_after_default': True}
    scene['rpt_automatic_preset'] = json.dumps(record, ensure_ascii=False)
    return record
