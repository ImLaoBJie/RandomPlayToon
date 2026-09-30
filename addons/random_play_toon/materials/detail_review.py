"""Shared 0.7.5 repairs: hair, alpha policy, connected hulls and face/neck seams.

Only attributes/materials/modifiers are added. Rest geometry and UVs stay intact.
Character choices are separate from these common mechanisms.
"""
import bpy,json,colorsys
import numpy as np
from pathlib import Path
from mathutils.kdtree import KDTree
from .. import style_panel as ui
from .style_upgrade import Graph,add,source,output
from .vivian_parity import color_value

def restore_verified_hair_maps(r,identity,assets=None):
    """Migrate old scenes from explicit, audited profile bindings.

    Fresh reconstruction already loads these through materials.build.
    """
    from .decoder import build_decoder,image_node
    profile=json.loads((Path(__file__).parents[1]/'specializations/profiles'/(identity+'.json')).read_text(encoding='utf8'))
    for e in r['materials']:
        if e['role']!='hair':continue
        mat=bpy.data.materials[e['material']];q=Graph(mat.node_tree)
        if mat.node_tree.nodes.get('已审核的控制通道'):continue
        binding=profile['materials'][e['slot']]
        if not all(k in binding['maps'] for k in ['NormalMap','LightMap','MaterialMap']):continue
        dec=q.node('ShaderNodeGroup','已审核的控制通道');dec.node_tree=build_decoder();q.put(output(q,r['global'],'Normal Strength'),dec.inputs['Normal Strength'])
        for kind in ['NormalMap','LightMap','MaterialMap']:
            filename=binding['maps'][kind]['file']
            if assets:
                path=Path(assets)/filename
                import hashlib
                if hashlib.sha256(path.read_bytes()).hexdigest()!=binding['maps'][kind]['sha256']:raise ValueError('Verified control map changed: '+filename)
                tex=image_node(mat.node_tree,str(path),data=True);tex.name=kind+' · Non-Color';tex.image.pack()
            else:
                peer=next(n for other in r['materials'] for n in bpy.data.materials[other['material']].node_tree.nodes if n.type=='TEX_IMAGE' and n.name==kind+' · Non-Color' and n.image and filename in n.image.name)
                tex=q.node('ShaderNodeTexImage',kind+' · Non-Color');tex.image=peer.image
            tex.extension='REPEAT';q.put(mat.node_tree.nodes['DDS V correction'].outputs[0],tex.inputs['Vector']);q.put(tex.outputs['Color'],dec.inputs[kind+' RGB'])
        nm=q.node('ShaderNodeNormalMap','RG 重建 Z；原 UV 切线');nm.uv_map='UVMap';q.put(dec.outputs['Normal TS Encoded'],nm.inputs['Color']);toon=mat.node_tree.nodes['共享 EEVEE 卡通着色'];q.put(nm.outputs[0],toon.inputs['Normal'])
        for key in ['Shadow Bias','Material Slot','Metal Mask','Specular Mask','Smoothness']:q.put(dec.outputs[key],toon.inputs[key])
        # A newly matched MaterialMap also participates in selective eye reveal.
        # Rebuild that branch as well, so migrations match an empty-scene build.
        ao=mat.node_tree.nodes.get('Front bangs only')
        if ao:
            direction=mat.node_tree.nodes['Independent light / head pose'];geo=mat.node_tree.nodes['Surface'];att=mat.node_tree.nodes['Selected front bangs']
            front=output(q,r['global'],'Eye Reveal Front Angle');side=output(q,r['global'],'Eye Reveal Side Angle')
            a=q.math('MINIMUM',front,q.math('SUBTRACT',side,1));b=q.math('MAXIMUM',side,q.math('ADD',front,1))
            fade=q.smooth(q.vec('DOT_PRODUCT',direction.outputs['Head Forward'],geo.outputs['Incoming']),q.math('COSINE',q.math('RADIANS',b)),q.math('COSINE',q.math('RADIANS',a)))
            influence=output(q,r['global'],'Eye Reveal Texture Influence');reveal=q.math('ADD',q.math('SUBTRACT',1,influence),q.math('MULTIPLY',influence,dec.outputs['Eye Reveal Potential']))
            q.put(q.math('MULTIPLY',att.outputs['Fac'],q.math('MULTIPLY',reveal,fade)),ao.inputs['Color'])
        mat['rpt_matching']=binding['matching']

