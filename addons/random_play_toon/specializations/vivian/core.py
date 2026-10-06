"""Exact Vivian reconstruction in an isolated Blender worker (native EEVEE)."""
from pathlib import Path
import hashlib,json,os,time
import bpy
import numpy as np
from ...pmx_import import import_model,prepare_import

RES=Path(__file__).parent/'resources'
PRESETS=('CURRENT','BASELINE','DISPLAY','SOFT','CONTRAST','NIGHT')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_profile():return json.loads((RES/'profile.json').read_text(encoding='utf8'))

def preflight(pmx,texture_root,asset_root,preset='CURRENT'):
    if bpy.app.version[:2]!=(5,2):raise ValueError('本次精确重建仅验证 Blender 5.2；请使用 Blender 5.2.1 LTS。')
    profile=read_profile();pmx=Path(pmx).expanduser().resolve()
    textures=Path(texture_root).expanduser().resolve() if texture_root else pmx.parent
    assets=Path(asset_root).expanduser().resolve()
    errors=[];warnings=[];resolved={}
    if preset not in PRESETS:errors.append('未知风格：'+preset)
    if not pmx.is_file() or digest(pmx)!=profile['pmx_sha256']:
        errors.append('本轮仅支持已验证的普通版薇薇安原始 PMX（文件可改名或移动）；所选模型缺失或内容不同。')
    manifest=json.loads((RES/'manifest.json').read_text(encoding='utf8'))
    for relative,expected in manifest.items():
        p=RES/relative
        if not p.is_file() or digest(p)!=expected:errors.append('插件资源校验失败：'+relative)
    for image in profile['images']:
        kind=image['kind'];rel=image['relative']
        if kind=='optional_missing':
            warnings.append('保留原始材质的非渲染依赖缺失：'+rel);continue
        if kind=='derived':candidates=[RES/rel]
        elif kind=='pmx':candidates=[textures/rel]
        else:candidates=[assets/rel,assets/'Vivian'/rel,assets/'PlayerCharacterData/Vivian'/rel]
        matching=[p for p in candidates if p.is_file() and digest(p)==image['sha256']]
        if not matching:
            existing=[str(p) for p in candidates if p.is_file()]
            errors.append(('贴图内容与 0.6.9 校准基准不同：' if existing else '缺少贴图：')+rel)
        else:resolved[image['name']]=str(matching[0])
    if errors:raise ValueError('\n'.join(dict.fromkeys(errors)))
    return profile,{'pmx':str(pmx),'texture_root':str(textures),'asset_root':str(assets),'images':resolved,'warnings':list(dict.fromkeys(warnings))}

def mesh_snapshot(o):
    me=o.data
    def h(a):return hashlib.sha256(np.asarray(a,dtype=np.float32).tobytes()).hexdigest()
    return {'positions':h([v.co[:] for v in me.vertices]),'loops':[l.vertex_index for l in me.loops],
        'parts':[p.material_index for p in me.polygons],
        'uvs':{u.name:h([v.uv[:] for v in u.data]) for u in me.uv_layers},
        'shapes':{k.name:h([v.co[:] for v in k.data]) for k in me.shape_keys.key_blocks} if me.shape_keys else {},
        'groups':[g.name for g in o.vertex_groups],
        'weights':hashlib.sha256(json.dumps([[(g.group,g.weight) for g in v.groups] for v in me.vertices]).encode()).hexdigest()}

def progress(stage):print('RANDOMPLAY '+stage,flush=True)

