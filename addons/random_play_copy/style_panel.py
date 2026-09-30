# Frozen from RandomPlayToon 0.7.9; regenerate with sync_copy_style_panel.py.
# Source SHA256: 12e07322cd0d87c657ab8fd6ac969d020964c528073f465e62f83059a0ee1a2f
"""Install as a Blender add-on, or run this text once to show the character panel.

All sliders edit the actual node inputs. No duplicate parameter storage or frame
handlers. Rendering and saved parameters work even when this UI is not installed.
"""
bl_info={'name':'RandomPlayCopy · 参数面板','author':'Vivian rendering experiment','version':(0,8,3),'blender':(5,2,0),'location':'3D View / Shader Editor > N > Character','category':'Material'}
import bpy, json, copy, math, textwrap
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

def registry(scene):return json.loads(scene.get('zzz_stage6_registry','{}'))
def node(entry):return bpy.data.materials[entry['material']].node_tree.nodes[entry['node']]
def all_entries(scene):
    r=registry(scene);return r.get('materials',[])+([r['global']] if 'global' in r else [])
def capture(scene):
    return {e['material']:{s.name:s.default_value if isinstance(s.default_value,(float,int,bool,str)) else list(s.default_value) for s in node(e).inputs if hasattr(s,'default_value')} for e in all_entries(scene)}
def refresh(scene):
    for e in all_entries(scene):
        bpy.data.materials[e['material']].update_tag();node(e).id_data.update_tag()
    for g in bpy.data.node_groups:
        if g.bl_idname=='ShaderNodeTree' and g.name.startswith('ZZZ_'):g.update_tag()
    bpy.data.objects['ZZZ_StyleControls'].update_tag();scene.frame_set(scene.frame_current);bpy.context.view_layer.update()
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:a.tag_redraw()

def light_object(scene):return bpy.data.objects.get(registry(scene).get('controller',''))
def light_edit_error(ob):
    if not ob:return None
    ad=ob.animation_data
    if ad and (ad.action or any(not t.mute and len(t.strips) for t in ad.nla_tracks) or any(not f.mute for f in ad.drivers)):
        return '光向控制器已有动画或驱动，请在静态副本应用方向或风格预设'
    if any(not c.mute and getattr(c,'influence',1)>0 for c in ob.constraints):
        return '光向控制器受约束控制，请先停用约束再应用方向或风格预设'
    return None
def light_angles(scene):
    from mathutils import Vector
    ob=light_object(scene)
    d=ob.matrix_world.to_3x3() @ Vector((0,0,1));d.normalize()
    return math.degrees(math.atan2(d.y,d.x)),math.degrees(math.asin(max(-1,min(1,d.z))))
def set_light_angles(scene,a,b):
    ob=light_object(scene)
    if ob:
        error=light_edit_error(ob)
        if error:raise ValueError(error)
        from mathutils import Matrix,Euler
        bpy.context.view_layer.update()
        # Angles and shader drivers are world-space; writing local Euler angles
        # introduces a parent rotation twice when the handle is parented.
        world=ob.matrix_world.copy();rotation=Euler((0,math.radians(90-b),math.radians(a)),'XYZ').to_quaternion()
        ob.rotation_mode='XYZ';ob.matrix_world=Matrix.LocRotScale(world.translation,rotation,world.to_scale());ob.update_tag()
def azimuth_get(s):return light_angles(s)[0] if light_object(s) else 0.
def elevation_get(s):return light_angles(s)[1] if light_object(s) else 0.
def azimuth_set(s,v):set_light_angles(s,v,elevation_get(s));bpy.context.view_layer.update()
def elevation_set(s,v):set_light_angles(s,azimuth_get(s),v);bpy.context.view_layer.update()

def lightweight_viewports():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.shading.use_compositor='DISABLED'
                area.spaces.active.shading.type='SOLID'