def linear(v):
    v=np.asarray(v);return np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)

def sample(image,uv):
    w,h=image.size;a=np.asarray(image.pixels[:],dtype=np.float32).reshape(h,w,4)
    uv=np.asarray(uv);xy=(uv%1*[w,h]).astype(int);return a[xy[:,1],xy[:,0]]

def surfaces(obj,r):
    uv=obj.data.uv_layers.active.data;out={}
    for e in r['materials']:
        mat=bpy.data.materials[e['material']];ps=[p for p in obj.data.polygons if p.material_index==e['slot']]
        coords=[np.mean([uv[i].uv[:] for i in p.loop_indices],axis=0) for p in ps]
        tex=mat.node_tree.nodes.get('PMX 原色（保留原配色）')
        rgba=sample(tex.image,coords) if tex else np.ones((len(ps),4))
        out[e['slot']]={'faces':ps,'uv':coords,'rgba':rgba,'area':np.array([p.area for p in ps]),'texture':tex}
    return out

def attribute(obj,name,typ,values):
    a=obj.data.attributes.get(name) or obj.data.attributes.new(name,typ,'POINT')
    a.data.foreach_set('vector' if typ=='FLOAT_VECTOR' else 'value',np.asarray(values,dtype=np.float32).ravel());return a.name

def attr_node(q,name):
    n=q.node('ShaderNodeAttribute',name);n.attribute_name=name;return n.outputs

def transparent_surfaces(obj,r,data,options):
    audit=[]
    for e in r['materials']:
        m=bpy.data.materials[e['material']];n=ui.node(e);a=data[e['slot']]['rgba'][:,3];fraction=float(((a>.025)&(a<.975)).mean());role=e['role'];q=Graph(m.node_tree)
        shell=bpy.data.materials.get('RPT_Outline_'+str(e['slot']))
        if role=='hair' and fraction>.015:
            # PMX's fractional hair tint must not make the whole head translucent.
            # True holes remain; the eye compositor handles selective reveal.
            tex=data[e['slot']]['texture'];mix=m.node_tree.nodes['Independent surface alpha']
            add(e,'Hair Coverage Cutoff','发丝镂空阈值',.5,0,1,'05 表面','保留真正发丝镂空，去掉非眼部的整片半透明噪点。')
            q.put(q.math('MULTIPLY',q.math('GREATER_THAN',tex.outputs['Alpha'],n.outputs['Hair Coverage Cutoff']),n.outputs['Opacity']),mix.inputs[0])
            if shell:
                sq=Graph(shell.node_tree);st=shell.node_tree.nodes.get('Source alpha')
                if st:sq.put(sq.math('MULTIPLY',sq.math('GREATER_THAN',st.outputs['Alpha'],output(sq,e,'Hair Coverage Cutoff')),shell.node_tree.nodes['Source opacity'].outputs[0]),shell.node_tree.nodes['Preserve source holes'].inputs[0])
            audit.append({'slot':e['slot'],'policy':'opaque hair plus source cutout','fraction':fraction})
        elif role in {'eye_shadow','eye_highlight'} or (role not in {'eyes','eye_white'} and (fraction>.025 or .001<n.inputs['表面不透明度'].default_value<.999)):
            m.surface_render_method='BLENDED'
            if shell:shell.surface_render_method='BLENDED'
            audit.append({'slot':e['slot'],'policy':'smooth blended transparency','fraction':fraction})
        if role in {'eyes','eye_white'}:
            # A single iris material can contain several overlapping mesh layers
            # (Aria's star and its gradient background). BLENDED does not sort
            # those triangles: keep fragment depth testing for source coverage.
            m.surface_render_method='DITHERED'
            if shell:shell.surface_render_method='DITHERED'
            audit.append({'slot':e['slot'],'policy':'depth-tested iris coverage; overlay masks remain blended','fraction':fraction})
        if role in {'eyes','eye_white','eye_shadow','eye_highlight'} or e['slot'] in options.get('no_outline',[])+options.get('eye_shadow_parts',[]):n.inputs['部位描边倍率'].default_value=0
        if e['slot'] in options.get('inverted_source_shells',[]):
            m.use_backface_culling=True;n.inputs['部位描边倍率'].default_value=0
            audit.append({'slot':e['slot'],'policy':'cull reverse source hull; underlying color texture exists'})
    return audit

