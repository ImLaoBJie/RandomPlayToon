"""Single-input dispatcher. Known fingerprints use explicit auditable profiles."""
from pathlib import Path
import hashlib,json,time,os,uuid
PROFILES=Path(__file__).parent/'specializations/profiles'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def identify(pmx):
    p=Path(pmx).expanduser().resolve()
    if not p.is_file():raise ValueError('所选 PMX 不存在')
    fingerprint=sha(p);catalog=json.loads((PROFILES/'catalog.json').read_text(encoding='utf8'))
    matches=[x for x in catalog if x['pmx_sha256']==fingerprint]
    if not matches:raise ValueError('所选 PMX 尚无校准配置；不会按相似文件名强行套用其他角色。')
    profile=json.loads((PROFILES/(matches[0]['id']+'.json')).read_text(encoding='utf8'))
    overrides=json.loads((PROFILES.parent/'parameter_overrides.json').read_text(encoding='utf8'))['models'].get(profile['id'],{})
    profile['parameter_overrides']=overrides.get('materials',{});profile['override_reason']=overrides.get('reason','')
    profile['warnings'].extend(overrides.get('warnings',[]))
    profile['zero_alpha_filter']=overrides.get('zero_alpha_filter',False)
    return profile

def preflight(pmx,texture_root,asset_root,preset='CURRENT'):
    import bpy
    if bpy.app.version[:2]!=(5,2):raise ValueError('当前构建已验证 Blender 5.2；请使用相同版本。')
    profile=identify(pmx)
    if profile['id']=='Vivian':
        from .specializations.vivian.core import preflight as exact
        return exact(pmx,texture_root,asset_root,preset)
    pmx=Path(pmx).resolve();root=Path(texture_root).resolve() if texture_root else pmx.parent;assets=Path(asset_root).resolve();character=profile['character']
    roots=[assets,assets/character,assets/'PlayerCharacterData'/character,assets/'render_library/PlayerCharacterData'/character]
    inputs={'pmx':str(pmx),'textures':{},'maps':{},'warnings':list(profile['warnings'])};errors=[]
    for m in profile['materials']:
        idx=str(m['index']);source=m.get('source_texture')
        if source:
            p=(root/source.replace('\\','/')).resolve()
            if not p.is_relative_to(root):errors.append('贴图路径超出所选目录：'+source)
            elif not p.is_file():
                if m.get('source_sha256'):errors.append('缺少 PMX 贴图：'+source)
                else:inputs['warnings'].append({'material':m['index'],'name':m['name'],'reason':'原资产已缺图：'+source,'action':'保留 PMX 材质底色；需用户补充原图后重新校准'})
            elif m.get('source_sha256') and sha(p)!=m['source_sha256']:errors.append('PMX 贴图已变化，需重新校准：'+source)
            else:inputs['textures'][idx]=str(p)
        inputs['maps'][idx]={}
        for kind,item in m['maps'].items():
            matches=[r/item['file'] for r in roots if (r/item['file']).is_file() and sha(r/item['file'])==item['sha256']]
            if not matches:errors.append('缺少或内容变化的已配对素材：'+item['file'])
            else:inputs['maps'][idx][kind]=str(matches[0])
    if errors:raise ValueError('\n'.join(dict.fromkeys(errors)))
    return profile,inputs

