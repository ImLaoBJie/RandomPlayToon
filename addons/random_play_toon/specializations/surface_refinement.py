"""Calibrated transparency and reflection exceptions for the reviewed profiles."""
import bpy,json
from .. import style_panel as ui
from ..materials.style_upgrade import common_controls,source,add,Graph,output,drive

def smooth_transparency(s,r,identity):
    changes=[]
    for e in r['materials']:
        role=e['role'];mat=bpy.data.materials[e['material']];n=ui.node(e)
        if role in ['eye_shadow','eye_highlight']:
            mat.surface_render_method='BLENDED'
            # Eye decals do not need a second translucent inverted hull.
            n.inputs['部位描边倍率'].default_value=0
            changes.append({'slot':e['slot'],'change':'eye decal BLENDED; original color and alpha preserved'})
        if identity=='Alice' and role=='hair':
            # PMX authored fractional bangs show whole forehead through the hair.
            # Use solid coverage here; selective eye visibility remains the AOV compositor.
            q=Graph(mat.node_tree);mix=mat.node_tree.nodes['Independent surface alpha'];tex=mat.node_tree.nodes['PMX 原色（保留原配色）']
            add(e,'Hair Coverage Cutoff','发丝镂空阈值',.5,0,1,'05 表面','仅镂空原纹理透明区域；刘海不再整体半透明，眼眉由局部透眼合成保留。')
            q.put(q.math('MULTIPLY',q.math('GREATER_THAN',tex.outputs['Alpha'],n.outputs['Hair Coverage Cutoff']),n.outputs['Opacity']),mix.inputs[0])
            shell=bpy.data.materials.get('RPT_Outline_'+str(e['slot']))
            if shell:
                sq=Graph(shell.node_tree);st=shell.node_tree.nodes['Source alpha'];sm=shell.node_tree.nodes['Preserve source holes']
                sq.put(sq.math('MULTIPLY',sq.math('GREATER_THAN',st.outputs['Alpha'],output(sq,e,'Hair Coverage Cutoff')),shell.node_tree.nodes['Source opacity'].outputs[0]),sm.inputs[0])
            changes.append({'slot':e['slot'],'change':'hair source cutout + opaque bangs; selective eyes retained'})
    return changes