def outline_color(r,data):
    colors=[];weights=[]
    for e in r['materials']:
        if e['role']!='hair':continue
        d=data[e['slot']];rgb=d['rgba'][:,:3];sat=rgb.max(1)-rgb.min(1);w=d['area']*d['rgba'][:,3]*np.maximum(sat,.025)
        colors.extend(rgb);weights.extend(w)
    if not colors:return None
    mean=np.average(colors,axis=0,weights=weights);h,s,v=colorsys.rgb_to_hsv(*mean)
    srgb=colorsys.hsv_to_rgb(h,max(.6,min(s,.85)),.20);rgb=tuple(linear(srgb))+(1.,)
    ui.node(r['global']).inputs['描边颜色'].default_value=rgb
    for item in ui.node(r['global']).node_tree.interface.items_tree:
        if item.item_type=='SOCKET' and item.in_out=='INPUT' and item.name=='描边颜色':item.default_value=rgb
    return {'method':'surface-area and saturation weighted hair diffuse mean','srgb_mean':mean.tolist(),'outline_linear':rgb}

def connected_hulls(obj,r,identity):
    shell=bpy.data.objects.get('RPT_OutlineShell')
    if not shell:return
    g=next(m.node_group for m in shell.modifiers if m.type=='NODES' and m.node_group.name.startswith('RPT Inverted hull'))
    q=Graph(g);ext=q.node('GeometryNodeExtrudeMesh','Connected outline with boundary walls');ext.mode='FACES';ext.inputs['Individual'].default_value=False
    # Offset Scale multiplies the already scaled vector, including region mode.
    # Zero here collapses the entire outline; another width squares it.
    q.put(g.nodes['Deformed source'].outputs[0],ext.inputs['Mesh']);q.put(g.nodes['Thickness'].outputs[0],ext.inputs['Offset']);ext.inputs['Offset Scale'].default_value=1
    keep=q.math('MAXIMUM',ext.outputs['Top'],ext.outputs['Side']);delete=q.node('GeometryNodeDeleteGeometry','Keep expanded surface and boundary walls');delete.domain='FACE';delete.mode='ALL'
    q.put(ext.outputs['Mesh'],delete.inputs['Geometry']);q.put(q.math('SUBTRACT',1,keep),delete.inputs['Selection']);q.put(delete.outputs[0],g.nodes['Reverse winding'].inputs[0])
    for e in r['materials']:
        if e['role']=='hair':ui.node(e).inputs['部位描边倍率'].default_value=.65
    from .outline_regions import author_eye_rims,wire_filter,apply_boundary_policy
    author_eye_rims(obj,r);wire_filter(g,r)
    apply_boundary_policy(g,r,identity)