def apply_values(scene,values):
    """Validate the entire preset before any mutation; never silently half-apply."""
    if not isinstance(values,dict):raise ValueError('预设参数必须是材质参数字典')
    ob=light_object(scene);error=light_edit_error(ob)
    if error:raise ValueError(error)
    known={e['material']:e for e in all_entries(scene)};todo=[]
    if set(values)!=set(known):raise ValueError('预设材质集合与当前场景不匹配')
    for mat,data in values.items():
        if not isinstance(data,dict):raise ValueError('材质参数格式错误：'+mat)
        n=node(known[mat]);inputs={s.name:s for s in n.inputs if hasattr(s,'default_value')}
        if set(data)!=set(inputs):
            legacy=known[mat].get('legacy_label_sets',[known[mat].get('legacy_labels',[])])
            if any(labels and set(data)==set(labels) for labels in legacy):
                retired=set(known[mat].get('retired_labels',[]))
                data={k:v for k,v in data.items() if k not in retired}
                data={**json.loads(scene['zzz_stage6_defaults'])[mat],**data}
            else:raise ValueError('预设参数版本不匹配：'+mat)
        interfaces={x.identifier:x for x in n.node_tree.interface.items_tree if x.item_type=='SOCKET' and x.in_out=='INPUT'}
        for name,v in data.items():
            s=inputs[name];ui=interfaces[s.identifier]
            if s.type=='RGBA':
                if not isinstance(v,list) or len(v)!=4 or not all(not isinstance(x,bool) and isinstance(x,(float,int)) and math.isfinite(x) and 0<=x<=100 for x in v):raise ValueError('颜色无效：'+name)
            elif s.type=='BOOLEAN':
                if not isinstance(v,bool):raise ValueError('开关无效：'+name)
            else:
                lo,hi=ui.min_value,ui.max_value
                if ob and mat==registry(scene)['global']['material'] and name=='虚拟光俯仰角（度）':lo,hi=-90,90
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('数值超出范围：'+name)
            if s.is_linked:raise ValueError('输入已有自定义连接，请断开后载入数值预设：'+name)
            if n.id_data.animation_data and n.id_data.animation_data.action:
                # Preserve animated user inputs: applying defaults should not masquerade as an animation reset.
                raise ValueError('控制节点已有动画，请在静态副本载入预设')
            todo.append((s,v))
    ob=light_object(scene)
    if ob:
        data=values[registry(scene)['global']['material']]
        set_light_angles(scene,data['虚拟光水平角（度）'],data['虚拟光俯仰角（度）'])
    for s,v in todo:
        if ob and s.node==node(registry(scene)['global']) and s.name in ['虚拟光水平角（度）','虚拟光俯仰角（度）']:continue
        s.default_value=v
    refresh(scene)

def generic_preset_values(scene,name):
    # Keep the portable text self-contained: no installed package is required.
    values=json.loads(scene['zzz_stage6_defaults']);r=registry(scene);glob=values[r['global']['material']]
    if name=='SOFT':glob.update({'身体过渡宽度':.17,'基础高光强度':.2,'边缘光强度':.025})
    if name=='CONTRAST':glob.update({'身体过渡宽度':.035,'基础高光强度':.48})
    if name=='NIGHT':
        glob.update({'角色受光亮度':.32,'辉光强度':.45})
        for e in r['materials']:
            if e['role'] in ['emissive','eyes']:values[e['material']]['自发光强度']=1.2
    if name=='DISPLAY':glob['独立展示光照']=True
    return values

