"""Uncalibrated PMX fallback; never borrow another model's slot calibration."""
import os
import re
from pathlib import Path


def material_role(name, english=''):
    text=(name+' '+english).lower()
    for words,role in [
        (('眉','睫','目线','二重','brow','lash'),'brows_lashes'),
        (('目影','eye shadow'),'eye_shadow'),
        (('目光','目高光','眼高光','eye highlight'),'eye_highlight'),
        (('白目','目白','眼白','sclera','eye white'),'eye_white'),
        (('口线','唇','lip'),'mouth_line'),
        (('口舌','舌','齿','歯','teeth','tongue','mouth'),'mouth'),
        (('颜','顔','脸','face'),'face'),
        (('髮','髪','头发','頭髮','前发','后发','後发','前髪','hair','bang'),'hair'),
        (('肌','皮肤','皮膚','skin'),'skin'),
        (('金属','metal'),'metal'),
        (('自发光','emissive'),'emissive'),
        (('武器','weapon'),'weapon'),
        (('翅膀','wing'),'wing'),
        (('袜','stocking'),'stocking'),
    ]:
        if any(word in text for word in words):
            return 'hair_overlay' if role=='hair' and ('+' in text or '高光' in text) else role
    if re.fullmatch(r'(目|眼|眼睛|瞳|瞳孔)\d*',name) or any(x in text for x in ['iris','pupil','eye']):return 'eyes'
    if re.fullmatch(r'(口|口内)\d*',name):return 'mouth'
    if re.fullmatch(r'(脖子|颈|頸|首|neck)\d*',name.lower()):return 'skin'
    if name in {'发','发+'}:return 'hair_overlay' if '+' in name else 'hair'
    return 'cloth'


def profile(path, fingerprint):
    from .._vendor.mmd_tools.core import pmx
    path=Path(path).resolve()
    try:model=pmx.load(str(path))
    except (pmx.InvalidFileError,pmx.UnsupportedVersionError,ValueError,IndexError) as exc:
        raise ValueError('无法读取 PMX：'+str(exc)) from exc
    if not model.vertices or not model.faces or not model.materials:
        raise ValueError('PMX 缺少可构建的网格或材质')
    materials=[];start=0
    for index,mat in enumerate(model.materials):
        texture=os.path.relpath(model.textures[mat.texture].path,path.parent) if mat.texture>=0 else None
        role=material_role(mat.name,mat.name_e)
        materials.append({'index':index,'name':mat.name or f'Material {index}',
            'role':role,'source_texture':texture,'maps':{},'matching':'pmx_only',
            'diffuse':list(mat.diffuse),'draw_flags':int(mat.is_double_sided),
            'face_start':start,'face_count':mat.vertex_count//3,'alpha_mode':'source_pmx_alpha'})
        start+=mat.vertex_count//3
    if start!=len(model.faces):raise ValueError('PMX 材质面数与网格不一致')
    return {'schema':1,'id':'Generic_'+fingerprint[:12],
        'character':path.stem,'kind':'uncalibrated','variant':'default',
        'uncalibrated':True,'pmx_sha256':fingerprint,'import_scale':.08,
        'materials':materials,'parameter_overrides':{},'zero_alpha_filter':True,
        'warnings':[{'reason':'uncalibrated_pmx','action':'按材质名称推断部位并使用 PMX 原色；不接入未经校验的 DDS 控制图，不套用其他角色的专用校准。'}],
        'capabilities':{'face':any(m['role']=='face' for m in materials),
                        'eyes':any(m['role']=='eyes' for m in materials)}}