def hair(obj,r,data,options):
    tuning=options.get('hair',{})
    hids={i for e in r['materials'] if e['role']=='hair' for p in data[e['slot']]['faces'] for i in p.vertices}
    if not hids:return []
    faceids={i for e in r['materials'] if e['role']=='face' for p in data[e['slot']]['faces'] for i in p.vertices}
    # Helmeted characters still have mapped hair. A face is only a convenient
    # coordinate reference for the optional (disabled) geometric band tool.
    if not faceids:faceids=hids
    pos=np.asarray([v.co[:] for v in obj.data.vertices]);fp=pos[list(faceids)];height=float(np.ptp(fp[:,2]));eyeids={i for e in r['materials'] if e['role']=='eyes' for p in data[e['slot']]['faces'] for i in p.vertices}
    eye=float(np.mean(pos[list(eyeids),2])) if eyeids else float(fp[:,2].mean());top=float(fp[:,2].max())
    if hids:top=max(top,float(np.quantile(pos[list(hids),2],.98)))
    width=max(np.ptp(fp[:,0])*.5,.03)
    z=(pos[:,2]-eye)/max(top-eye,.04)-.10*np.minimum((pos[:,0]/width)**2,2)
    attribute(obj,'RPT_HairBandHeight','FLOAT',z)
    audit=[]
    for e in r['materials']:
        if e['role']!='hair':continue
        m=bpy.data.materials[e['material']];q=Graph(m.node_tree);n=ui.node(e);toon=m.node_tree.nodes['共享 EEVEE 卡通着色'];em=m.node_tree.nodes['Final stylized surface'];dec=m.node_tree.nodes.get('已审核的控制通道')
        base=source(toon.inputs['Base Color']);q.put(0.,toon.inputs['Specular Strength'])
        if 'gain' in tuning:n.inputs['部位亮度'].default_value=tuning['gain']
        add(e,'Hair Peak Limit','头发亮部柔化上限',.90,.4,2,'05 头发','只柔化最亮峰值，保留头发底色和暗部；不会像旧版压暗整片头发。')
        n.inputs['头发亮部柔化上限'].default_value=tuning.get('peak_limit',.90)
        add(e,'Hair Highlights','发束图形高光强度',.24,0,2,'05 头发','使用已核验控制图中的发束高光形状；不以横向白带替代缺失贴图。')
        n.inputs['发束图形高光强度'].default_value=tuning.get('highlight_strength',.18 if dec is None else .28)
        add(e,'Hair Ambient','头发环境提亮',.22,0,1,'05 头发','补足卡通头发暗部，保留原色；不制造辉光。')
        n.inputs['头发环境提亮'].default_value=tuning.get('ambient',.22)
        add(e,'Hair Ring Fill','辅助环状高光',0.,0,1,'05 头发','可选的几何造型工具，默认关闭；未确认的贴图高光不以横向白带代替。')
        add(e,'Hair Ring Height','环状高光位置',.52,0,1,'05 头发','相对眼睛至头顶的高光高度。')
        add(e,'Hair Ring Width','环状高光宽度',.04,.01,.3,'05 头发','控制辅助高光带的软宽度。')
        coord=attr_node(q,'RPT_HairBandHeight')['Fac'];dist=q.math('ABSOLUTE',q.math('SUBTRACT',coord,n.outputs['Hair Ring Height']))
        ring=q.math('SUBTRACT',1,q.smooth(dist,n.outputs['Hair Ring Width'],q.math('MULTIPLY',n.outputs['Hair Ring Width'],2.2)))
        mask=dec.outputs['Specular Mask'] if dec else 0.
        mask=q.math('MAXIMUM',q.math('POWER',q.math('MAXIMUM',mask,0),.7),q.math('MULTIPLY',ring,n.outputs['Hair Ring Fill']))
        normal=source(toon.inputs['Normal']);direction=m.node_tree.nodes['Independent light / head pose'].outputs['Light Direction'];facing=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,direction),0)
        band=q.math('MULTIPLY',mask,q.math('MULTIPLY',n.outputs['Hair Highlights'],output(q,r['global'],'Global Specular')))
        band=q.math('MULTIPLY',band,q.math('ADD',.5,q.math('MULTIPLY',facing,.5)))
        ambient=q.vec('SCALE',base,q.math('MULTIPLY',source(toon.inputs['Key Gain']),output(q,r['global'],'Display Light')))
        color=q.mix(toon.outputs['Color'],ambient,n.outputs['Hair Ambient'])
        boost=q.math('ADD',1,q.math('MULTIPLY',output(q,r['global'],'Studio Mode'),q.math('SUBTRACT',output(q,r['global'],'Studio Emission'),1)))
        glow=q.vec('SCALE',base,q.math('MULTIPLY',n.outputs['Glow Strength'],boost))
        # A pale tint reads on dark/red hair without increasing diffuse exposure.
        tint=q.mix(base,(1,1,1,1),tuning.get('highlight_white_mix',.28))
        final=q.vec('ADD',color,q.vec('SCALE',tint,band))
        sep=q.node('ShaderNodeSeparateColor','Hair highlight shoulder');q.put(final,sep.inputs[0]);peak=q.math('MAXIMUM',q.math('MAXIMUM',sep.outputs[0],sep.outputs[1]),sep.outputs[2])
        limit=n.outputs['Hair Peak Limit'];knee=q.math('MULTIPLY',limit,.8);span=q.math('SUBTRACT',limit,knee);excess=q.math('MAXIMUM',q.math('SUBTRACT',peak,knee),0)
        shoulder=q.math('ADD',q.math('MINIMUM',peak,knee),q.math('DIVIDE',q.math('MULTIPLY',span,excess),q.math('ADD',span,excess)))
        q.put(q.vec('ADD',q.vec('SCALE',final,q.math('DIVIDE',shoulder,q.math('MAXIMUM',peak,.0001))),glow),em.inputs['Color'])
        audit.append({'slot':e['slot'],'mapped_band':dec is not None,'ring_fill':n.inputs['辅助环状高光'].default_value})
    return audit

