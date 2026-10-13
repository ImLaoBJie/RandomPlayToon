"""Optional, view-dependent nose art direction over normalized rest geometry.

No character-name branches, UV edits, textures, frame callbacks or topology edits.
The static POINT field travels with armature/shape-key/Alembic deformation; live
head-frame axes and Geometry.Incoming determine the visible nose shape.
"""
import json
import math
import bpy
import numpy as np
from .. import style_panel as ui
from .graph import Graph, group
from .style_upgrade import add, source
from .controls import output
from .feature_extension import role, stabilize_control_paths, active_emission
from .vivian_parity import color_value

REVISION = 1
ATTRIBUTE = 'rpt_nose_rest'
CATEGORY = '12 风格化鼻影'
SPECS = [
    ('Nose Enabled', '启用风格化鼻影', False, 0, 1, '默认关闭；只作用于鼻子局部，保留原有脸部明暗。'),
    ('Nose Opacity', '鼻影强度', .65, 0, 1, '鼻影与当前脸部颜色的混合强度；0保留原效果。'),
    ('Nose Tint', '鼻影乘色', (.62, .32, .28, 1.), 0, 1, '乘以当前肤色，随原脸部明暗变化；不生成自发光。'),
    ('Nose Width', '鼻影宽度', 1., .2, 3., '相对自动识别脸宽的倍率，不使用固定世界尺寸。'),
    ('Nose Length', '鼻影长度', 1., .2, 3., '相对自动识别脸宽的倍率。'),
    ('Nose Offset X', '鼻影左右偏移', 0., -.06, .06, '以脸宽为单位，微调自动定位；不会修改顶点。'),
    ('Nose Offset Z', '鼻影上下偏移', 0., -.06, .06, '以脸宽为单位，正值向上。'),
    ('Nose Softness', '鼻影边缘柔度', .12, .01, .7, '鼻影形状边缘的过渡宽度。'),
    ('Nose Direction', '鼻影独立方向（度）', 35., -80., 80., '鼻影专用的头部相对方向，不改变主光；正负值选择正面时的不同侧，0在正面淡出。'),
    ('Nose View Follow', '鼻影视角跟随', 1., 0., 2., '1随相机相对头部的转角换侧；0固定在独立方向指定的一侧；更大时换侧更快。'),
    ('Nose Transition', '鼻影换侧过渡（度）', 8., 1., 30., '换侧前先淡出，再从另一侧出现；不在鼻子中间合成色块。'),
    ('Nose Profile Fade', '鼻影侧脸淡出（度）', 70., 40., 85., '超过此角度开始淡出，接近完全侧脸时隐藏。'),
]


def coordinates(obj, entries):
    """Locate the protruding centerline between semantic mouth/eye anchors.

    Input is calibrated PMX rest space (+X right, -Y forward, +Z up), the same
    basis used by the existing head-direction fields. Missing/ambiguous anchors
    are reported instead of putting a guessed mark on an arbitrary mesh.
    """
    me = obj.data
    xyz = np.empty((len(me.vertices), 3), np.float32)
    me.vertices.foreach_get('co', xyz.ravel())
    def ids(kinds):
        slots = {e['slot'] for e in entries if role(e) in kinds}
        return np.array(sorted({i for p in me.polygons if p.material_index in slots for i in p.vertices}), dtype=int)
    fi, ei, mi = ids({'face'}), ids({'eyes', 'eye_white'}), ids({'mouth_line'})
    if not len(mi): mi = ids({'mouth'})
    if min(len(fi), len(ei), len(mi)) < 3:
        raise ValueError('鼻影需要已识别的脸部、眼部和嘴部网格')
    face = xyz[fi]; lo, hi = face.min(0), face.max(0)
    width = float(hi[0]-lo[0]); center = float((hi[0]+lo[0])/2)
    mouth, eye = float(np.median(xyz[mi, 2])), float(np.median(xyz[ei, 2]))
    if width <= 1e-6 or not .1 < (eye-mouth)/width < .65:
        raise ValueError('鼻影脸部比例不可靠，请检查角色语义和静止网格')
    candidates = fi[(abs(face[:, 0]-center) < width*.065) &
                    (face[:, 2] > mouth+(eye-mouth)*.2) &
                    (face[:, 2] < eye-(eye-mouth)*.12)]
    if len(candidates) < 3: raise ValueError('鼻尖候选顶点不足')
    tip_id = int(candidates[np.argmin(xyz[candidates, 1])]); tip = xyz[tip_id].copy()
    tip[0] = center
    if not .25 < (float(tip[2])-mouth)/(eye-mouth) < .88:
        raise ValueError('鼻尖未位于眼口之间，停止自动适配')
    values = (xyz-tip)/width
    # Missing shader attributes evaluate to zero. Offset X so a lost field
    # safely produces an empty mask rather than coloring the entire face.
    values[:, 0] += 2.
    return values, {'method':'semantic eye/mouth anchors + protruding rest centerline',
                    'tip_vertex':tip_id, 'tip':tip.tolist(), 'face_width':width,
                    'eye_z':eye, 'mouth_z':mouth, 'candidate_count':len(candidates)}


