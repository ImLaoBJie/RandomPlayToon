"""PMX import used by reconstruction workers, independent of installed add-ons."""
from pathlib import Path
from ctypes import c_float


def prepare_import():
    import bpy
    if not bpy.app.background:
        raise RuntimeError('PMX 导入应在独立后台构建进程中运行。')
    from ._vendor import mmd_tools
    mmd_tools.register_import_properties()


def import_model(filepath, scale):
    path = Path(filepath).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != '.pmx':
        raise ValueError('请选择存在的 PMX 模型文件。')
    prepare_import()
    from ._vendor.mmd_tools.core.pmx.importer import PMXImporter
    # Keep the same import choices as the calibrated MMD Tools operator.
    # In particular, never merge vertices, reorder bones, or translate names.
    PMXImporter().execute(
        filepath=str(path), types={'MESH', 'ARMATURE', 'MORPHS'},
        # Blender FloatProperty passes a float32. Match it to preserve geometry
        # hashes and the calibrated vertex/shape-key coordinates exactly.
        scale=c_float(scale).value,
        clean_model=False, remove_doubles=False, fix_bone_order=False,
        rename_LR_bones=False, import_adduv2_as_vertex_colors=False,
        fix_ik_links=False, ik_loop_factor=5, apply_bone_fixed_axis=False,
        bone_disp_mode='OCTAHEDRAL', translator=None,
        use_mipmap=True, sph_blend_factor=1.0, spa_blend_factor=1.0,
    )
