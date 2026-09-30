"""Scene-persistent camera settings and independent import/retiming controls."""
import json
import bpy
from bpy.props import StringProperty, FloatProperty, BoolProperty, PointerProperty
from . import camera


def warmup_get(self):
    defaults = json.loads(self.id_data.get('rpc_transfer', '{}'))
    return float(self.get('warmup_seconds', defaults.get('camera_warmup_seconds', 0)))


def warmup_set(self, value):
    self['warmup_seconds'] = value


class RPC_CameraSettings(bpy.types.PropertyGroup):
    path: StringProperty(name='仅相机 VMD（可选）', subtype='FILE_PATH', description='作者提供的相机动作；角色 retargeted.vmd 不含相机')
    source_fps: FloatProperty(name='相机源帧率', default=30, min=1, max=240, description='原始相机通常为 30；已经烘焙到 60 fps 的相机填 60')
    duration_scale: FloatProperty(name='额外时长倍数', default=1, min=.01, max=100, description='1 保持时长；2 放慢一倍。30→60 fps 已自动换算，不要再填 2')
    warmup_seconds: FloatProperty(name='角色预热时间（秒）', min=0, max=3600, get=warmup_get, set=warmup_set,
        description='默认沿用套用时记录的 ABC 预热。本批为 1 秒；只延后相机，60 fps 下 1 秒为 60 帧')
    start_frame: FloatProperty(name='额外起始偏移（帧）', default=0, min=-100000, max=100000, description='源相机第 0 帧映射到此帧，再加预热偏移；不自动加 1')
    spatial_scale: FloatProperty(name='空间比例', default=.1, min=.00001, max=100, description='每个 MMD 单位对应的米数。默认自动读取 ABC 元数据')
    auto_scale: BoolProperty(name='空间比例跟随 ABC', default=True)
    detect_cuts: BoolProperty(name='保留连续帧切镜', default=True, description='原始相邻一帧的镜头关键帧视为切镜；若相机是逐帧烘焙数据，请关闭')


def settings(scene):
    p = scene.rpc_camera_settings
    return dict(source_fps=p.source_fps, duration_scale=p.duration_scale,
                warmup_seconds=p.warmup_seconds, start_frame=p.start_frame,
                spatial_scale=None if p.auto_scale else p.spatial_scale, detect_cuts=p.detect_cuts)


class RPC_OT_camera_import(bpy.types.Operator):
    bl_idname = 'rpc.import_camera'
    bl_label = '导入相机并按目标帧率采样'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            p = context.scene.rpc_camera_settings
            track = camera.read_vmd(bpy.path.abspath(p.path))
            report = camera.bake(context.scene, track, **settings(context.scene))
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"相机已导入：{report['sampled_frames']} 个采样，原相机保留。")
        return {'FINISHED'}


class RPC_OT_camera_retime(bpy.types.Operator):
    bl_idname = 'rpc.retime_camera'
    bl_label = '按上述设置重新对齐相机'
    bl_description = '从 blend 内保存的原始 VMD 数据重新采样，不反复拉伸现有关键帧；会替换本工具相机上的手动修改'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get('rpc_camera'))

    def execute(self, context):
        try:
            r = json.loads(context.scene['rpc_camera'])
            track = json.loads(bpy.data.texts[r['text']].as_string())
            camera.bake(context.scene, track, **settings(context.scene))
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RPC_OT_sync_fps(bpy.types.Operator):
    bl_idname = 'rpc.sync_fps'
    bl_label = '同步 ABC 时间轴到当前帧率'
    bl_description = '同步本工具烘焙的头部控制、帧范围和相机；保持动作秒数，不修改 ABC 文件'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get('rpc_transfer'))

    def execute(self, context):
        try:
            camera.synchronize_fps(context.scene)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class RPC_PT_camera(bpy.types.Panel):
    bl_label = '可选相机 VMD · 帧率与预热对齐'
    bl_idname = 'RPC_PT_camera'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ABC渲染'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 20

    def draw(self, context):
        scene = context.scene
        p = scene.rpc_camera_settings
        layout = self.layout
        layout.prop(p, 'path')
        layout.prop(p, 'source_fps')
        row = layout.row(align=True)
        row.prop(scene.render, 'resolution_x', text='画面宽')
        row.prop(scene.render, 'resolution_y', text='高')
        row = layout.row(align=True)
        row.prop(scene.render, 'fps', text='目标帧率')
        row.prop(scene.render, 'fps_base', text='除数')
        if scene.get('rpc_transfer'):
            r = json.loads(scene['rpc_transfer'])
            if abs(r['fps']-scene.render.fps/scene.render.fps_base) > 1e-5:
                layout.label(text='帧率已改变，请先同步动作控制', icon='ERROR')
            layout.operator('rpc.sync_fps')
        for key in ['duration_scale','warmup_seconds','start_frame','detect_cuts','auto_scale']:
            layout.prop(p,key)
        if not p.auto_scale:
            layout.prop(p,'spatial_scale')
        factor = scene.render.fps/scene.render.fps_base/p.source_fps*p.duration_scale
        layout.label(text=f'总帧数换算：× {factor:.4g}；时长 × {p.duration_scale:.4g}')
        layout.label(text='30→60：源 30、目标 60、时长 1')
        layout.label(text='预热仅偏移相机，首个镜头保持静止')
        layout.operator('rpc.import_camera', icon='CAMERA_DATA')
        if scene.get('rpc_camera'):
            layout.operator('rpc.retime_camera', icon='TIME')
            layout.label(text='重新对齐会替换本工具相机的手动改动')


CLASSES = [RPC_CameraSettings, RPC_OT_camera_import, RPC_OT_camera_retime, RPC_OT_sync_fps, RPC_PT_camera]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rpc_camera_settings = PointerProperty(type=RPC_CameraSettings)


def unregister():
    del bpy.types.Scene.rpc_camera_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
