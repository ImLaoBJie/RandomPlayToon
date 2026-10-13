"""Optional Vivian face-only brightness; following global is exactly neutral."""
import json
import bpy
from .. import style_panel as ui
from .style_upgrade import Graph,add,output
from .feature_extension import stabilize_control_paths

def apply(scene):
    if scene.get('rpt_face_brightness_revision')==1:return
    r=ui.registry(scene)
    if r.get('generic'):return
    glob=r['global'];gn=ui.node(glob)
    groups={n.node_tree for e in r['materials'] for n in bpy.data.materials[e['material']].node_tree.nodes if n.type=='GROUP' and n.node_tree and n.node_tree.name.startswith('ZZZ_FaceDirection_v1')}
    if not groups:raise ValueError('缺少薇薇安脸部着色组')
    # Resolve existing brightness drivers before inserting any new controls.
    display_sources={}
    for g in groups:
        sockets=[]
        for f in g.animation_data.drivers if g.animation_data else []:
            if any('inputs["展示亮面亮度"]' in t.data_path for v in f.driver.variables for t in v.targets):
                sockets.append(g.path_resolve(f.data_path.rsplit('.',1)[0]))
        if not sockets:raise ValueError('脸部亮面控制结构不匹配：'+g.name)
        display_sources[g]=sockets
    stabilize_control_paths(r)
    old_defaults=json.loads(scene['zzz_stage6_defaults'])
    glob.setdefault('legacy_label_sets',[]).append([s.name for s in gn.inputs])
    for key,label,value,lo,hi,desc in [
        ('Face Key Follow Global','脸部受光亮度跟随全局',True,0,1,'默认跟随角色受光亮度；关闭后使用下方脸部独立值。'),
        ('Face Key Gain','脸部角色受光亮度',float(gn.inputs['角色受光亮度'].default_value),0,3,'仅脸部基础受光颜色的倍率；两种光照模式均生效，不改变眼部自发光、头发和衣服。'),
        ('Face Display Follow Global','脸部亮面亮度跟随全局',True,0,1,'默认跟随展示亮面亮度；关闭后使用下方脸部独立值。'),
        ('Face Display Light','脸部展示亮面亮度',float(gn.inputs['展示亮面亮度'].default_value),.5,2,'仅独立光源模式下调整脸部亮面；不调整脸部阴影或其他部位。'),
    ]:add(glob,key,label,value,lo,hi,'02 脸部独立亮度',desc)
    for e in glob['entries']:
        if e['key']=='Face Key Gain':e.update(global_control=True,source_socket='脸部受光亮度跟随全局')
        if e['key']=='Face Display Light':e.update(global_control=True,source_socket='脸部亮面亮度跟随全局')
    for g in groups:
        q=Graph(g)
        old=g.nodes['Inputs'].outputs['Key Gain'];targets=[l.to_socket for l in old.links]
        selected=q.mix(output(q,glob,'Face Key Gain'),old,output(q,glob,'Face Key Follow Global'),'RPT Face key brightness selection')
        for target in targets:q.put(selected,target)
        for old in display_sources[g]:
            targets=[l.to_socket for l in old.links]
            selected=q.mix(output(q,glob,'Face Display Light'),old,output(q,glob,'Face Display Follow Global'),'RPT Face display brightness selection')
            for target in targets:q.put(selected,target)
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    defaults=ui.capture(scene)
    for mat,vals in defaults.items():
        for k in vals.keys() & old_defaults.get(mat,{}).keys():vals[k]=old_defaults[mat][k]
    scene['zzz_stage6_defaults']=json.dumps(defaults,ensure_ascii=False)
    scene['rpt_face_brightness_revision']=1
    ui.refresh(scene)