def source_make_preset(scene,name):
    values=json.loads(scene['zzz_stage6_defaults']);r=registry(scene)
    if r.get('generic'):
        return generic_preset_values(scene,name)
    if name=='BASELINE':return values
    def setkey(e,key,v):
        item=next((x for x in e['entries'] if x['key']==key),None)
        if item:values[e['material']][item['label']]=v
    for e in r['materials']:
        if r.get('revision',0)<2:values[e['material']]['使用全局控制']=False
        if name=='SOFT':
            for k,v in [('Body Softness',.18),('Face Softness',.24),('Global Specular',.7),('Rim Strength',.028)]:setkey(e,k,v)
        elif name=='CONTRAST':
            for k,v in [('Body Softness',.035),('Face Softness',.075),('Global Specular',1.25),('Rim Strength',.075)]:setkey(e,k,v)
        elif name=='NIGHT':
            if e['slot'] in [3,4]:setkey(e,'Glow Strength',1.5 if e['slot']==3 else .5)
            if e['slot'] in [10,12,13]:setkey(e,'Glow Strength',.7)
            if e['slot']==16:
                setkey(e,'Glow Strength',1.4);setkey(e,'Back Glow Strength',1.0);setkey(e,'Glow Tint',[.08,.16,.9,1.])
    glob=r['global']
    if name=='SOFT' and not r.get('default_tuning'):setkey(glob,'Warmth',.12)
    if name=='SOFT':
        for k,v in [('Body Softness',.18),('Global Specular',.7),('Rim Strength',.028)]:setkey(glob,k,v)
    if name=='CONTRAST':
        for k,v in [('Body Softness',.035),('Global Specular',1.25),('Rim Strength',.075)]:setkey(glob,k,v)
    if name=='CONTRAST':setkey(glob,'Outline Width',.0008)
    if name=='NIGHT':
        for k,v in [('Key Gain',.28),('Bloom Strength',.35),('Bloom Threshold',.45)]:setkey(glob,k,v)
    if r.get('revision',0)>=2:
        # Original four presets retain their previous scene/emission behavior.
        # The user may independently override the lighting choice afterwards.
        if name=='DISPLAY':
            setkey(glob,'Studio Mode',True);setkey(glob,'Black Background',True)
            setkey(glob,'Studio Emission',1.6)
            if r.get('polish'):
                for k,v in [('Body Softness',.045),('Bloom Strength',.16),('Bloom Threshold',1.05)]:setkey(glob,k,v)
                for e in r['materials']:
                    setkey(e,'Body Softness',.045);setkey(e,'Face Softness',.075)
                    if e['slot']==16 and r.get('polish')==1:setkey(e,'Glow Tint',[.055,.48,.85,1.])
            if r.get('live_preview'):
                setkey(glob,'Bloom Strength',.55);setkey(glob,'Bloom Size',.3)
            if r.get('lightweight'):
                # Reset the entire gem parameter set to BASELINE, with its studio
                # boost opt-in disabled. Other parts keep studio emission.
                gem=next(e for e in r['materials'] if e['slot']==16)
                values[gem['material']]=json.loads(scene['zzz_stage6_defaults'])[gem['material']]
            if r.get('bloom_fix'):setkey(glob,'Bloom Threshold',.8)
    return values

def make_preset(scene,name):
    values=source_make_preset(scene,name)
    report=json.loads(scene.get('rpc_transfer','{}'))
    scale=report.get('head',{}).get('source_to_cache_scale',1.)
    r=registry(scene)
    for item in r['global']['entries']:
        if item['key']=='Outline Width':
            values[r['global']['material']][item['label']]*=scale
    return values

class RPCSTYLE_OT_preset(bpy.types.Operator):
    bl_idname='rpcstyle.style_preset';bl_label='应用风格预设';bl_options={'REGISTER','UNDO'}
    bl_description='替换本工具管理的风格数值；不更改灯光、模型或贴图。可撤销，建议先导出个人预设'
    preset:EnumProperty(items=[('BASELINE','默认风格','恢复第六步入口默认值，包括场景光照方式'),('SOFT','柔和','柔和明暗与较弱高光'),('CONTRAST','清晰','更清晰的明暗与描边'),('NIGHT','暗场','角色受光变暗并启用局部发光，不改场景灯光'),('DISPLAY','独立虚拟光源控制','使用虚拟光向与黑底展示预设，隔离实际场景照明')])
    def execute(self,context):
        try:apply_values(context.scene,make_preset(context.scene,self.preset))
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
        return {'FINISHED'}

class RPCSTYLE_OT_export(bpy.types.Operator,ExportHelper):
    bl_idname='rpcstyle.export_style';bl_label='导出个人预设';filename_ext='.json'
    filter_glob:StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            with open(self.filepath,'w',encoding='utf8') as f:json.dump({'schema':1,'values':capture(context.scene)},f,ensure_ascii=False,indent=2)
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
        return {'FINISHED'}