def reflection(s,r,identity):
    """Same real-light/virtual-light split as Vivian, with profile-specific masks."""
    glob=r['global'];gn=ui.node(glob);is_metal=identity=='Pyrois'
    gn.inputs['基础高光强度'].default_value=.25 if is_metal else .18
    gn.inputs['基础高光宽度'].default_value=2.5 if is_metal else 5.
    gn.inputs['辉光强度'].default_value=.45 if is_metal else .18
    gn.inputs['辉光亮度阈值'].default_value=.9 if is_metal else 1.2
    gn.inputs['光晕扩散范围'].default_value=.25
    for e in r['materials']:
        if is_metal and e['role']!='metal':continue
        if not is_metal and e['slot'] not in [0,1,6,7,8,9,10,11]:continue
        n=ui.node(e);mat=bpy.data.materials[e['material']];q=Graph(mat.node_tree);toon=mat.node_tree.nodes['共享 EEVEE 卡通着色'];geo=mat.node_tree.nodes['Surface'];d=mat.node_tree.nodes['Independent light / head pose'];dec=mat.node_tree.nodes.get('已审核的控制通道')
        add(e,'Surface Reflection','表面反射强度',1.35 if is_metal else .12,0,5,'04 金属与塑料','随光向和视角变化的反射；独立展示使用虚拟反光，场景模式使用 EEVEE Glossy。')
        add(e,'Surface Roughness','表面反射粗糙度',.3 if is_metal else .62,.04,1,'04 金属与塑料','越低反光越集中，越高越宽。区别于原卡通高光宽度。')
        add(e,'Diffuse Retention','反射区底色保留',.32 if is_metal else 1.,0,1,'04 金属与塑料','仅在反射遮罩内降低原底色亮度，避免亮底色与反射叠加成白块。')
        if is_metal and e['slot'] in [0,1]:
            n.inputs['表面反射强度'].default_value=.22
            n.inputs['表面反射粗糙度'].default_value=.4
            n.inputs['反射区底色保留'].default_value=.8
        if not is_metal:n.inputs['部位高光倍率'].default_value=.6
        n.inputs['金属反光强度'].default_value=0 # Old uniform brightening is replaced.
        normal=source(toon.inputs['Normal']);base=source(toon.inputs['Base Color'])
        mask=dec.outputs['Metal Mask'] if is_metal and dec else 1.
        if not is_metal and e['slot'] in [6,7]:
            # Use material mask for shell accents; broad low-strength dielectric remains.
            mask=q.math('ADD',.25,q.math('MULTIPLY',dec.outputs['Specular Mask'],.75)) if dec else 1.
        h=q.vec('NORMALIZE',q.vec('ADD',d.outputs['Light Direction'],geo.outputs['Incoming']));nh=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,h),0)
        rough=n.outputs['Surface Roughness'];exponent=q.math('DIVIDE',2,q.math('MAXIMUM',q.math('MULTIPLY',rough,rough),.025));lobe=q.math('POWER',nh,exponent)
        # A second large virtual card provides a readable band on curved armor.
        side=q.vec('NORMALIZE',q.vec('ADD',q.vec('SCALE',d.outputs['Light Direction'],-1),(0,0,.45)))
        sh=q.vec('NORMALIZE',q.vec('ADD',side,geo.outputs['Incoming']));secondary=q.math('POWER',q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,sh),0),q.math('MULTIPLY',exponent,.45))
        nv=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,geo.outputs['Incoming']),0);edge=q.math('POWER',q.math('SUBTRACT',1,nv),3)
        amplitude=q.math('MULTIPLY',mask,n.outputs['Surface Reflection']);light=q.math('ADD',q.math('MULTIPLY',lobe,2.8),q.math('MULTIPLY',secondary,1.4 if is_metal else .65))
        light=q.math('ADD',light,q.math('MULTIPLY',edge,.4 if is_metal else .08))
        tint=q.mix((.7,.82,1,1),(1,1,1,1),lobe) if is_metal else (1,1,1)
        virtual=q.vec('SCALE',tint,q.math('MULTIPLY',amplitude,light))
        glossy=q.node('ShaderNodeBsdfGlossy','Review native EEVEE reflection');q.put(q.vec('SCALE',tint,amplitude),glossy.inputs['Color']);q.put(rough,glossy.inputs['Roughness']);q.put(normal,glossy.inputs['Normal'])
        sr=q.node('ShaderNodeShaderToRGB','Review scene reflection');q.put(glossy.outputs[0],sr.inputs[0]);ref=q.mix(sr.outputs['Color'],virtual,output(q,glob,'Studio Mode'))
        em=mat.node_tree.nodes['Final stylized surface'];old=source(em.inputs['Color']);atten=q.math('SUBTRACT',1,q.math('MULTIPLY',mask,q.math('SUBTRACT',1,n.outputs['Diffuse Retention'])))
        q.put(q.vec('ADD',q.vec('SCALE',old,atten),ref),em.inputs['Color'])
        mat['rpt_review_reflection']='Vivian-style scene/virtual split; not full scene ray reflection'
    if is_metal:
        for slot,strength,tint in [(3,7.,(.18,.32,1.,1.)),(2,8.,(.002,.006,1.,1.))]:
            e=next(e for e in r['materials'] if e['slot']==slot);n=ui.node(e);mat=bpy.data.materials[e['material']];q=Graph(mat.node_tree)
            add(e,'Review Glow','能量发光强度',strength,0,20,'06 自发光','该 PMX 独立能量部位的发光；不扩散到其他材质。')
            add(e,'Review Glow Tint','能量发光颜色',tint,0,1,'06 自发光','独立能量颜色；支持核心亮到白色及蓝色光晕。')
            em=mat.node_tree.nodes['Final stylized surface'];q.put(q.vec('ADD',source(em.inputs['Color']),q.vec('SCALE',n.outputs['Review Glow Tint'],n.outputs['Review Glow'])),em.inputs['Color'])