def build(pmx,texture_root,asset_root,output,preset='CURRENT',personal_preset=None):
    import bpy
    from mathutils import Vector
    from .specializations.vivian.core import mesh_snapshot
    from .pmx_import import import_model
    from .materials import controls
    from .materials.build import build as materials
    from .effects import layers
    from . import style_panel as ui
    if not bpy.app.background:raise RuntimeError('构建仅在独立后台进程运行')
    dest=Path(output).resolve()
    if dest.exists():raise ValueError('输出已存在，请选择新文件名')
    if dest.suffix.lower()!='.blend':raise ValueError('输出必须是 .blend')
    start=time.time();profile,inputs=preflight(pmx,texture_root,asset_root,preset)
    if identify(pmx)['id']=='Vivian':
        from .specializations.vivian.core import build as exact
        return exact(pmx,texture_root,asset_root,output,preset,personal_preset)
    dest.parent.mkdir(parents=True,exist_ok=True)
    print('RANDOMPLAY 1/6 导入 '+profile['id'],flush=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    import_model(pmx,profile['import_scale'])
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if len(meshes)!=1:raise ValueError('预期单 PMX 主网格，导入结构与校准配置不符')
    obj=meshes[0];obj.name=profile['id']+'_Model';snapshot=mesh_snapshot(obj);scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE'
    if len(obj.data.materials)!=len(profile['materials']):raise ValueError('材质分区数量不符')
    print('RANDOMPLAY 2/6 生成本模型脸部场、刘海域和重复覆盖层证据',flush=True);effects=layers.authored_attributes(obj,profile)
    registry,directions=controls.initialize(scene,obj,profile)
    print('RANDOMPLAY 3/6 配对控制图并构建共享材质',flush=True);materials(obj,profile,inputs,registry,directions)
    if profile.get('zero_alpha_filter'):
        layers.filter_zero_opacity(obj,registry);effects['inactive_surface_filter']='per-material opacity < 0.0001; source mesh preserved'
    print('RANDOMPLAY 4/6 描边、局部透眼与辉光',flush=True);shell=layers.outline(scene,obj,registry);eye_enabled=bool(profile['capabilities']['eyes'] and effects['bang_faces'])
    layers.setup_layers(scene,obj,shell,eye_enabled);layers.compositor(scene,registry,eye_enabled)
    scene['zzz_stage6_schema']=2;scene['zzz_stage6_registry']=json.dumps(registry,ensure_ascii=False);scene['rpt_character']=profile['character'];scene['rpt_identity']=profile['id'];scene['rpt_profile_schema']=1
    scene['zzz_stage6_defaults']=json.dumps(ui.capture(scene),ensure_ascii=False);ui.register();ui.lightweight_viewports()
    from .specializations.surface_refinement import apply as refine_surface
    refine_surface(scene,profile['id'])
    from .materials.vivian_parity import apply as align_vivian
    align_vivian(scene,profile['id'])
    from .materials.detail_review import apply as refine_details
    refine_details(scene,profile['id'])
    from .specializations.character_refinement import apply as refine_character
    character_refinement=refine_character(scene,profile['id'])
    from .materials.light_color import apply as add_light_color
    add_light_color(scene)
    from .materials.feature_extension import apply as add_feature_extension
    add_feature_extension(scene)
    if personal_preset:ui.apply_values(scene,personal_preset)
    # A complete camera and neutral backdrop are part of one-click reconstruction.
    coords=[obj.matrix_world@v.co for v in obj.data.vertices];lo=Vector(tuple(min(v[i] for v in coords) for i in range(3)));hi=Vector(tuple(max(v[i] for v in coords) for i in range(3)));center=(lo+hi)*.5
    cam=bpy.data.objects.new('RPT Camera',bpy.data.cameras.new('RPT Camera'));scene.collection.objects.link(cam);cam.data.type='ORTHO';height=max(hi.z-lo.z,(hi.x-lo.x)/.8,0.1);cam.data.ortho_scale=height*1.16;cam.location=center+Vector((0,-height*3,height*.12));cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();scene.camera=cam
    scene.render.resolution_x=1280;scene.render.resolution_y=1600;scene.render.resolution_percentage=100;scene.eevee.taa_render_samples=64;scene.render.film_transparent=True
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.world=bpy.data.worlds.new('RPT Neutral world');scene.world.use_nodes=True;scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.13,.13,.13,1)
    light=bpy.data.objects.new('RPT Scene sun',bpy.data.lights.new('RPT Scene sun','SUN'));scene.collection.objects.link(light);light.data.energy=1.6;light.rotation_euler=bpy.data.objects[registry['controller']].rotation_euler
    print('RANDOMPLAY 5/6 验证源数据保留并打包',flush=True)
    # Only material datablocks + added attributes/modifiers may differ.
    after=mesh_snapshot(obj);preserved={k:snapshot[k]==after[k] for k in snapshot}
    if not all(preserved.values()):raise RuntimeError('源模型数据意外改变：'+str(preserved))
    for im in bpy.data.images:
        if im.source=='FILE' and Path(bpy.path.abspath(im.filepath)).is_file():im.pack()
    report={'status':'success','output':str(dest),'plugin':'RandomPlayToon','version':'0.9.3','profile':profile['id'],'character':profile['character'],'kind':profile['kind'],'source_preserved':preserved,'materials':[{k:m.get(k) for k in ['index','name','role','matching','atlas','maps']} for m in profile['materials']],'effects':effects,'eye_reveal':eye_enabled,'warnings':inputs['warnings'],'validation':'rebuilt; visual acceptance recorded separately','elapsed_seconds':round(time.time()-start,2)}
    report['parameter_overrides']=profile.get('parameter_overrides',{});report['override_reason']=profile.get('override_reason','')
    report['detail_repairs']=json.loads(scene['rpt_detail_audit']);report['resolution']=[scene.render.resolution_x,scene.render.resolution_y]
    if character_refinement:report['character_refinement']=character_refinement
    for item in report['materials']:item['role']=next(e['role'] for e in ui.registry(scene)['materials'] if e['slot']==item['index'])
    scene['rpt_report']=json.dumps(report,ensure_ascii=False)
    text=bpy.data.texts.new('RandomPlayToon · 构建报告');text.write(json.dumps(report,ensure_ascii=False,indent=2))
    from .portable import embed_panel
    embed_panel()
    for selected in bpy.context.selected_objects:selected.select_set(False)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA'
    print('RANDOMPLAY 6/6 保存新文件',flush=True);temp=dest.with_name(dest.stem+'.building_'+uuid.uuid4().hex+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(temp),compress=True);os.replace(temp,dest);dest.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report