class RPCSTYLE_OT_full_render(bpy.types.Operator):
    bl_idname='rpcstyle.full_render';bl_label='渲染完整效果';bl_description='渲染主画面与眼部遮挡层，显示最终合成（含透眼、辉光、黑底）；普通材质预览不包含双层合成'
    def execute(self,context):
        s=context.scene
        if bpy.app.is_job_running('RENDER'):self.report({'WARNING'},'当前渲染尚未结束');return {'CANCELLED'}
        if not s.camera:self.report({'ERROR'},'请先设置场景相机');return {'CANCELLED'}
        required=['ZZZ_Beauty']+(['ZZZ_EyeVisibility'] if 'ZZZ_EyeVisibility' in s.view_layers else [])
        if not s.compositing_node_group or any(n not in s.view_layers for n in required):
            self.report({'ERROR'},'场景缺少透眼合成或视图层，请打开完整薇薇安场景');return {'CANCELLED'}
        s.render.use_compositing=True;s.render.use_single_layer=False
        for name in required:s.view_layers[name].use=True
        def finished(_):
            if finished in bpy.app.handlers.render_complete:bpy.app.handlers.render_complete.remove(finished)
            if cancelled in bpy.app.handlers.render_cancel:bpy.app.handlers.render_cancel.remove(cancelled)
            def show_composite():
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type=='IMAGE_EDITOR':
                            sp=area.spaces.active
                            if sp.image and sp.image.type=='RENDER_RESULT':sp.image_user.multilayer_layer=0;area.tag_redraw()
                return None
            bpy.app.timers.register(show_composite,first_interval=.2)
        def cancelled(_):
            if finished in bpy.app.handlers.render_complete:bpy.app.handlers.render_complete.remove(finished)
            if cancelled in bpy.app.handlers.render_cancel:bpy.app.handlers.render_cancel.remove(cancelled)
        bpy.app.handlers.render_complete.append(finished);bpy.app.handlers.render_cancel.append(cancelled)
        try:
            # Let Blender's render operator manage its display window. Opening
            # Render View first can change the invocation context unexpectedly.
            result=bpy.ops.render.render('INVOKE_DEFAULT',scene=s.name,layer='')
            if 'CANCELLED' in result:cancelled(s)
        except Exception as ex:cancelled(s);self.report({'ERROR'},str(ex));return {'CANCELLED'}
        return {'FINISHED'}

class RPCSTYLE_OT_live_preview(bpy.types.Operator):
    bl_idname='rpcstyle.live_preview';bl_label='轻量操作视图 · 关闭实时渲染'
    bl_description='切换实体着色并关闭视口合成；旋转光向箭头后按 F12 检查完整效果'
    def execute(self,context):
        lightweight_viewports();return {'FINISHED'}

class RPCSTYLE_OT_light_direction(bpy.types.Operator):
    bl_idname='rpcstyle.light_direction';bl_label='选择光向箭头 · 旋转调整'
    bl_description='箭头指向来光方向；用 R 或旋转工具拖动，角度读数同步。移动箭头不改变照明'
    def execute(self,context):
        ob=light_object(context.scene)
        if not ob:return {'CANCELLED'}
        for o in context.selected_objects:o.select_set(False)
        ob.hide_set(False);ob.select_set(True);context.view_layer.objects.active=ob
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type=='VIEW_3D':
                    a.spaces.active.overlay.show_overlays=True
                    with context.temp_override(window=w,area=a):bpy.ops.wm.tool_set_by_id(name='builtin.rotate')
        return {'FINISHED'}

class RPCSTYLE_OT_import(bpy.types.Operator,ImportHelper):
    bl_idname='rpcstyle.import_style';bl_label='载入个人预设';bl_options={'REGISTER','UNDO'}
    filename_ext='.json';filter_glob:StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            with open(self.filepath,encoding='utf8') as f:data=json.load(f)
            if data.get('schema')!=1:raise ValueError('不支持的预设版本')
            apply_values(context.scene,data['values'])
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
        return {'FINISHED'}