def neck_bridge(obj,r,data):
    face=[e for e in r['materials'] if e['role']=='face'];skin=[e for e in r['materials'] if e['role']=='skin']
    if not face or not skin:return {'seeds':0}
    pos=np.asarray([v.co[:] for v in obj.data.vertices]);me=obj.data;uv=me.uv_layers.active.data
    skinids={i for e in skin for p in data[e['slot']]['faces'] for i in p.vertices};tree=KDTree(len(skinids))
    for i in skinids:tree.insert(pos[i],i)
    tree.balance();seeds={};faceids={i for e in face for p in data[e['slot']]['faces'] for i in p.vertices};fp=pos[list(faceids)];height=np.ptp(fp[:,2]);field=me.attributes.get('rpt_face_direction')
    if not field:return {'seeds':0}
    for e in face:
        tex=data[e['slot']]['texture']
        if not tex:continue
        loops=[li for p in data[e['slot']]['faces'] for li in p.loop_indices];cols=linear(sample(tex.image,[uv[li].uv[:] for li in loops])[:,:3])
        for li,col in zip(loops,cols):
            vi=me.loops[li].vertex_index;co=pos[vi]
            if co[2]>fp[:,2].min()+height*.4:continue
            hit=tree.find(co)
            if hit and hit[2]<.00008:seeds[tuple(np.round(co,6))]=(co,col,np.array(field.data[vi].vector[:]))
    if len(seeds)<4:return {'seeds':len(seeds),'status':'no verified coincident face/skin seam'}
    seedpos=np.array([a[0] for a in seeds.values()]);col=np.array([a[1] for a in seeds.values()]);normal=np.array([a[2] for a in seeds.values()]);colors=np.zeros_like(pos);normals=np.zeros_like(pos);blend=np.zeros(len(pos));active=faceids|skinids
    for i in active:
        ds=np.linalg.norm(seedpos-pos[i],axis=1);near=np.argsort(ds)[:3];w=1/np.maximum(ds[near],1e-8)**4;w/=w.sum();colors[i]=(col[near]*w[:,None]).sum(0);normals[i]=(normal[near]*w[:,None]).sum(0)
        distance=ds.min()
        if i in faceids:
            amount=np.clip((height*.11-distance)/(height*.065),0,1)
        else:
            # Vivian's solution: keep the entire exposed neck in the same
            # face response, fading BELOW the collar rather than across it.
            bottom=seedpos[:,2].min()-height*.40
            width=max(abs(seedpos[:,0]).max()+height*.08,height*.23)
            inside=abs(pos[i,0])<width and seedpos[:,1].min()-height*.12<pos[i,1]<seedpos[:,1].max()+height*.12 and pos[i,2]<seedpos[:,2].max()+height*.08
            amount=np.clip((pos[i,2]-bottom)/(height*.075),0,1) if inside else 0.
        blend[i]=amount*amount*(3-2*amount)
    attribute(obj,'RPT_NeckColor','FLOAT_VECTOR',colors);attribute(obj,'RPT_NeckDirection','FLOAT_VECTOR',normals);attribute(obj,'RPT_NeckBlend','FLOAT',blend)
    baseentry=face[0]
    for e in face+skin:
        m=bpy.data.materials[e['material']];q=Graph(m.node_tree);em=m.node_tree.nodes['Final stylized surface'];original=source(em.inputs['Color']);toon=m.node_tree.nodes['共享 EEVEE 卡通着色'];direction=m.node_tree.nodes['Independent light / head pose']
        sh=q.node('ShaderNodeGroup','Shared face-neck boundary shading');sh.node_tree=toon.node_tree
        for label in ['Light Direction','Key Tint','Scene Shadow Strength']:q.put(source(toon.inputs[label]),sh.inputs[label])
        def face_control(key):return ui.node(baseentry).outputs[key] if e is baseentry else output(q,baseentry,key)
        threshold=q.mix(face_control('Local Threshold'),output(q,r['global'],'Body Threshold'),face_control('Use Global Lighting'))
        softness=q.math('MULTIPLY',q.mix(face_control('Local Width'),output(q,r['global'],'Body Softness'),face_control('Use Global Lighting')),face_control('Local Softness'))
        q.put(threshold,sh.inputs['Threshold']);q.put(softness,sh.inputs['Softness']);q.put(q.math('MULTIPLY',output(q,r['global'],'Key Gain'),face_control('Local Gain')),sh.inputs['Key Gain'])
        q.put(0.,sh.inputs['Rim Strength']);q.put(0.,sh.inputs['Specular Strength']);q.put(0.,sh.inputs['Bias Strength'])
        tint=ui.node(baseentry).outputs['Base Tint'] if e is baseentry else color_value(q,baseentry,'Base Tint')
        color=q.mix(attr_node(q,'RPT_NeckColor')['Vector'],tint,1,mode='MULTIPLY');q.put(color,sh.inputs['Base Color'])
        sn=q.node('ShaderNodeSeparateXYZ','Seam head direction');q.put(attr_node(q,'RPT_NeckDirection')['Vector'],sn.inputs[0]);world=q.vec('ADD',q.vec('ADD',q.vec('SCALE',direction.outputs['Head Right'],sn.outputs[0]),q.vec('SCALE',direction.outputs['Head Forward'],sn.outputs[1])),q.vec('SCALE',direction.outputs['Head Up'],sn.outputs[2]));q.put(q.vec('NORMALIZE',world),sh.inputs['Normal'])
        # Exactly the same face shadow response on both sides of the seam.
        shadow=ui.node(baseentry).outputs['Shadow Tint'] if e is baseentry else color_value(q,baseentry,'Shadow Tint');sep=q.node('ShaderNodeSeparateColor','Seam shadow');q.put(shadow,sep.inputs[0]);comb=q.node('ShaderNodeCombineColor','Seam shadow depth')
        for i in range(3):q.put(q.math('POWER',sep.outputs[i],output(q,r['global'],'Display Shadow')),comb.inputs[i])
        q.put(q.mix(shadow,comb.outputs[0],output(q,r['global'],'Studio Mode')),sh.inputs['Shadow Tint']);q.put(q.mix(original,sh.outputs['Color'],attr_node(q,'RPT_NeckBlend')['Fac']),em.inputs['Color'])
    return {'seeds':len(seeds),'active_vertices':int((blend>0).sum()),'method':'Vivian-style two-sided boundary sampling; short face fade and neck continuation below collar'}

