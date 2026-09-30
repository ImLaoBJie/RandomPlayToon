"""Independent Alembic render-look transfer. Independent namespaced 0.7.9-compatible style UI."""
bl_info = {'name': 'RandomPlayCopy · ABC渲染套用', 'author': 'Rendering experiment',
           'version': (0, 8, 3), 'blender': (5, 2, 0), 'category': 'Import-Export'}
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

import bpy
from bpy.props import StringProperty, PointerProperty, EnumProperty, FloatProperty, BoolProperty
from .paths import output_path

_job = None


class RPC_Settings(bpy.types.PropertyGroup):
    template: StringProperty(name='已着色模板', subtype='FILE_PATH', description='角色已调好效果的静态 .blend，包括个人材质参数')
    abc: StringProperty(name='动画缓存', subtype='FILE_PATH', description='phase3 交付目录中的 animation.abc；保留三个配套数据文件')
    # A plain text field accepts a full pasted path without the generic file
    # browser treating it as a filename and replacing separators with underscores.
    output: StringProperty(name='输出完整路径', description='直接粘贴包含文件名的完整 .blend 路径；也可先点“选择目录”。已有文件不会覆盖')
    status: StringProperty(default='选择模板、ABC 和新输出路径。')
    result: StringProperty(subtype='FILE_PATH')
    output_fps: EnumProperty(name='输出帧率', items=[('SOURCE','跟随 ABC','保持缓存帧率'),('30','30 fps','按秒播放'),('60','60 fps','保持动作时长，头部控制同步换算')], default='SOURCE')
    camera_warmup_seconds: FloatProperty(name='ABC 已含预热（秒）', default=1, min=0, max=3600,
        description='本批 phase3_faces_60fps_full 为 1 秒；仅记录为可选相机的默认偏移，不改变角色缓存')


def tick():
    global _job
    if _job is None:
        return None
    if _job['process'].poll() is None:
        return .5
    job, _job = _job, None
    job['log'].close()
    try:
        result = json.loads(job['status'].read_text(encoding='utf8'))
    except (OSError, ValueError):
        result = {'status': 'error', 'message': '后台进程退出；查看日志：'+str(job['log_path'])}
    p = bpy.context.window_manager.rpc_settings
    if result['status'] == 'success':
        p.result = result['output']
        p.status = '已保存到：'+result['output']
    else:
        p.status = '失败：'+result.get('message', '查看日志')
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return None


