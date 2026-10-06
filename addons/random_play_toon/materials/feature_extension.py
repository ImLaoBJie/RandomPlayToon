"""Optional directional patches, authored-band width, and isolated eye emission.

V2 art-direction studies inform the patch/AOV and projected-outline approach.
All render-time controls live in sockets; no frame handler or external cache.
"""
import json
import math
import re
import bpy
import numpy as np
from .. import style_panel as ui
from .graph import Graph
from .style_upgrade import add, source
from .controls import output, drive
from .vivian_parity import color_value

REVISION = 1
PATCH_AOV = 'RPT Directional Patch'
VIVIAN_ROLES = {0:'face',1:'face',2:'brows_lashes',3:'eyes',4:'eye_highlight',5:'eye_white',6:'mouth_line',7:'mouth',8:'mouth',9:'eye_shadow',10:'cloth',11:'skin',12:'cloth',13:'stocking',14:'hair',16:'gem'}


def stabilize_control_paths(r):
    """Old libraries contain index-based angle drivers. Adding a panel can move
    sockets: convert these paths to stable socket labels BEFORE any interface edit.
    Also preserve user F-curves and driver variable references to these controls.
    """
    nodes={ui.node(e) for e in [r['global']]+r['materials']}
    pattern=re.compile(r'nodes\[("(?:[^"\\]|\\.)*")\]\.(inputs|outputs)\[(\d+)\]')
    def rewrite(owner,path):
        tree=owner.node_tree if isinstance(owner,bpy.types.Material) else owner
        if not isinstance(tree,bpy.types.NodeTree):return path
        def sub(m):
            n=tree.nodes.get(json.loads(m.group(1)))
            if n not in nodes:return m.group(0)
            sockets=getattr(n,m.group(2));idx=int(m.group(3))
            if idx>=len(sockets):raise ValueError('控制节点动画索引无效：'+path)
            return 'nodes['+m.group(1)+'].'+m.group(2)+'['+json.dumps(sockets[idx].name,ensure_ascii=False)+']'
        return pattern.sub(sub,path)
    owners=list(bpy.data.node_groups)+[m.node_tree for m in bpy.data.materials if m.use_nodes]+list(bpy.data.objects)+list(bpy.data.scenes)
    for owner in owners:
        ad=owner.animation_data
        if not ad:continue
        for fc in ad.drivers:
            fc.data_path=rewrite(owner,fc.data_path)
            for var in fc.driver.variables:
                for target in var.targets:
                    if target.id and target.data_path:target.data_path=rewrite(target.id,target.data_path)
        actions=([ad.action] if ad.action else [])+[strip.action for track in ad.nla_tracks for strip in track.strips if strip.action]
        for action in actions:
            curves=list(getattr(action,'fcurves',[]))
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in getattr(strip,'channelbags',[]):curves.extend(bag.fcurves)
            for fc in curves:fc.data_path=rewrite(owner,fc.data_path)


def role(entry):
    return entry.get('role') or VIVIAN_ROLES.get(entry['slot'], 'cloth')


def disconnect(socket, value=0.):
    for link in list(socket.links):
        socket.id_data.links.remove(link)
    socket.default_value = value


def replace_consumers(q, old, new, targets):
    for target in targets:
        q.put(new, target)