def profile_details(obj,r,data,options):
    for e in r['materials']:
        m=bpy.data.materials[e['material']];n=ui.node(e);q=Graph(m.node_tree);toon=m.node_tree.nodes['共享 EEVEE 卡通着色'];em=m.node_tree.nodes['Final stylized surface'];slot=e['slot']
        if slot in options.get('skin_parts',[]):
            e['role']='skin';m['rpt_role']='skin';n.inputs['阴影乘色'].default_value=(.76,.57,.60,1)
        if slot in options.get('eye_shadow_parts',[]):
            n.inputs['原色乘色'].default_value=options['eye_shadow_color'];n.inputs['表面不透明度'].default_value=.4
        if str(slot) in options.get('eye_overlay_opacity',{}):n.inputs['表面不透明度'].default_value=options['eye_overlay_opacity'][str(slot)]
        if slot in options.get('soft_specular_parts',[]) or e['role']=='skin':
            n.inputs['部位高光倍率'].default_value=min(n.inputs['部位高光倍率'].default_value,.075)
            n.inputs['金属反光强度'].default_value=0
            n.inputs['部位高光宽度倍率'].default_value=4.
        if slot in options.get('metal_parts',[]):
            n.inputs['金属反光强度'].default_value=0;n.inputs['部位高光倍率'].default_value=.06;n.inputs['部位亮度'].default_value=.72;n.inputs['部位高光宽度倍率'].default_value=5.
            base=source(toon.inputs['Base Color']);geo=m.node_tree.nodes['Surface'];direction=m.node_tree.nodes['Independent light / head pose'];normal=source(toon.inputs['Normal']);h=q.vec('NORMALIZE',q.vec('ADD',direction.outputs['Light Direction'],geo.outputs['Incoming']));nh=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,h),0)
            add(e,'Broad Metal Reflection','宽幅金属反射',.18,0,2,'04 金属与塑料','宽而柔和的金属反射，避免把灰色金属抬成整片白色。')
            ref=q.vec('SCALE',(.65,.68,.73),q.math('MULTIPLY',q.math('POWER',nh,5),n.outputs['Broad Metal Reflection']))
            q.put(q.vec('ADD',source(em.inputs['Color']),ref),em.inputs['Color'])
        if str(slot) in options.get('emission_tints',{}):
            add(e,'Authored Emission Tint','部位发光色',tuple(options['emission_tints'][str(slot)]),0,1,'06 自发光','特效颜色独立于 PMX 中用于占位的原色，可手动修改。')
            q.put(q.vec('SCALE',n.outputs['Authored Emission Tint'],q.math('ADD',.6,q.math('MULTIPLY',n.outputs['Glow Strength'],output(q,r['global'],'Studio Emission')))),em.inputs['Color'])
        if slot in options.get('stocking_parts',[]):
            # The supplied stocking mesh is also the leg surface: a Transparent
            # BSDF would reveal the black background, not underlying skin.
            add(e,'Stocking Skin Show','丝袜透肤比例',.28,0,.75,'05 丝袜','单层腿部网格的透肤近似：混入肤色底层，避免直接透明后露出背景。')
            add(e,'Stocking Skin Tint','丝袜底层肤色',(.82,.58,.51,1),0,1,'05 丝袜','薄袜下面的肤色，可独立调节。')
            base=source(toon.inputs['Base Color']);q.put(q.mix(base,n.outputs['Stocking Skin Tint'],n.outputs['Stocking Skin Show']),toon.inputs['Base Color']);n.inputs['部位高光倍率'].default_value=.09;n.inputs['部位高光宽度倍率'].default_value=5.;n.inputs['部位过渡倍率'].default_value=3.
        if options.get('bangs_without_map_attenuation') and e['role']=='hair':
            aov=m.node_tree.nodes.get('Front bangs only')
            if aov:
                att=attr_node(q,'rpt_bangs')['Fac'];direction=m.node_tree.nodes['Independent light / head pose'];geo=m.node_tree.nodes['Surface']
                front=output(q,r['global'],'Eye Reveal Front Angle');side=q.math('MAXIMUM',output(q,r['global'],'Eye Reveal Side Angle'),q.math('ADD',front,1))
                angle=q.smooth(q.vec('DOT_PRODUCT',direction.outputs['Head Forward'],geo.outputs['Incoming']),q.math('COSINE',q.math('RADIANS',side)),q.math('COSINE',q.math('RADIANS',front)))
                q.put(q.math('MULTIPLY',att,angle),aov.inputs['Color'])

def apply(scene,identity,verified_assets=None):
    if scene.get('rpt_detail_revision')==1:return
    r=ui.registry(scene)
    if not r.get('generic'):return
    obj=bpy.data.objects[r['mesh_object']];restore_verified_hair_maps(r,identity,verified_assets);data=surfaces(obj,r);options=json.loads((Path(__file__).parents[1]/'specializations/detail_profiles.json').read_text(encoding='utf8')).get(identity,{})
    for e in [r['global']]+r['materials']:
        e.setdefault('legacy_label_sets',[]).append([s.name for s in ui.node(e).inputs])
    audit={'transparency':transparent_surfaces(obj,r,data,options),'outline_color':outline_color(r,data)}
    from .outline_regions import apply_default_scope
    audit['outline_scope']=apply_default_scope(r,identity)
    connected_hulls(obj,r,identity);audit['hair']=hair(obj,r,data,options);profile_details(obj,r,data,options);audit['neck']=neck_bridge(obj,r,data)
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False);scene['zzz_stage6_defaults']=json.dumps(ui.capture(scene),ensure_ascii=False)
    scene['rpt_detail_revision']=1;scene['rpt_detail_audit']=json.dumps(audit,ensure_ascii=False);ui.refresh(scene)