class RPC_OT_build(bpy.types.Operator):
    bl_idname = 'rpc.build'
    bl_label = '将渲染效果套用到 ABC'
    bl_description = '独立后台构建，不改动当前场景，不重算动作'

    @classmethod
    def poll(cls, context):
        return _job is None

    def execute(self, context):
        global _job
        p = context.window_manager.rpc_settings
        if not all(getattr(p, key).strip() for key in ['template', 'abc', 'output']):
            self.report({'ERROR'}, '请填写三个路径。')
            return {'CANCELLED'}
        try:
            destination = output_path(p.output, bpy.data.filepath)
            args = {key: str(Path(bpy.path.abspath(getattr(p, key))).resolve()) for key in ['template', 'abc']}
            args['output'] = str(destination)
        except (ValueError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if not Path(args['template']).is_file() or not Path(args['abc']).is_file():
            self.report({'ERROR'}, '模板或缓存不存在。')
            return {'CANCELLED'}
        if Path(args['output']).exists():
            self.report({'ERROR'}, '输出已存在，请使用新路径。')
            return {'CANCELLED'}
        # Inherit normal Windows ACLs; Python 3.13 mkdtemp's restrictive 0700
        # can make child files inaccessible in a managed desktop environment.
        folder = Path(tempfile.gettempdir())/('random_play_copy_'+uuid.uuid4().hex)
        folder.mkdir()
        status, request, log_path = folder/'status.json', folder/'request.json', folder/'worker.log'
        args['output_fps'] = None if p.output_fps == 'SOURCE' else float(p.output_fps)
        args['camera_warmup_seconds'] = p.camera_warmup_seconds
        args['status_file'] = str(status)
        request.write_text(json.dumps(args, ensure_ascii=False), encoding='utf8')
        log = log_path.open('w', encoding='utf8')
        try:
            process = subprocess.Popen([bpy.app.binary_path, '-b', '--factory-startup', '--python-exit-code', '1',
                                        '--python', str(Path(__file__).with_name('worker.py')), '--', str(request)],
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            log.close()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        _job = dict(process=process, status=status, log=log, log_path=log_path)
        p.result = ''
        p.status = '正在后台套用；日志：'+str(log_path)
        bpy.app.timers.register(tick, first_interval=.5)
        return {'FINISHED'}


class RPC_OT_output_directory(bpy.types.Operator):
    bl_idname = 'rpc.choose_output_directory'
    bl_label = '选择目录'
    bl_description = '只选择输出文件夹；文件名在面板的完整路径中修改，不要把完整路径填入文件选择器的文件名栏'
    directory: StringProperty(subtype='DIR_PATH')
    filter_folder: BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        try:
            self.directory = str(output_path(context.window_manager.rpc_settings.output,
                                             bpy.data.filepath, check_exists=False).parent)
        except (ValueError, OSError):
            self.directory = str(Path(bpy.data.filepath).parent) if bpy.data.filepath else ''
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        directory = Path(bpy.path.abspath(self.directory))
        if not directory.is_absolute() or not directory.is_dir():
            self.report({'ERROR'}, '请选择存在的完整目录。')
            return {'CANCELLED'}
        p = context.window_manager.rpc_settings
        try:
            filename = output_path(p.output, bpy.data.filepath, check_exists=False).name
        except (ValueError, OSError):
            filename = 'render_ready.blend'
        p.output = str(directory / filename)
        return {'FINISHED'}


class RPC_OT_open(bpy.types.Operator):
    bl_idname = 'rpc.open_result'
    bl_label = '打开结果'
    bl_description = '打开新文件；当前有未保存修改时会确认'

    def invoke(self, context, event):
        if bpy.data.is_dirty:
            return context.window_manager.invoke_confirm(self, event, message='当前场景有未保存修改，打开结果会替换当前场景。')
        return self.execute(context)

    def execute(self, context):
        path = context.window_manager.rpc_settings.result
        if not Path(path).is_file():
            self.report({'ERROR'}, '结果文件不存在。')
            return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
        return {'FINISHED'}


class RPC_PT_main(bpy.types.Panel):
    bl_label = 'ABC 渲染套用 · 0.8.3'
    bl_idname = 'RPC_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ABC渲染'

    def draw(self, context):
        layout = self.layout
        p = context.window_manager.rpc_settings
        for key in ['template', 'abc']:
            layout.prop(p, key)
        layout.prop(p, 'output')
        layout.operator('rpc.choose_output_directory', icon='FILE_FOLDER')
        layout.label(text='完整路径可直接粘贴到上方输入框')
        layout.prop(p, 'output_fps')
        layout.prop(p, 'camera_warmup_seconds')
        layout.operator('rpc.build', icon='MOD_MESHDEFORM')
        if p.result:
            layout.operator('rpc.open_result', icon='FILE_BLEND')
        import textwrap
        for line in textwrap.wrap(p.status, 32):
            layout.label(text=line)
        if context.scene.get('rpc_transfer'):
            report = json.loads(context.scene['rpc_transfer'])
            layout.separator()
            layout.label(text=f"{report['character']} · {report['frame_range'][0]}–{report['frame_range'][1]} 帧")
            layout.label(text='F12 查看透眼、描边与辉光。')


CLASSES = [RPC_Settings, RPC_OT_build, RPC_OT_output_directory, RPC_OT_open, RPC_PT_main]


def register():
    from . import style_panel, camera_panel
    style_panel.register()
    camera_panel.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.rpc_settings = PointerProperty(type=RPC_Settings)
    if _job is not None and not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=.5)


def unregister():
    from . import style_panel, camera_panel
    camera_panel.unregister()
    style_panel.unregister()
    # A running worker owns an independent new file; let it finish safely.
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    if hasattr(bpy.types.WindowManager, 'rpc_settings'):
        del bpy.types.WindowManager.rpc_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