def active_emission(mat):
    """Reach only shaders used by the active material output, not debug branches."""
    root = next(n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    found=[];seen=set()
    def visit(n):
        if n.as_pointer() in seen:return
        seen.add(n.as_pointer())
        if n.type == 'EMISSION':found.append(n);return
        for s in n.inputs:
            if s.type=='SHADER':
                for link in s.links:visit(link.from_node)
    visit(root)
    return found


def add_controls(r):
    g=r['global']
    specs=[
      ('Patch Enabled','启用独立亮块',False,0,1,'11 独立亮块','独立虚拟方向的风格化亮块；默认关闭。'),
      ('Patch Azimuth','亮块水平角（度）',-118.,-180,180,'11 独立亮块','世界空间方向，与角色主光独立，可关键帧。'),
      ('Patch Elevation','亮块俯仰角（度）',48.,-89,89,'11 独立亮块','独立虚拟方向俯仰角。'),
      ('Patch Color','亮块颜色',(1.,.96,.86,1.),0,1,'11 独立亮块','亮块和它的专用辉光共用此颜色。'),
      ('Patch Strength','亮块强度',1.,0,5,'11 独立亮块','控制亮块输出亮度，不调整其他材质曝光。'),
      ('Patch Width','亮块宽度',.44,.01,.95,'11 独立亮块','沿掠视表面扩展亮块范围。'),
      ('Patch Softness','亮块边缘柔度',.025,.001,.3,'11 独立亮块','控制亮块边缘过渡宽度。'),
      ('Patch Bloom Enabled','启用亮块辉光',True,0,1,'11 独立亮块','只对亮块AOV产生辉光，与原画面辉光分别控制。'),
      ('Patch Bloom Strength','亮块辉光强度',.32,0,5,'11 独立亮块','0关闭光晕但保留亮块。'),
      ('Patch Bloom Size','亮块辉光范围',.32,0,1,'11 独立亮块','最终合成中光晕的扩散范围。'),
      ('Patch Bloom Threshold','亮块辉光阈值',.15,0,5,'11 独立亮块','仅检测亮块，不检测原白衣或眼睛。'),
      ('Iris Glow','瞳孔自发光强度',0.,0,8,'06 眼部自发光','仅虹膜/瞳孔材质，独立于眼白、眉睫和透眼比例。'),
      ('Iris Glow Color','瞳孔发光颜色',(1.,1.,1.,1.),0,1,'06 眼部自发光','乘以虹膜原色，白色保留原配色。'),
      ('Sclera Glow','眼白自发光强度',0.,0,8,'06 眼部自发光','仅眼白；不包含眼高光贴片、眉毛和睫毛。'),
      ('Sclera Glow Color','眼白发光颜色',(1.,1.,1.,1.),0,1,'06 眼部自发光','眼白单独的发光乘色。'),
      ('Outline Projected','启用贴合视角描边',True,0,1,'07 描边','在当前渲染相机平面内扩张，限制短边与屏幕宽度；支持正交和透视。'),
      ('Outline Pixel Cap','描边最大像素宽度',3.,.5,12,'07 描边','输出分辨率下的外扩上限，防止大幅加粗时露出宽壳。'),
      ('Outline View Variation','描边视角变化',.65,0,1,'07 描边','随变形后的法线与当前相机角度改变宽度。'),
    ]
    for spec in specs:add(g,*spec)


def direction(q, glob):
    a=q.math('MULTIPLY',output(q,glob,'Patch Azimuth'),math.pi/180)
    e=q.math('MULTIPLY',output(q,glob,'Patch Elevation'),math.pi/180)
    n=q.node('ShaderNodeCombineXYZ','RPT Independent patch direction')
    q.put(q.math('MULTIPLY',q.math('COSINE',a),q.math('COSINE',e)),n.inputs[0])
    q.put(q.math('MULTIPLY',q.math('SINE',a),q.math('COSINE',e)),n.inputs[1])
    q.put(q.math('SINE',e),n.inputs[2])
    return n.outputs[0]


def eye_emission(mat, entry, r):
    kind=role(entry);q=Graph(mat.node_tree);controls=ui.node(entry)
    if kind in {'brows_lashes','eye_shadow','mouth_line','eye_highlight'}:
        # These surfaces can be visible through bangs, but are not emitters.
        for key in ['Glow Strength','Emission Strength','Review Glow']:
            if key in controls.outputs:
                for link in list(controls.outputs[key].links):disconnect(link.to_socket)
        for item in entry['entries']:
            if item['key'] in {'Glow Strength','Glow Tint','Emission Strength','Review Glow','Custom Glow Mask','Use Glow Mask'}:
                item['disabled_reason']='眉睫、眼影与高光贴片不参与眼部自发光'
        return 'excluded'
    if kind not in {'eyes','eye_white'}:return None
    key='Iris Glow' if kind=='eyes' else 'Sclera Glow'
    toon=next((n for n in mat.node_tree.nodes if n.type=='GROUP' and n.node_tree and n.node_tree.name.startswith('ZZZ_ToonSurface')),None)
    base=source(toon.inputs['Base Color']) if toon else None
    if base is None:
        n=mat.node_tree.nodes.get('ZZZ_Stage6 原色乘色')
        if n:base=n.outputs[0]
        else:
            tex=next((n for n in mat.node_tree.nodes if n.type=='TEX_IMAGE'),None)
            base=tex.outputs['Color'] if tex else (1.,1.,1.)
    glow=q.vec('SCALE',q.vec('MULTIPLY',base,color_value(q,r['global'],key+' Color')),output(q,r['global'],key),'RPT '+key+' only')
    for em in active_emission(mat):
        old=source(em.inputs['Color'])
        # Update the exact same color used by premultiplied eye-reveal AOVs.
        targets=[l.to_socket for l in old.links] if isinstance(old,bpy.types.NodeSocket) else [em.inputs['Color']]
        new=q.vec('ADD',old,glow,'RPT isolated '+kind+' emission')
        replace_consumers(q,old,new,targets)
    return kind


def morphology(signal, radius, maximum):
    op=np.maximum if maximum else np.minimum
    result=signal
    for axis in (0,1):
        pad=[(0,0),(0,0)];pad[axis]=(radius,radius)
        src=np.pad(result,pad,mode='edge');result=np.array(signal,copy=True)
        for offset in range(2*radius+1):
            sl=[slice(None),slice(None)];sl[axis]=slice(offset,offset+signal.shape[axis])
            if offset==0:result=src[tuple(sl)].copy()
            else:op(result,src[tuple(sl)],out=result)
    return result


def hair_width(mat,entry):
    if role(entry)!='hair':return None
    q=Graph(mat.node_tree)
    decoder=next((n for n in mat.node_tree.nodes if n.type=='GROUP' and n.node_tree and n.node_tree.name.startswith('ZZZ_PackedChannels')),None)
    if decoder is None or not decoder.inputs['LightMap RGB'].is_linked:return {'slot':entry['slot'],'status':'no audited LightMap'}
    tex=decoder.inputs['LightMap RGB'].links[0].from_node
    if tex.type!='TEX_IMAGE' or not tex.image:return {'slot':entry['slot'],'status':'custom LightMap graph; unchanged'}
    add(entry,'Hair Band Width','原贴图高光扩缩（像素）',0.,-12,12,'05 头发','0保留当前效果；正值扩宽、负值收窄原发束图形。像素以1024贴图为基准，不生成横向光环。')
    add(entry,'Hair Band Gain','原贴图高光倍率',1.,0,3,'05 头发','只缩放已审核发束高光遮罩；默认1。')
    image=tex.image;w,h=image.size[:];pixels=np.empty(w*h*4,np.float32);image.pixels.foreach_get(pixels);mask=pixels.reshape(h,w,4)[:,:,2]
    generated=bpy.data.images.get('RPT Band Extents '+image.name)
    if generated is None:
        # Store grayscale morphology endpoints in RGB plus alpha (data, not opacity).
        a=max(1,round(4*max(w,h)/1024));b=max(a+1,round(12*max(w,h)/1024))
        channels=[morphology(mask,a,True),morphology(mask,b,True),morphology(mask,a,False),morphology(mask,b,False)]
        generated=bpy.data.images.new('RPT Band Extents '+image.name,width=w,height=h,alpha=True,float_buffer=False,is_data=True)
        generated.alpha_mode='CHANNEL_PACKED';generated.pixels.foreach_set(np.stack(channels,axis=-1).astype(np.float32).ravel());generated.pack()
    nt=q.node('ShaderNodeTexImage','RPT Authored band dilation and erosion');nt.image=generated;nt.interpolation=tex.interpolation;nt.extension=tex.extension
    q.put(source(tex.inputs['Vector']),nt.inputs['Vector'])
    sep=q.node('ShaderNodeSeparateColor','RPT Band endpoint channels');q.put(nt.outputs['Color'],sep.inputs[0])
    original=decoder.outputs['Specular Mask'];targets=[l.to_socket for l in original.links]
    width=ui.node(entry).outputs['Hair Band Width'];positive=q.math('GREATER_THAN',width,0);amount=q.math('ABSOLUTE',width)
    near=q.mix(sep.outputs['Blue'],sep.outputs['Red'],positive)
    far=q.mix(nt.outputs['Alpha'],sep.outputs['Green'],positive)
    short=q.mix(original,near,q.math('MINIMUM',q.math('DIVIDE',amount,4),1))
    extended=q.mix(short,far,q.math('MAXIMUM',q.math('DIVIDE',q.math('SUBTRACT',amount,4),8),0))
    result=q.math('MULTIPLY',extended,ui.node(entry).outputs['Hair Band Gain'],'RPT Preserve authored highlight default')
    replace_consumers(q,original,result,targets)
    return {'slot':entry['slot'],'source':image.name,'endpoints':generated.name,'default_width':0,'default_gain':1}


def patches(mat,entry,r):
    if role(entry) in {'eyes','eye_white','eye_highlight','brows_lashes','eye_shadow','mouth','mouth_line','hair_overlay','emissive'}:return False
    q=Graph(mat.node_tree);g=r['global'];n=ui.node(entry)
    add(entry,'Patch Part','部位亮块倍率',.45 if role(entry) in {'face','hair'} else 1.,0,1,'11 独立亮块','限定此部位的独立亮块；0关闭。')
    geo=q.node('ShaderNodeNewGeometry','RPT Patch geometry normal');normal=geo.outputs['Normal'];view=geo.outputs['Incoming']
    edge=q.math('SUBTRACT',1,q.math('ABSOLUTE',q.vec('DOT_PRODUCT',normal,view)))
    center=q.math('SUBTRACT',1,output(q,g,'Patch Width'));soft=output(q,g,'Patch Softness')
    silhouette=q.smooth(edge,q.math('SUBTRACT',center,soft),q.math('ADD',center,soft))
    side=q.smooth(q.vec('DOT_PRODUCT',normal,direction(q,g)),q.math('SUBTRACT',.2,soft),q.math('ADD',.2,soft))
    mask=q.math('MULTIPLY',q.math('MULTIPLY',silhouette,side),q.math('MULTIPLY',output(q,g,'Patch Enabled'),n.outputs['Patch Part']))
    color=q.vec('SCALE',color_value(q,g,'Patch Color'),output(q,g,'Patch Strength'))
    for em in active_emission(mat):q.put(q.mix(source(em.inputs['Color']),color,mask,'RPT Directional colored patch'),em.inputs['Color'])
    aov=q.node('ShaderNodeOutputAOV',PATCH_AOV);aov.aov_name=PATCH_AOV;q.put(q.vec('SCALE',color,mask),aov.inputs['Color'])
    return True


def patch_compositor(scene,r):
    layer=scene.view_layers.get('ZZZ_Beauty') or scene.view_layers[0]
    if PATCH_AOV not in layer.aovs:a=layer.aovs.add();a.name=PATCH_AOV;a.type='COLOR'
    t=scene.compositing_node_group;q=Graph(t);g=r['global']
    render=q.node('CompositorNodeRLayers','RPT Patch pass');render.layer=layer.name
    bloom=q.node('CompositorNodeGlare','RPT Isolated patch bloom');bloom.inputs['Type'].default_value='Bloom';bloom.inputs['Strength'].default_value=1
    q.put(render.outputs[PATCH_AOV],bloom.inputs['Image']);drive(bloom.inputs['Size'],g,'Patch Bloom Size');drive(bloom.inputs['Threshold'],g,'Patch Bloom Threshold')
    amount=q.math('MULTIPLY',output(q,g,'Patch Bloom Strength'),q.math('MULTIPLY',output(q,g,'Patch Enabled'),output(q,g,'Patch Bloom Enabled')))
    halo=q.mix(bloom.outputs['Glare'],amount,1,'RPT Patch glow intensity','MULTIPLY')
    for legacy in list(t.nodes):
        if legacy.type=='GLARE' and legacy!=bloom and legacy.inputs['Image'].is_linked:
            old=source(legacy.inputs['Image'])
            # Isolate from generic bloom to prevent a second uncontrolled halo.
            diff=q.mix(old,render.outputs[PATCH_AOV],1,'RPT Remove patch from generic bloom','SUBTRACT')
            clamp=q.mix(diff,(0,0,0,1),1,'RPT Nonnegative generic bloom','LIGHTEN');q.put(clamp,legacy.inputs['Image'])
    go=next(n for n in t.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output)
    old=source(go.inputs[0]);added=q.mix(old,halo,1,'RPT Add isolated patch glow','ADD')
    sep=q.node('CompositorNodeSeparateColor','RPT Existing output alpha');q.put(old,sep.inputs[0])
    hs=q.node('CompositorNodeSeparateColor','RPT Halo opacity');q.put(halo,hs.inputs[0])
    alpha=q.math('MINIMUM',1,q.math('ADD',sep.outputs['Alpha'],q.math('MAXIMUM',hs.outputs[0],q.math('MAXIMUM',hs.outputs[1],hs.outputs[2]))))
    sa=q.node('CompositorNodeSetAlpha','RPT Preserve output and halo alpha');sa.inputs['Type'].default_value='Replace Alpha';q.put(added,sa.inputs['Image']);q.put(alpha,sa.inputs['Alpha']);q.put(sa.outputs[0],go.inputs[0])


def projected_outline(scene,r):
    groups={m.node_group for o in scene.objects for m in o.modifiers if m.type=='NODES' and m.node_group and m.node_group.name.startswith(('RPT Inverted hull','ZZZ_OutlineShell'))}
    report=[]
    for tree in groups:
        q=Graph(tree);offset=tree.nodes.get('Thickness') or tree.nodes.get('SCALE')
        if not offset:continue
        old=offset.outputs['Vector'];targets=[l.to_socket for l in old.links];width=source(offset.inputs['Scale'])
        normal=q.node('GeometryNodeInputNormal','RPT Deformed outline normal').outputs[0]
        blur=q.node('GeometryNodeBlurAttribute','RPT Smooth projected outline');blur.data_type='FLOAT_VECTOR';blur.inputs['Iterations'].default_value=2;q.put(normal,blur.inputs['Value'])
        normal=q.vec('NORMALIZE',q.vec('ADD',q.vec('SCALE',normal,.75),q.vec('SCALE',blur.outputs['Value'],.25)))
        camera=q.node('GeometryNodeInputActiveCamera','RPT Current render camera')
        ci=q.node('GeometryNodeCameraInfo','RPT Current camera optics');q.put(camera.outputs[0],ci.inputs['Camera'])
        ob=q.node('GeometryNodeObjectInfo','RPT Camera in mesh space');ob.transform_space='RELATIVE';q.put(camera.outputs[0],ob.inputs['Object'])
        axis=q.node('ShaderNodeVectorRotate','RPT Camera parallel axis');axis.rotation_type='EULER_XYZ';axis.inputs['Vector'].default_value=(0,0,1);q.put(ob.outputs['Rotation'],axis.inputs['Rotation'])
        pos=q.node('GeometryNodeInputPosition','RPT Evaluated position').outputs[0]
        ray=q.vec('SUBTRACT',ob.outputs['Location'],pos)
        def vmix(a,b,f):return q.vec('ADD',q.vec('SCALE',a,q.math('SUBTRACT',1,f)),q.vec('SCALE',b,f))
        def fmix(a,b,f):return q.math('ADD',q.math('MULTIPLY',a,q.math('SUBTRACT',1,f)),q.math('MULTIPLY',b,f))
        view=q.vec('NORMALIZE',vmix(q.vec('NORMALIZE',ray),axis.outputs[0],ci.outputs['Is Orthographic']))
        projected=q.vec('SUBTRACT',normal,q.vec('SCALE',view,q.vec('DOT_PRODUCT',normal,view)))
        silhouette=q.math('SUBTRACT',1,q.math('ABSOLUTE',q.vec('DOT_PRODUCT',normal,view)))
        variation=q.math('ADD',q.math('SUBTRACT',1,output(q,r['global'],'Outline View Variation')),q.math('MULTIPLY',output(q,r['global'],'Outline View Variation'),silhouette))
        # Find the shortest incident deformed edge, not a rest-pose clearance.
        edges=q.node('GeometryNodeInputMeshEdgeVertices','RPT Local edge positions')
        length=q.vec('DISTANCE',edges.outputs['Position 1'],edges.outputs['Position 2'])
        index=q.node('GeometryNodeInputIndex','RPT Outline vertex index')
        adjacent=q.node('GeometryNodeEdgesOfVertex','RPT Shortest incident edge');q.put(index.outputs[0],adjacent.inputs['Vertex Index']);q.put(length,adjacent.inputs['Weights']);adjacent.inputs['Sort Index'].default_value=0
        sample=q.node('GeometryNodeSampleIndex','RPT Edge clearance');sample.data_type='FLOAT';sample.domain='EDGE';sample.clamp=True
        inp=next(n for n in tree.nodes if n.type=='GROUP_INPUT');q.put(inp.outputs[0],sample.inputs['Geometry']);q.put(length,sample.inputs['Value']);q.put(adjacent.outputs['Edge Index'],sample.inputs['Index'])
        clearance=q.math('MULTIPLY',sample.outputs['Value'],.22)
        # Camera optics node and scene driver follow active-camera switches.
        pixels=q.node('ShaderNodeValue','RPT Effective render extent');driver=pixels.outputs[0].driver_add('default_value').driver;driver.type='SCRIPTED'
        for name,path in [('rx','render.resolution_x'),('ry','render.resolution_y'),('pct','render.resolution_percentage'),('ax','render.pixel_aspect_x'),('ay','render.pixel_aspect_y')]:
            v=driver.variables.new();v.name=name;v.type='SINGLE_PROP';v.targets[0].id_type='SCENE';v.targets[0].id=scene;v.targets[0].data_path=path
        driver.expression='max(rx,ry*ay/max(ax,0.001))*max(pct,1)/100'
        sensor=q.node('ShaderNodeSeparateXYZ','RPT Camera sensor');q.put(ci.outputs['Sensor'],sensor.inputs[0])
        depth=q.math('ABSOLUTE',q.vec('DOT_PRODUCT',ray,axis.outputs[0]))
        extent=q.math('MULTIPLY',depth,q.math('DIVIDE',sensor.outputs['X'],q.math('MAXIMUM',ci.outputs['Focal Length'],.001)))
        # Relative object info already gives perspective depth in local units.
        selfnode=q.node('GeometryNodeSelfObject','RPT Outline object');selfinfo=q.node('GeometryNodeObjectInfo','RPT Outline object scale');selfinfo.transform_space='ORIGINAL';q.put(selfnode.outputs[0],selfinfo.inputs['Object'])
        os=q.node('ShaderNodeSeparateXYZ','RPT Object uniform scale');q.put(selfinfo.outputs['Scale'],os.inputs[0])
        ortho=q.math('DIVIDE',ci.outputs['Orthographic Scale'],q.math('MAXIMUM',q.math('ABSOLUTE',os.outputs['X']),.0001))
        per_pixel=q.math('DIVIDE',fmix(extent,ortho,ci.outputs['Is Orthographic']),pixels.outputs[0])
        cap=q.math('MULTIPLY',per_pixel,output(q,r['global'],'Outline Pixel Cap'))
        bounded=q.math('MINIMUM',q.math('MULTIPLY',width,variation),q.math('MINIMUM',clearance,cap))
        new=q.vec('SCALE',projected,bounded)
        # Explicit vector interpolation works in Geometry Nodes as well.
        enabled=output(q,r['global'],'Outline Projected')
        result=q.vec('ADD',q.vec('SCALE',old,q.math('SUBTRACT',1,enabled)),q.vec('SCALE',new,enabled),'RPT Bounded camera-plane outline')
        replace_consumers(q,old,result,targets)
        report.append(tree.name)
    return report


def repair_bangs_pass(scene):
    """Keep Vivian bang coverage in a dedicated colour AOV on Blender 5.2."""
    t=scene.compositing_node_group
    if not t or 'Hair AND visible eyes' not in t.nodes:return
    mats=[m for m in bpy.data.materials if m.node_tree and 'ZZZ_EyeReveal ZZZ_BangsPotential' in m.node_tree.nodes]
    if not mats:return
    name='RPT Bangs Coverage'
    for layer in scene.view_layers:
        a=layer.aovs.get(name) or layer.aovs.add();a.name=name;a.type='COLOR'
    for mat in mats:
        q=Graph(mat.node_tree);old=mat.node_tree.nodes['ZZZ_EyeReveal ZZZ_BangsPotential']
        n=mat.node_tree.nodes.get('RPT Stable bangs coverage') or q.node('ShaderNodeOutputAOV','RPT Stable bangs coverage')
        n.aov_name=name;q.put(source(old.inputs['Value']),n.inputs['Color'])
    for n in t.nodes:
        if n.type=='R_LAYERS':n.layer=n.layer
    bpy.context.view_layer.update()
    t.links.new(t.nodes['Beauty - unchanged surfaces'].outputs[name],t.nodes['Hair AND visible eyes'].inputs[0])


def apply(scene):
    repair_bangs_pass(scene)
    if scene.get('rpt_feature_extension')==REVISION:return json.loads(scene['rpt_feature_audit'])
    r=ui.registry(scene)
    if not r.get('global'):raise ValueError('缺少已校准的角色参数注册表')
    old_defaults=json.loads(scene['zzz_stage6_defaults'])
    stabilize_control_paths(r)
    for entry in [r['global']]+r['materials']:
        entry.setdefault('legacy_label_sets',[]).append([s.name for s in ui.node(entry).inputs])
    add_controls(r)
    audit={'eyes':[],'hair':[],'patch_materials':[]}
    for entry in r['materials']:
        mat=bpy.data.materials[entry['material']]
        eye=eye_emission(mat,entry,r)
        if eye:audit['eyes'].append({'slot':entry['slot'],'role':role(entry),'status':eye})
        hair=hair_width(mat,entry)
        if hair:audit['hair'].append(hair)
        if patches(mat,entry,r):audit['patch_materials'].append(entry['slot'])
    patch_compositor(scene,r);audit['outlines']=projected_outline(scene,r)
    # Arrow is only a visual indicator; the two independent angle sockets are authority.
    arrow=bpy.data.objects.new('RPT_IndependentPatchDirection',None);scene.collection.objects.link(arrow);arrow.empty_display_type='SINGLE_ARROW';arrow.empty_display_size=.3;arrow.location=(.45,0,1.7);arrow.hide_render=True
    for idx,key,expr in [(1,'Patch Elevation','pi/2-v*pi/180'),(2,'Patch Azimuth','v*pi/180')]:
        d=arrow.driver_add('rotation_euler',idx).driver;d.type='SCRIPTED';v=d.variables.new();v.name='v';v.type='SINGLE_PROP';v.targets[0].id_type='MATERIAL';v.targets[0].id=bpy.data.materials[r['global']['material']]
        label=next(x['label'] for x in r['global']['entries'] if x['key']==key)
        v.targets[0].data_path='node_tree.nodes['+json.dumps(r['global']['node'])+'].inputs['+json.dumps(label,ensure_ascii=False)+'].default_value';d.expression=expr
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    defaults=ui.capture(scene)
    for mat,values in defaults.items():
        for label in values.keys() & old_defaults.get(mat,{}).keys():values[label]=old_defaults[mat][label]
    scene['zzz_stage6_defaults']=json.dumps(defaults,ensure_ascii=False)
    scene['rpt_feature_extension']=REVISION;scene['rpt_feature_audit']=json.dumps(audit,ensure_ascii=False)
    ui.refresh(scene)
    return audit