class RPCSTYLE_OT_focus(bpy.types.Operator):
    bl_idname='rpcstyle.focus_controls';bl_label='定位参数节点';bl_description='在着色器编辑器中定位唯一参数节点；无需进入组内'
    global_controls:bpy.props.BoolProperty(default=False)
    def execute(self,context):
        r=registry(context.scene)
        is_global=self.global_controls or context.scene.rpc_style_style_slot=='GLOBAL'
        if is_global:e=r['global']
        else:
            idx=int(context.scene.rpc_style_style_slot);e=next(x for x in r['materials'] if x['slot']==idx)
        mat=bpy.data.materials[e['material']];n=node(e)
        obj=bpy.data.objects['ZZZ_StyleDashboard' if is_global else r.get('mesh_object','Vivian_Mapping')]
        for ob in context.view_layer.objects:ob.select_set(False)
        context.view_layer.objects.active=obj;obj.hide_set(False);obj.select_set(True)
        if not is_global:obj.active_material_index=idx
        if context.area.type=='NODE_EDITOR':area=context.area
        else:
            ws=bpy.data.workspaces.get('Shading')
            if ws:context.window.workspace=ws
            area=next((a for a in context.window.screen.areas if a.type=='NODE_EDITOR'),None)
        if area:
            area.ui_type='ShaderNodeTree';sp=area.spaces.active;sp.shader_type='OBJECT';sp.pin=False
            for x in mat.node_tree.nodes:x.select=False
            n.select=True;mat.node_tree.nodes.active=n
            region=next(x for x in area.regions if x.type=='WINDOW')
            with context.temp_override(area=area,region=region):bpy.ops.node.view_selected()
            # Node dimensions become available after the workspace's first draw.
            def fit_after_draw():
                try:
                    with bpy.context.temp_override(area=area,region=region):bpy.ops.node.view_selected()
                except (ReferenceError,RuntimeError):pass
                return None
            if not bpy.app.background:bpy.app.timers.register(fit_after_draw,first_interval=.2)
        return {'FINISHED'}

class RPCSTYLE_OT_skin(bpy.types.Operator):
    bl_idname='rpcstyle.copy_skin_tint';bl_label='肤色同步到脸和皮肤';bl_options={'REGISTER','UNDO'}
    bl_description='将当前部位的肤色乘色复制到颜、颜2和肌，保留每个部位的阴影色'
    def execute(self,context):
        r=registry(context.scene);idx=int(context.scene.rpc_style_style_slot);e=next(x for x in r['materials'] if x['slot']==idx)
        key=next(x['label'] for x in e['entries'] if x['key']=='Base Tint');v=tuple(node(e).inputs[key].default_value)
        for target in r['materials']:
            if target.get('role') in ['face','skin'] or (not r.get('generic') and target['slot'] in [0,1,11]):
                if '肤色乘色' in node(target).inputs:node(target).inputs['肤色乘色'].default_value=v
        refresh(context.scene);return {'FINISHED'}

_ITEMS_CACHE={}
def material_items(self,context):
    # Blender retains pointers to dynamic EnumProperty strings; keep them alive.
    if context is None:return []
    key=context.scene.get('zzz_stage6_registry','{}')
    if key not in _ITEMS_CACHE:
        _ITEMS_CACHE[key]=[('GLOBAL','全局','角色共用明暗、高光、描边、透眼和出图设置')]+[(str(e['slot']),e['material'].split('_')[-1]+' · '+str(e['slot']),'编辑此材质的实际节点输入') for e in registry(context.scene).get('materials',[])]
    return _ITEMS_CACHE[key]

def draw_grouped(layout,entry,prefixes=None,exclude=None):
    n=node(entry);grouped={}
    for e in entry['entries']:
        cat=e['category']
        if prefixes and not any(cat.startswith(x) for x in prefixes):continue
        if exclude and any(cat.startswith(x) for x in exclude):continue
        grouped.setdefault(cat,[]).append(e)
    for cat,items in sorted(grouped.items()):
        header,body=layout.panel('rpc_style_'+entry['material']+'_'+cat,default_closed=cat.startswith(('04','05','06')));header.label(text=cat[3:])
        if body:
            for item in items:
                if item['key']=='Studio Mode':continue  # The mode selector is always visible above the part list.
                s=n.inputs[item['label']];row=body.row()
                switch=item.get('source_socket','使用全局控制')
                if (item.get('global') or item.get('global_control')) and switch and n.inputs[switch].default_value:row.enabled=False
                if item['key'] in ['Studio Azimuth','Studio Elevation','Studio Emission','Display Light','Display Shadow','Light Color','Hair Scene Tint'] and not bpy.context.scene.rpc_style_lighting_mode=='STUDIO':row.enabled=False
                if s.is_linked:row.label(text=item['label']+'（节点连线）')
                elif light_object(bpy.context.scene) and item['key'] in ['Studio Azimuth','Studio Elevation']:
                    if light_edit_error(light_object(bpy.context.scene)):row.enabled=False
                    row.prop(bpy.context.scene,'rpc_style_studio_azimuth' if item['key']=='Studio Azimuth' else 'rpc_style_studio_elevation',text=item['label'])
                else:row.prop(s,'default_value',text=item['label'])
                if bpy.context.scene.rpc_style_style_help:
                    width=max(16,int(bpy.context.region.width/14)-3)
                    for line in textwrap.wrap(item['description'],width=width):body.label(text=line)