def build_group():
    name = 'RPT Stylized Nose v1'
    if name in bpy.data.node_groups: return bpy.data.node_groups[name]
    F, V, C = 'NodeSocketFloat', 'NodeSocketVector', 'NodeSocketColor'
    inputs = [('Original', C, (1,1,1,1)), ('Rest', V, (100,100,100)),
              ('View', V, (0,-1,0)), ('Right', V, (1,0,0)),
              ('Forward', V, (0,-1,0)), ('Up', V, (0,0,1))]
    inputs += [(k, C if isinstance(v,tuple) else F, v) for k,_,v,*_ in SPECS]
    g,q,i,o = group(name, inputs, [('Color',C),('Mask',F)])
    sep=q.node('ShaderNodeSeparateXYZ','Normalized rest nose');q.put(q.vec('SUBTRACT',i['Rest'],(2,0,0)),sep.inputs[0])
    view=q.vec('NORMALIZE',i['View'])
    yaw=q.math('ARCTAN2',q.vec('DOT_PRODUCT',view,i['Right']),q.vec('DOT_PRODUCT',view,i['Forward']))
    angle=q.math('SUBTRACT',q.math('MULTIPLY',yaw,i['Nose View Follow']),q.math('MULTIPLY',i['Nose Direction'],math.pi/180))
    transition=q.math('MULTIPLY',i['Nose Transition'],math.pi/180)
    side=q.math('SIGN',angle)
    turn_fade=q.smooth(q.math('ABSOLUTE',angle),0,transition)
    # Each shape is strictly on one side of the nose. A zero-opacity interval
    # joins the two sides, instead of morphing them into a central nose blotch.
    v=q.math('DIVIDE',q.math('ADD',q.math('SUBTRACT',sep.outputs['Z'],i['Nose Offset Z']),.008),q.math('MULTIPLY',i['Nose Length'],.040))
    u=q.math('DIVIDE',q.math('SUBTRACT',sep.outputs['X'],i['Nose Offset X']),q.math('MULTIPLY',i['Nose Width'],.023))
    u=q.math('SUBTRACT',u,q.math('MULTIPLY',side,q.math('ADD',.48,q.math('MULTIPLY',v,.22))))
    taper=q.math('MAXIMUM',q.math('ADD',.78,q.math('MULTIPLY',v,.16)),.25)
    u=q.math('DIVIDE',u,taper)
    distance=q.math('SQRT',q.math('ADD',q.math('MULTIPLY',u,u),q.math('MULTIPLY',v,v)))
    shape=q.math('SUBTRACT',1,q.smooth(distance,q.math('SUBTRACT',1,i['Nose Softness']),1))
    one_side=q.smooth(q.math('MULTIPLY',q.math('SUBTRACT',sep.outputs['X'],i['Nose Offset X']),side),.0008,.004)
    # Explicit depth and facial-region guard keeps the mark off rear surfaces,
    # inner mouth and the seam, including when the user enlarges the shape.
    depth=q.math('SUBTRACT',1,q.smooth(sep.outputs['Y'],.12,.20))
    horizontal=q.math('SUBTRACT',1,q.smooth(q.math('ABSOLUTE',sep.outputs['X']),.10,.13))
    vertical=q.math('SUBTRACT',1,q.smooth(q.math('ABSOLUTE',sep.outputs['Z']),.10,.13))
    profile=q.math('SUBTRACT',1,q.smooth(q.math('ABSOLUTE',yaw),q.math('MULTIPLY',i['Nose Profile Fade'],math.pi/180),math.radians(89)))
    pitch=q.math('SUBTRACT',1,q.smooth(q.math('ABSOLUTE',q.vec('DOT_PRODUCT',view,i['Up'])),math.sin(math.radians(55)),math.sin(math.radians(80))))
    mask=shape
    for value in [one_side,turn_fade,depth,horizontal,vertical,profile,pitch,i['Nose Enabled'],i['Nose Opacity']]:mask=q.math('MULTIPLY',mask,value)
    tint=q.mix(i['Original'],i['Nose Tint'],1,'Skin-relative nose color','MULTIPLY')
    q.put(q.mix(i['Original'],tint,mask,'Nose off is original'),o['Color']);q.put(mask,o['Mask'])
    g['description']='View-driven local nose art direction; not a recovered game facial SDF.'
    return g