def tune_parity(r,identity):
    """Local exceptions under identical shared Vivian defaults."""
    if identity in {'Alice','SunnaMaid'}:
        for e in r['materials']:
            n=ui.node(e)
            if e['role']=='hair' and '发束图形高光强度' in n.inputs:
                n.inputs['发束图形高光强度'].default_value=.20
                if identity=='Alice':n.inputs['部位亮度'].default_value=.88
    if identity=='Pyrois':
        entry=next(e for e in r['materials'] if e['slot']==3);n=ui.node(entry)
        n.inputs['能量发光强度'].default_value=1.5
        n.inputs['能量发光颜色'].default_value=(.3,.45,1,1)
        n.inputs['自发光强度'].default_value=0
        add(entry,'Core Glow Radius','核心发光范围',.43,.1,1,'06 自发光','中心亮点的相对半径；使用随骨骼变形的静止坐标，不受镜像 UV 分岛影响。')
        add(entry,'Core Ring Brightness','核心暗环亮度',.055,0,.5,'06 自发光','两层周边环的底色亮度，独立于中心发光强度。')
        obj=bpy.data.objects[r['mesh_object']]
        ids={i for p in obj.data.polygons if p.material_index==3 for i in p.vertices}
        coords=[obj.data.vertices[i].co for i in ids]
        low=[min(v[i] for v in coords) for i in range(3)];high=[max(v[i] for v in coords) for i in range(3)]
        center=tuple((a+b)*.5 for a,b in zip(low,high));inverse=(2/(high[0]-low[0]),0.,2/(high[2]-low[2]))
        # Store rest coordinates, not a vertex-sampled radius: interpolation then
        # LENGTH keeps the small central disk round even across its large triangles.
        attr=obj.data.attributes.get('RPT_PyroisCoreRest') or obj.data.attributes.new('RPT_PyroisCoreRest','FLOAT_VECTOR','POINT')
        for v in obj.data.vertices:attr.data[v.index].vector=v.co
        mat=bpy.data.materials[entry['material']];q=Graph(mat.node_tree)
        position=q.node('ShaderNodeAttribute','Core rest coordinates');position.attribute_name=attr.name
        radius=q.vec('LENGTH',q.vec('MULTIPLY',q.vec('SUBTRACT',position.outputs['Vector'],center),inverse));extent=n.outputs['Core Glow Radius']
        fall=q.math('SUBTRACT',1,q.smooth(radius,q.math('MULTIPLY',extent,.35),extent))
        # Keep the authored two rings dark; emission has no residual outer floor.
        em=mat.node_tree.nodes['Final stylized surface'];final=em.inputs['Color'].links[0].from_node
        q.put(q.vec('SCALE',source(final.inputs[0]),n.outputs['Core Ring Brightness']),final.inputs[0])
        sinks=[l.to_socket for l in n.outputs['Review Glow'].links];scaled=q.math('MULTIPLY',n.outputs['Review Glow'],fall)
        for socket in sinks:q.put(scaled,socket)
        mat['rpt_core_mask']='single rest-space center; dark authored rings; no outer emission floor'
        ui.node(next(e for e in r['materials'] if e['slot']==2)).inputs['能量发光强度'].default_value=5.
    if identity=='AriaRobotDiscordant':
        for e in r['materials']:
            n=ui.node(e)
            if '表面反射强度' in n.inputs:
                n.inputs['表面反射强度'].default_value=.035
                n.inputs['表面反射粗糙度'].default_value=.72
                n.inputs['部位高光倍率'].default_value*=.4

def apply(scene,identity):
    if scene.get('rpt_surface_refinement')==1:return json.loads(scene['rpt_surface_review'])['transparency']
    r=ui.registry(scene)
    for e in [r['global']]+r['materials']:e['legacy_labels']=[s.name for s in ui.node(e).inputs]
    common_controls(scene,r);changes=smooth_transparency(scene,r,identity)
    if identity in ['Pyrois','AriaRobotDiscordant']:reflection(scene,r,identity)
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False);scene['zzz_stage6_defaults']=json.dumps(ui.capture(scene),ensure_ascii=False)
    scene['rpt_surface_review']=json.dumps({'identity':identity,'status':'surface refinement 0.7.3','transparency':changes},ensure_ascii=False)
    scene['rpt_surface_refinement']=1
    from ..portable import embed_panel
    embed_panel();ui.register();ui.refresh(scene)
    return changes