class PanelBase:
    bl_region_type='UI';bl_category='ABC渲染'
    @classmethod
    def poll(cls,context):return bool(context.scene.get('rpc_transfer')) and context.scene.get('zzz_stage6_schema') in [1,2]
    def draw(self,context):
        s=context.scene;r=registry(s);layout=self.layout
        if r.get('revision',0)>=2:
            layout.operator('rpcstyle.style_preset',text='独立虚拟光源控制').preset='DISPLAY'
        layout.operator('rpcstyle.style_preset',text='默认风格').preset='BASELINE'
        row=layout.row(align=True)
        for name,label in [('SOFT','柔和'),('CONTRAST','清晰'),('NIGHT','暗场')]:row.operator('rpcstyle.style_preset',text=label).preset=name
        if r.get('revision',0)>=2:layout.prop(s,'rpc_style_lighting_mode',text='光照方式')
        layout.operator('rpcstyle.full_render',text='渲染完整效果 · 透眼 / 辉光',icon='RENDER_STILL')
        if r.get('live_preview'):
            layout.operator('rpcstyle.live_preview',icon='SHADING_SOLID')
            if s.rpc_style_lighting_mode=='STUDIO':layout.operator('rpcstyle.light_direction',icon='EMPTY_SINGLE_ARROW')
            layout.label(text='调整方向后按 F12 查看完整效果',icon='INFO')
        elif r.get('polish',0)>=2:layout.label(text='F12结果不会随材质修改自动重渲染',icon='INFO')
        row=layout.row(align=True);row.operator('rpcstyle.export_style',text='导出预设');row.operator('rpcstyle.import_style',text='载入预设')
        layout.separator();layout.prop(s,'rpc_style_style_slot',text='部位')
        layout.prop(s,'rpc_style_style_help',text='显示参数作用说明')
        if s.rpc_style_style_slot=='GLOBAL':
            layout.operator('rpcstyle.focus_controls',text='查看全局参数节点').global_controls=True
            draw_grouped(layout,r['global'])
            return
        e=next((x for x in r['materials'] if x['slot']==int(s.rpc_style_style_slot)),r['materials'][0]);n=node(e)
        layout.operator('rpcstyle.focus_controls',text='查看本部位参数节点').global_controls=False
        keys={x['key'] for x in e['entries']}
        if r.get('revision',0)>=2 and not r.get('generic'):
            if keys & {'Body Threshold','Body Softness'}:layout.prop(n.inputs['明暗使用全局'],'default_value',text='明暗使用全局')
            if keys & {'Global Specular','Highlight Width','Rim Strength'}:layout.prop(n.inputs['使用全局控制'],'default_value',text='基础高光／边缘光使用全局')
        elif not r.get('generic'):layout.prop(n.inputs['使用全局控制'],'default_value',text='明暗／高光使用全局数值')
        if not r.get('generic') and e['slot'] in [0,1,11]:layout.operator('rpcstyle.copy_skin_tint')
        draw_grouped(layout,e)

class RPCSTYLE_PT_view(PanelBase,bpy.types.Panel):
    bl_idname='RPCSTYLE_PT_view';bl_label='角色风格';bl_space_type='VIEW_3D'
class RPCSTYLE_PT_nodes(PanelBase,bpy.types.Panel):
    bl_idname='RPCSTYLE_PT_nodes';bl_label='角色风格';bl_space_type='NODE_EDITOR'

CLASSES=[RPCSTYLE_OT_preset,RPCSTYLE_OT_export,RPCSTYLE_OT_import,RPCSTYLE_OT_focus,RPCSTYLE_OT_skin,RPCSTYLE_OT_full_render,RPCSTYLE_OT_live_preview,RPCSTYLE_OT_light_direction,RPCSTYLE_PT_view,RPCSTYLE_PT_nodes]