def apply(scene):
    if scene.get('rpt_nose_revision') == REVISION:
        return json.loads(scene['rpt_nose_audit'])
    r=ui.registry(scene);faces=[e for e in r.get('materials',[]) if role(e)=='face']
    if not faces:return {'status':'skipped','reason':'no face materials'}
    obj=bpy.data.objects.get(r.get('mesh_object','Vivian_Mapping'))
    if obj is None: return {'status':'skipped','reason':'no calibrated source mesh'}
    try:values,audit=coordinates(obj,r['materials'])
    except ValueError as exc:
        audit={'status':'skipped','reason':str(exc)}
        scene['rpt_nose_audit']=json.dumps(audit,ensure_ascii=False)
        return audit
    # Inspect all insertion points BEFORE making any edits. Insert before the
    # independent patch branch, leaving patch color/AOV/bloom entirely intact.
    points=[]
    for e in faces:
        mat=bpy.data.materials[e['material']];t=mat.node_tree
        direction=next((n for n in t.nodes if n.type=='GROUP' and all(k in n.outputs for k in ['Head Right','Head Forward','Head Up'])),None)
        if direction is None:raise ValueError('鼻影缺少已绑定的头部方向：'+mat.name)
        patch=t.nodes.get('RPT Directional colored patch')
        targets=[patch.inputs[1]] if patch else [n.inputs['Color'] for n in active_emission(mat)]
        if not targets:raise ValueError('鼻影未找到脸部颜色输出：'+mat.name)
        points.append((mat,direction,targets))
    stabilize_control_paths(r)
    defaults=json.loads(scene.get('zzz_stage6_defaults','{}'))
    glob=r['global'];glob.setdefault('legacy_label_sets',[]).append([s.name for s in ui.node(glob).inputs])
    for k,label,v,lo,hi,desc in SPECS:add(glob,k,label,v,lo,hi,CATEGORY,desc)
    attr=obj.data.attributes.get(ATTRIBUTE) or obj.data.attributes.new(ATTRIBUTE,'FLOAT_VECTOR','POINT')
    attr.data.foreach_set('vector',values.astype(np.float32).ravel());obj.data.update()
    group_tree=build_group()
    for mat,direction,targets in points:
        q=Graph(mat.node_tree)
        att=q.node('ShaderNodeAttribute','RPT Attached nose coordinates');att.attribute_name=ATTRIBUTE
        geo=q.node('ShaderNodeNewGeometry','RPT Nose view')
        for target in targets:
            n=q.node('ShaderNodeGroup','RPT Local nose shadow');n.node_tree=group_tree
            q.put(source(target),n.inputs['Original']);q.put(att.outputs['Vector'],n.inputs['Rest']);q.put(geo.outputs['Incoming'],n.inputs['View'])
            for axis in ['Right','Forward','Up']:q.put(direction.outputs['Head '+axis],n.inputs[axis])
            for k,_,v,*_ in SPECS:q.put(color_value(q,glob,k) if isinstance(v,tuple) else output(q,glob,k),n.inputs[k])
            q.put(n.outputs['Color'],target)
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    new=ui.capture(scene)
    for mat,params in new.items():
        for k in params.keys() & defaults.get(mat,{}).keys():params[k]=defaults[mat][k]
    scene['zzz_stage6_defaults']=json.dumps(new,ensure_ascii=False)
    audit.update(status='installed',materials=[m.name for m,_,_ in points],attribute=ATTRIBUTE,default_enabled=False)
    scene['rpt_nose_revision']=REVISION;scene['rpt_nose_audit']=json.dumps(audit,ensure_ascii=False)
    ui.refresh(scene)
    return audit
