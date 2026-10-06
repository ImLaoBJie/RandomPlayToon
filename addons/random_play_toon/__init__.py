"""Vivian reconstruction plugin; build work never changes the active scene."""
bl_info={'name':'RandomPlayToon','author':'Vivian rendering experiment','version':(0,9,3),'blender':(5,2,0),'category':'Import-Export'}
import bpy,json,subprocess,time,uuid,hashlib
from pathlib import Path
from bpy.props import StringProperty,EnumProperty,BoolProperty,PointerProperty
from bpy_extras.io_utils import ImportHelper

_job=None

def scene_guard():
    """Conservative fingerprint for an otherwise empty, untitled start scene."""
    s=bpy.context.scene
    # Automatic opening only for an actually empty scene, not a default cube scene.
    if bpy.data.filepath or len(bpy.data.objects):return None
    def props(block):
        if block is None:return None
        values={}
        for prop in block.bl_rna.properties:
            if prop.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:
                try:
                    value=getattr(block,prop.identifier)
                    if not isinstance(value,(bool,int,float,str)):value=list(value)
                    values[prop.identifier]=value
                except (TypeError,AttributeError):pass
        return values
    def tree_state(tree):
        if tree is None:return None
        return {'nodes':[(n.name,props(n),[props(x) for x in n.inputs]) for n in tree.nodes],
          'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in tree.links]}
    fingerprint={'scene':props(s),'render':props(s.render),'view':props(s.view_settings),
        'world':props(s.world),'world_nodes':tree_state(s.world.node_tree) if s.world else None,
        'compositor':tree_state(s.compositing_node_group),
        'materials':[(m.name,props(m),tree_state(m.node_tree)) for m in bpy.data.materials],
        'node_groups':[(g.name,tree_state(g)) for g in bpy.data.node_groups]}
    return (s.as_pointer(),tuple((x.name,x.as_pointer()) for x in bpy.data.scenes),hashlib.sha256(json.dumps(fingerprint,sort_keys=True,default=str).encode()).hexdigest())

class RPT_Settings(bpy.types.PropertyGroup):
    pmx:StringProperty(name='模型 PMX',subtype='FILE_PATH',description='已校准角色、形态或独立武器 PMX；按内容指纹识别，文件可改名或移动')
    textures:StringProperty(name='配套纹理目录',subtype='DIR_PATH',description='留空时使用 PMX 所在文件夹；指定时应包含 tex、spa 等原始相对目录')
    assets:StringProperty(name='渲染素材目录',subtype='DIR_PATH',description='选择角色素材目录、PlayerCharacterData 或 ZZ-Model-Importer-Assets 根目录')
    output:StringProperty(name='输出新文件',subtype='FILE_PATH',description='单独的新 .blend 文件；已有文件不会覆盖')
    keep_style:BoolProperty(name='保留当前个人调整',default=False,description='有第六步风格面板的场景可将当前参数带入新重建结果；不迁移动画或手工节点连接')
    auto_open:BoolProperty(name='空白场景完成后自动打开',default=True,description='仅无文件、无物体且构建期间未改变的空场景自动打开；其他情况保留原场景，通过打开结果进入')
    status:StringProperty(default='选择模型 PMX 和渲染素材目录后开始。')
    result:StringProperty(subtype='FILE_PATH')
    report:StringProperty(subtype='FILE_PATH')

class RPT_OT_choose(bpy.types.Operator,ImportHelper):
    bl_idname='rpt.choose_pmx';bl_label='选择模型 PMX'
    filter_glob:StringProperty(default='*.pmx',options={'HIDDEN'})
    def execute(self,context):
        p=context.scene.rpt;p.pmx=self.filepath
        if not p.output:p.output=str(Path(self.filepath).parent/(Path(self.filepath).stem+'_rebuilt.blend'))
        try:
            from .core import identify
            profile=identify(self.filepath);p.status='已识别：'+profile['id']+'；按该模型的默认参数重建。'
        except ValueError as ex:p.status=str(ex)
        return {'FINISHED'}

def redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {'VIEW_3D','NODE_EDITOR'}:area.tag_redraw()

def job_tick():
    global _job
    if not _job:return None
    job=_job;scene=job['scene']
    try:settings=scene.rpt
    except ReferenceError:
        # Loading/deleting a scene during a build must not lose the completed file.
        scene=bpy.context.scene;settings=scene.rpt;job['scene']=scene;job['guard']=None
    if job['process'].poll() is None:
        try:
            lines=job['log'].read_text(encoding='utf8',errors='replace').splitlines()
            steps=[x for x in lines if x.startswith('RANDOMPLAY ')]
            if steps:settings.status=steps[-1].removeprefix('RANDOMPLAY ')
        except OSError:pass
        redraw();return .5
    job['handle'].close();_job=None
    if bpy.app.timers.is_registered(job_tick):bpy.app.timers.unregister(job_tick)
    try:result=json.loads(job['status'].read_text(encoding='utf8'))
    except Exception:result={'status':'error','message':'后台进程未完成，请查看日志：'+str(job['log'])}
    settings.report=str(job['status'])
    if result['status']=='success':
        settings.result=result['output'];settings.status='重建完成。可打开结果，或查看构建报告。'
        if job['auto'] and job['guard'] is not None and scene_guard()==job['guard']:
            bpy.ops.wm.open_mainfile(filepath=result['output'])
            from . import style_panel
            style_panel.register();style_panel.lightweight_viewports()
            bpy.context.scene.rpt.result=result['output'];bpy.context.scene.rpt.report=str(job['status']);bpy.context.scene.rpt.status='重建完成；侧栏下方可调风格，F12 查看完整效果。'
    else:settings.status='构建未完成：'+result.get('message','请查看报告')
    redraw();return None

class RPT_OT_build(bpy.types.Operator):
    bl_idname='rpt.build';bl_label='一键重建';bl_description='在独立后台进程中导入 PMX 并构建对应角色材质、灯光和侧边栏；原场景不受影响'
    @classmethod
    def poll(cls,context):return _job is None
    def execute(self,context):
        global _job
        p=context.scene.rpt
        try:
            from .core import preflight
            if not p.pmx or not p.assets or not p.output:raise ValueError('请选择 PMX、渲染素材目录和输出新文件。')
            pmx=bpy.path.abspath(p.pmx);textures=bpy.path.abspath(p.textures) if p.textures else '';assets=bpy.path.abspath(p.assets);output=Path(bpy.path.abspath(p.output)).resolve()
            if output.exists():raise ValueError('输出已存在，请换一个文件名；旧结果会保留。')
            if output.suffix.lower()!='.blend':raise ValueError('输出文件名应以 .blend 结尾。')
            preflight(pmx,textures,assets,'CURRENT')
            personal=None
            if p.keep_style:
                from . import style_panel as ui
                if not ui.registry(context.scene):raise ValueError('当前场景没有可保留的风格参数。')
                personal=ui.capture(context.scene)
                # Validate without changing scene or forcing animated controllers.
                if ui.light_edit_error(ui.light_object(context.scene)):raise ValueError(ui.light_edit_error(ui.light_object(context.scene)))
                for entry in ui.all_entries(context.scene):
                    node=ui.node(entry);ad=node.id_data.animation_data
                    input_paths={s.path_from_id('default_value') for s in node.inputs if hasattr(s,'default_value') and s.name not in ['虚拟光水平角（度）','虚拟光俯仰角（度）']}
                    controlled=bool(ad and (ad.action or any(f.data_path in input_paths for f in ad.drivers)))
                    if any(s.is_linked for s in node.inputs) or controlled:
                        raise ValueError('当前风格控制含动画、驱动或自定义连线，无法作为静态参数迁移。')
            output.parent.mkdir(parents=True,exist_ok=True)
            folder=output.parent/'.randomplay_jobs'/uuid.uuid4().hex;folder.mkdir(parents=True)
            request=folder/'request.json';status=folder/'status.json';log=folder/'worker.log'
            args={'pmx':pmx,'texture_root':textures,'asset_root':assets,'output':str(output),'preset':'CURRENT','personal_preset':personal,'status_file':str(status)}
            request.write_text(json.dumps(args,ensure_ascii=False,indent=2),encoding='utf8')
            handle=log.open('w',encoding='utf8')
            try:process=subprocess.Popen([bpy.app.binary_path,'-b','--factory-startup','--python-exit-code','1','--python',str(Path(__file__).parent/'worker.py'),'--',str(request)],stdout=handle,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except Exception:handle.close();raise
            p.status='正在启动后台 Blender…';p.result='';p.report=str(status)
            _job={'process':process,'handle':handle,'log':log,'status':status,'scene':context.scene,'guard':scene_guard(),'auto':p.auto_open}
            bpy.app.timers.register(job_tick,first_interval=.5)
            return {'FINISHED'}
        except Exception as exc:
            p.status=str(exc);self.report({'ERROR'},str(exc));return {'CANCELLED'}

class RPT_OT_open(bpy.types.Operator):
    bl_idname='rpt.open_result';bl_label='打开重建结果'
    def invoke(self,context,event):
        if not bpy.data.is_dirty:return self.execute(context)
        return context.window_manager.invoke_confirm(self,event,message='当前场景有未保存修改。请先保存；继续将切换到重建结果。',confirm_text='打开结果')
    def execute(self,context):
        path=context.scene.rpt.result
        if not Path(path).is_file():self.report({'ERROR'},'结果文件不存在');return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=path)
        from . import style_panel
        style_panel.register();style_panel.lightweight_viewports();return {'FINISHED'}

class RPT_OT_report(bpy.types.Operator):
    bl_idname='rpt.show_report';bl_label='查看例外与构建报告'
    def execute(self,context):
        p=context.scene.rpt.report
        embedded=context.scene.get('rpt_report') or context.scene.get('zzz_stage7_report')
        if not embedded and (not p or not Path(p).is_file()):self.report({'WARNING'},'报告尚未生成');return {'CANCELLED'}
        text=bpy.data.texts.get('RandomPlayToon · 构建报告') or bpy.data.texts.new('RandomPlayToon · 构建报告');text.clear();text.write(json.dumps(json.loads(embedded),ensure_ascii=False,indent=2) if embedded else Path(p).read_text(encoding='utf8'))
        context.area.type='TEXT_EDITOR';context.area.spaces.active.text=text;return {'FINISHED'}

class RPT_PT_build(bpy.types.Panel):
    bl_label='RandomPlayToon · 一键重建';bl_idname='RPT_PT_build';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='RandomPlayToon';bl_order=-10
    def draw(self,context):
        p=context.scene.rpt;l=self.layout
        l.label(text='PMX → 自动识别 → 材质与参数面板')
        col=l.column();col.enabled=_job is None
        col.operator('rpt.choose_pmx',icon='FILE_FOLDER');col.prop(p,'pmx');col.prop(p,'textures');col.prop(p,'assets');col.prop(p,'output')
        if context.scene.get('zzz_stage6_registry'):col.prop(p,'keep_style')
        col.prop(p,'auto_open');col.operator('rpt.build',icon='IMPORT')
        import textwrap
        width=max(18,int(context.region.width/14)-3)
        for line in p.status.splitlines():
            for wrapped in textwrap.wrap(line,width):l.label(text=wrapped)
        if p.result:l.operator('rpt.open_result',icon='FILE_BLEND')
        if context.scene.get('rpt_report') or context.scene.get('zzz_stage7_report') or (p.report and Path(p.report).is_file()):l.operator('rpt.show_report',icon='TEXT')

CLASSES=[RPT_Settings,RPT_OT_choose,RPT_OT_build,RPT_OT_open,RPT_OT_report,RPT_PT_build]
def register():
    from . import style_panel
    # Blender removes a failed package import but can keep its submodules.
    # Replacing the failed 0.7.7 ZIP in the same session must not reuse its UI.
    if style_panel.bl_info['version']!=bl_info['version']:
        import importlib
        style_panel.unregister()
        importlib.reload(style_panel)
    style_panel.register()
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.rpt=PointerProperty(type=RPT_Settings)
def unregister():
    global _job
    if bpy.app.timers.is_registered(job_tick):bpy.app.timers.unregister(job_tick)
    if _job:
        _job['process'].terminate();_job['handle'].close();_job=None
    if hasattr(bpy.types.Scene,'rpt'):del bpy.types.Scene.rpt
    for cls in reversed(CLASSES):
        if getattr(cls,'is_registered',False):bpy.utils.unregister_class(cls)
    from . import style_panel
    style_panel.unregister()