def lighting_get(self):
    r=registry(self)
    return int(bool(node(r['global']).inputs['独立展示光照'].default_value)) if r.get('revision',0)>=2 else 0

def lighting_set(self,value):
    r=registry(self)
    if r.get('revision',0)>=2:
        node(r['global']).inputs['独立展示光照'].default_value=bool(value);refresh(self)
@bpy.app.handlers.persistent
def sync_character_tab(_=None):
    scene=getattr(bpy.context,'scene',None)
    if scene is None:return .1
    label='ABC渲染'
    for cls in [RPCSTYLE_PT_view,RPCSTYLE_PT_nodes]:
        if getattr(cls,'is_registered',False) and cls.bl_category!=label:
            bpy.utils.unregister_class(cls)
            cls.bl_category=label;bpy.utils.register_class(cls)

sync_character_tab._rpc_style_character_tab_handler=True

def unregister():
    # Re-running an embedded text creates new Python function objects.
    # Remove the preceding copy as well, otherwise file changes run stale panels.
    if bpy.app.timers.is_registered(sync_character_tab):bpy.app.timers.unregister(sync_character_tab)
    for handler in list(bpy.app.handlers.load_post):
        if handler is sync_character_tab or getattr(handler,'_rpc_style_character_tab_handler',False):
            if bpy.app.timers.is_registered(handler):bpy.app.timers.unregister(handler)
            bpy.app.handlers.load_post.remove(handler)
    for name in ['rpc_style_studio_azimuth','rpc_style_studio_elevation']:
        if hasattr(bpy.types.Scene,name):delattr(bpy.types.Scene,name)
    if hasattr(bpy.types.Scene,'rpc_style_style_slot'):del bpy.types.Scene.rpc_style_style_slot
    if hasattr(bpy.types.Scene,'rpc_style_style_help'):del bpy.types.Scene.rpc_style_style_help
    if hasattr(bpy.types.Scene,'rpc_style_lighting_mode'):del bpy.types.Scene.rpc_style_lighting_mode
    for c in reversed(CLASSES):
        old=c if getattr(c,'is_registered',False) else getattr(bpy.types,c.__name__,None)
        if old:bpy.utils.unregister_class(old)
def register():
    unregister()
    # Preferences enables add-ons inside RestrictBlend: scene/data are not
    # available yet. Register RNA now; read the scene on the next UI tick.
    # Direct background builds and portable-text runs already have a context.
    scene=getattr(bpy.context,'scene',None)
    label='ABC渲染'
    RPCSTYLE_PT_view.bl_category=label;RPCSTYLE_PT_nodes.bl_category=label
    if sync_character_tab not in bpy.app.handlers.load_post:bpy.app.handlers.load_post.append(sync_character_tab)
    for c in CLASSES:bpy.utils.register_class(c)
    bpy.types.Scene.rpc_style_style_slot=EnumProperty(name='部位',items=material_items)
    bpy.types.Scene.rpc_style_style_help=bpy.props.BoolProperty(name='显示参数作用说明',default=False,description='在每个参数下显示中文含义；节点输入本身也有悬停说明')
    bpy.types.Scene.rpc_style_lighting_mode=EnumProperty(name='光照方式',items=[('SCENE','场景响应','保留原KeySun和场景响应'),('STUDIO','独立展示','只使用虚拟光向和虚拟反光，隔离实际场景照明')],get=lighting_get,set=lighting_set)
    bpy.types.Scene.rpc_style_studio_azimuth=bpy.props.FloatProperty(name='虚拟光水平角（度）',min=-180,max=180,get=azimuth_get,set=azimuth_set)
    bpy.types.Scene.rpc_style_studio_elevation=bpy.props.FloatProperty(name='虚拟光俯仰角（度）',min=-90,max=90,get=elevation_get,set=elevation_set)
    if scene is None:bpy.app.timers.register(sync_character_tab,first_interval=0.)
if __name__=='__main__':
    register()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type in {'VIEW_3D','NODE_EDITOR'}:area.spaces.active.show_region_ui=True