def build(pmx,texture_root,asset_root,output,preset='CURRENT',personal_preset=None):
    if not bpy.app.background:raise RuntimeError('构建器必须运行在独立后台进程中，以保护当前场景。')
    start=time.time();output=Path(output).resolve()
    if output.suffix.lower()!='.blend':raise ValueError('输出文件必须为 .blend')
    if output.exists():raise ValueError('输出文件已存在；请选择新文件名，已有成果不会被覆盖。')
    if output.is_relative_to(RES):raise ValueError('不能覆盖插件资源。')
    progress('1/7 校验输入和 0.6.9 资源')
    profile,inputs=preflight(pmx,texture_root,asset_root,preset)
    output.parent.mkdir(parents=True,exist_ok=True)
    prepare_import()
    bpy.ops.wm.open_mainfile(filepath=str(RES/'library.blend'))
    scene=bpy.context.scene
    scene['rpt_character']='Vivian';scene['rpt_identity']='Vivian';scene['zzz_stage6_schema']=2
    if any(len(m.vertices) for m in bpy.data.meshes) or any(len(a.bones) for a in bpy.data.armatures):
        raise RuntimeError('节点库意外包含模型数据，拒绝以旧模型代替 PMX 导入。')
    old=bpy.data.objects[profile['mesh_object']];old_arm=bpy.data.objects[profile['armature_object']];old_root=bpy.data.objects[profile['root_object']]
    template=old.data;materials=list(template.materials)
    original_objects=set(bpy.data.objects)
    progress('2/7 从所选 PMX 导入网格、骨骼和表情')
    import_model(inputs['pmx'],profile['import_scale'])
    imported=[o for o in bpy.data.objects if o not in original_objects]
    meshes=[o for o in imported if o.type=='MESH']
    if len(meshes)!=1:raise ValueError('预期薇薇安主体为一个网格，实际导入结果不同。')
    fresh=meshes[0];rig=fresh.find_armature();root=rig.parent
    snap=mesh_snapshot(fresh);expected=profile['source_snapshot']
    for key in ['positions','loops','parts','shapes','groups','weights']:
        if snap[key]!=expected[key]:raise ValueError('导入数据与校准基准不一致：'+key)
    for key,val in snap['uvs'].items():
        if expected['uvs'].get(key)!=val:raise ValueError('原始 UV 与校准基准不一致：'+key)
    progress('3/7 恢复已验证的校准属性、材质和绑定')
    # Fresh geometry, weights and shape keys are retained; only calibrated attributes are added.
    mesh=fresh.data;original_materials=list(mesh.materials)
    for m in original_materials:m.use_fake_user=True
    with np.load(RES/'calibration.npz',allow_pickle=False) as arrays:
        for entry in profile['attributes']:
            attr=mesh.attributes.get(entry['name']) or mesh.attributes.new(entry['name'],entry['type'],entry['domain'])
            attr.data.foreach_set(entry['field'],arrays[entry['array']])
    mesh.uv_layers.active=mesh.uv_layers['UVMap'];mesh.uv_layers['UVMap'].active_render=True
    mesh.materials.clear()
    for m in materials:mesh.materials.append(m)
    mesh.polygons.foreach_set('material_index',np.asarray(expected['parts'],dtype=np.int32))
    for obj in original_objects:
        if obj.type=='MESH' and obj.data==template:
            obj.data=mesh
            if [g.name for g in obj.vertex_groups]!=profile['vertex_groups']:
                obj.vertex_groups.clear()
                for name in profile['vertex_groups']:obj.vertex_groups.new(name=name)
    bpy.data.objects.remove(fresh,do_unlink=True)
    # Replace rig/root stubs globally, including constraints and driver variable targets.
    for stub,new in [(old_root,root),(old_arm,rig)]:
        name=stub.name;cols=list(stub.users_collection)
        matrix=stub.matrix_world.copy();hidden=stub.hide_render
        stub.user_remap(new)
        bpy.data.objects.remove(stub,do_unlink=True);new.name=name
        for col in list(new.users_collection):col.objects.unlink(new)
        for col in cols:col.objects.link(new)
        new.matrix_world=matrix;new.hide_render=hidden
    rig.data.pose_position=profile['armature_pose_position']
    for name,values in profile['pose'].items():
        pb=rig.pose.bones.get(name)
        if pb is None:raise ValueError('缺少骨骼：'+name)
        for key,value in values.items():setattr(pb,key,value)
    for m in list(bpy.data.meshes):
        if m.users==0:bpy.data.meshes.remove(m)
    for a in list(bpy.data.armatures):
        if a.users==0:bpy.data.armatures.remove(a)
    progress('4/7 绑定本次纹理和渲染素材')
    # Preserve the imported original materials even when their texture root is separate.
    for image in bpy.data.images:
        if image.name in inputs['images'] or image.source!='FILE':continue
        source_path=Path(bpy.path.abspath(image.filepath)).resolve()
        try:relative=source_path.relative_to(Path(inputs['pmx']).parent)
        except ValueError:continue
        candidate=Path(inputs['texture_root'])/relative
        if candidate.is_file():image.filepath=str(candidate);image.reload()
    for entry in profile['images']:
        image=bpy.data.images.get(entry['name'])
        if entry['kind']=='optional_missing':continue
        if not image:raise RuntimeError('库缺少图像入口：'+entry['name'])
        image.filepath=inputs['images'][entry['name']];image.reload()
        image.colorspace_settings.name=entry['colorspace'];image.alpha_mode=entry['alpha_mode']
        if not image.size[0]:raise RuntimeError('图像无法解码：'+image.filepath)
    progress('5/7 恢复侧边栏、预设、透眼合成和轻量视图')
    from ... import style_panel as ui
    ui.register()
    from ...materials.light_color import apply as add_light_color
    add_light_color(scene)
    from ...materials.feature_extension import apply as add_feature_extension
    add_feature_extension(scene)
    if preset!='CURRENT':ui.apply_values(scene,ui.make_preset(scene,preset))
    if personal_preset is not None:ui.apply_values(scene,personal_preset)
    ui.lightweight_viewports();ui.refresh(scene)
    scene['zzz_stage7_library']=False;scene['zzz_stage7_profile']=profile['profile']
    scene['zzz_stage7_inputs']=json.dumps({k:v for k,v in inputs.items() if k!='images'},ensure_ascii=False)
    scene['zzz_stage7_version']='0.9.3';scene['zzz_stage7_baseline']='0.6.9'
    report={'status':'success','profile':profile['profile'],'baseline_version':'0.6.9','plugin':'RandomPlayToon','plugin_version':'0.9.3',
      'blender':bpy.app.version_string,'inputs':inputs,'preset':preset,'checks':{},'output':str(output)}
    checks=report['checks'];actual=mesh_snapshot(old)
    for key in ['positions','loops','parts','shapes','groups','weights']:checks['fresh_pmx_'+key]=actual[key]==expected[key]
    checks['all_uvs']=actual['uvs']==expected['uvs']
    checks['shared_eye_mesh']=bpy.data.objects['ZZZ_EyeReveal_Body'].data==old.data
    checks['source_rig']=old.find_armature()==rig
    checks['eevee']=scene.render.engine=='BLENDER_EEVEE'
    checks['panel_current']=ui.bl_info['version']==(0,9,3)
    checks['eye_layers']=all(n in scene.view_layers for n in ['ZZZ_Beauty','ZZZ_EyeVisibility'])
    progress('6/7 检查数据、打包资源')
    if not all(checks.values()):raise RuntimeError('构建后检查失败：'+str(checks))
    for image in bpy.data.images:
        if image.source=='FILE' and image.size[0] and Path(bpy.path.abspath(image.filepath)).is_file():
            image.pack();image.filepath='//textures/'+Path(image.filepath).name
    # Missing legacy toon remains a documented non-render dependency, not a fabricated image.
    for entry in profile['images']:
        if entry['kind']=='optional_missing':bpy.data.images[entry['name']].filepath='//missing_legacy/'+entry['relative']
    for text in bpy.data.texts:
        if text.name=='01_启用风格面板':text.clear();text.write((Path(__file__).parents[2]/'style_panel.py').read_text(encoding='utf8'))
    from ...portable import embed_panel
    embed_panel()
    readme=bpy.data.texts.get('00_第七步使用说明') or bpy.data.texts.new('00_第七步使用说明')
    readme.clear();readme.write('薇薇安一键重建 / 0.6.9 视觉基准\n从用户选择的 PMX 重新导入。侧栏 Vivian > 角色风格；方向箭头 + F12。\n生成数据已打包。局部透眼依赖最终合成。\n无插件时可在文本编辑器运行 01_启用风格面板。\n')
    for obj in bpy.context.selected_objects:obj.select_set(False)
    old.hide_set(False);old.select_set(True);bpy.context.view_layer.objects.active=old
    output.parent.mkdir(parents=True,exist_ok=True)
    report['elapsed_seconds']=round(time.time()-start,3)
    scene['zzz_stage7_report']=json.dumps(report,ensure_ascii=False)
    import uuid
    temp=output.with_name(output.stem+'.building_'+uuid.uuid4().hex+'.blend')
    progress('7/7 保存独立结果')
    scene.render.resolution_x*=2;scene.render.resolution_y*=2
    bpy.ops.wm.save_as_mainfile(filepath=str(temp),compress=True)
    os.replace(temp,output)
    output.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    progress('完成 '+str(output));return report
