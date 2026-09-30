"""Selective eye reveal and inverted hulls. Source data stays editable."""
import bpy,numpy as np
from ..materials.graph import Graph
from ..materials.controls import drive,output
BANG='rpt_bangs';EXCLUDE='rpt_duplicate_overlay'

def filter_group(attribute):
    g=bpy.data.node_groups.new('RPT Filter '+attribute,'GeometryNodeTree')
    for direction in ['INPUT','OUTPUT']:g.interface.new_socket(name='Geometry',in_out=direction,socket_type='NodeSocketGeometry')
    q=Graph(g);i=q.node('NodeGroupInput','Original');a=q.node('GeometryNodeInputNamedAttribute',attribute);a.data_type='BOOLEAN';a.inputs['Name'].default_value=attribute
    d=q.node('GeometryNodeDeleteGeometry','Exclude from evaluation');d.domain='FACE';d.mode='ALL';q.put(i.outputs[0],d.inputs['Geometry']);q.put(a.outputs['Attribute'],d.inputs['Selection']);o=q.node('NodeGroupOutput','Evaluated');q.put(d.outputs[0],o.inputs[0]);return g

def authored_attributes(obj,profile):
    me=obj.data;pos=np.array([v.co[:] for v in me.vertices]);roles={m['index']:m['role'] for m in profile['materials']};faces=[p for p in me.polygons if roles[p.material_index]=='face'];eyes=[p for p in me.polygons if roles[p.material_index] in ['eyes','eye_white']]
    report={'bang_faces':0,'duplicate_overlays':[]}
    # Remove a legacy overlay only with exact geometric triangle evidence.
    def tri_key(p):return tuple(sorted(tuple(np.round(pos[i],6)) for i in p.vertices))
    nonoverlay={tri_key(p) for p in me.polygons if roles[p.material_index]!='hair_overlay' and '+' not in profile['materials'][p.material_index]['name']}
    disabled=set()
    for m in profile['materials']:
        if m['role']!='hair_overlay' and '+' not in m['name']:continue
        ps=[p for p in me.polygons if p.material_index==m['index']];fraction=sum(tri_key(p) in nonoverlay for p in ps)/max(1,len(ps))
        if fraction>.98:
            disabled.add(m['index']);report['duplicate_overlays'].append({'slot':m['index'],'exact_position_fraction':fraction,'source_preserved':True})
    attr=me.attributes.new(EXCLUDE,'BOOLEAN','FACE');attr.data.foreach_set('value',[p.material_index in disabled for p in me.polygons]);mod=obj.modifiers.new('RPT · 已验证重复覆盖层（可关闭）','NODES');mod.node_group=filter_group(EXCLUDE)
    selected=set()
    if faces:
        idx=list({v for p in faces for v in p.vertices});facepos=pos[idx];low=facepos.min(0);high=facepos.max(0);center=(low+high)/2;width=max((high[0]-low[0])/2,.01);height=max(high[2]-low[2],.01)
        nx=np.clip((pos[:,0]-center[0])/width,-1,1)*.91;ny=np.sqrt(np.maximum(1-nx*nx,.08));nz=np.clip((pos[:,2]-center[2])/(height*.65),-.85,.8)*.5
        field=np.stack([nx,ny,nz],axis=-1);field/=np.linalg.norm(field,axis=1,keepdims=True)
        attr=me.attributes.new('rpt_face_direction','FLOAT_VECTOR','POINT');attr.data.foreach_set('vector',field.astype(np.float32).ravel())
        report['face_field']={'method':'authored normalized rest face field, not recovered game SDF','bounds':[low.tolist(),high.tolist()]}
        if eyes:
            eye_pos=pos[list({v for p in eyes for v in p.vertices})];front=float(np.median(eye_pos[:,1]));eye_z=float(np.mean(eye_pos[:,2]))
            hair={m['index'] for m in profile['materials'] if m['role']=='hair'}
            explicit={m['index'] for m in profile['materials'] if m['role']=='hair' and ('前' in m['name'])}
            for p in me.polygons:
                if p.material_index not in hair:continue
                c=pos[list(p.vertices)].mean(0)
                # Only the front face envelope. Side/back hair remains an occluder.
                if c[1]<front+.005 and abs(c[0]-center[0])<width*1.1 and low[2]<c[2]<high[2]+height*.35:
                    selected.add(p.index)
            report['bang_selection']='rest-space front-face envelope; must validate poses per profile'
            report['eye_center']=[float(eye_pos[:,0].mean()),front,eye_z]
    attr=me.attributes.new(BANG,'BOOLEAN','FACE');attr.data.foreach_set('value',[p.index in selected for p in me.polygons]);report['bang_faces']=len(selected)
    return report

def width_field(q,registry):
    width=q.node('ShaderNodeValue','全局描边厚度');drive(width.outputs[0],registry['global'],'Outline Width')
    index=q.node('GeometryNodeInputMaterialIndex','原始材质分区');switch=q.node('GeometryNodeIndexSwitch','各部位描边倍率');switch.data_type='FLOAT'
    while len(switch.index_switch_items)<len(registry['materials']):switch.index_switch_items.new()
    q.put(index.outputs[0],switch.inputs['Index'])
    for i,entry in enumerate(registry['materials']):drive(switch.inputs[i+1],entry,'Outline Scale')
    face=q.node('GeometryNodeFieldOnDomain','先按面选择倍率');face.data_type='FLOAT';face.domain='FACE';q.put(switch.outputs[0],face.inputs['Value'])
    return q.math('MULTIPLY',width.outputs[0],face.outputs[0],'全局厚度 × 部位倍率')

def filter_zero_opacity(obj,registry):
    g=bpy.data.node_groups.new('RPT 专用 · 隐藏未启用重合表情面','GeometryNodeTree')
    for direction in ['INPUT','OUTPUT']:g.interface.new_socket(name='Geometry',in_out=direction,socket_type='NodeSocketGeometry')
    q=Graph(g);i=q.node('NodeGroupInput','Original evaluated mesh');idx=q.node('GeometryNodeInputMaterialIndex','原始材质分区');switch=q.node('GeometryNodeIndexSwitch','各部位不透明度');switch.data_type='FLOAT'
    while len(switch.index_switch_items)<len(registry['materials']):switch.index_switch_items.new()
    q.put(idx.outputs[0],switch.inputs['Index'])
    for n,e in enumerate(registry['materials']):drive(switch.inputs[n+1],e,'Opacity')
    d=q.node('GeometryNodeDeleteGeometry','仅排除不透明度为零的面');d.domain='FACE';d.mode='ALL';q.put(i.outputs[0],d.inputs['Geometry']);q.put(q.math('LESS_THAN',switch.outputs[0],.0001),d.inputs['Selection']);out=q.node('NodeGroupOutput','Visible layers');q.put(d.outputs[0],out.inputs[0])
    mod=obj.modifiers.new('RPT · 未启用的重合眼层','NODES');mod.node_group=g

def outline(scene,obj,registry):
    shell=obj.copy();shell.data=obj.data;shell.name='RPT_OutlineShell';scene.collection.objects.link(shell);shell.hide_select=True
    for index,source in enumerate(obj.data.materials):
        mat=bpy.data.materials.new('RPT_Outline_'+str(index));mat.use_nodes=True;mat.use_backface_culling=True;mat.surface_render_method='DITHERED';t=mat.node_tree;t.nodes.clear();q=Graph(t)
        e=q.node('ShaderNodeEmission','Outline')
        for component in range(4):drive(e.inputs['Color'],registry['materials'][index],'Outline Color',component)
        n=q.node('ShaderNodeValue','Source opacity');drive(n.outputs[0],registry['materials'][index],'Opacity');alpha=n.outputs[0]
        original=source.node_tree.nodes.get('PMX 原色（保留原配色）')
        if original:
            tex=q.node('ShaderNodeTexImage','Source alpha');tex.image=original.image;uv=q.node('ShaderNodeUVMap','Original UV');uv.uv_map='UVMap';q.put(uv.outputs[0],tex.inputs['Vector']);alpha=q.math('MULTIPLY',alpha,tex.outputs['Alpha'])
        tr=q.node('ShaderNodeBsdfTransparent','Cutout');mix=q.node('ShaderNodeMixShader','Preserve source holes');q.put(alpha,mix.inputs[0]);q.put(tr.outputs[0],mix.inputs[1]);q.put(e.outputs[0],mix.inputs[2]);o=q.node('ShaderNodeOutputMaterial','Output');q.put(mix.outputs[0],o.inputs[0])
        role=registry['materials'][index]['role']
        if role in ['eyes','eye_white','eye_highlight','brows_lashes']:
            support=q.math('MULTIPLY',alpha,output(q,registry['global'],'Eye Reveal Brow Strength') if role=='brows_lashes' else 1.)
            a=q.node('ShaderNodeOutputAOV','Outline eye support');a.aov_name='RPT Eye';q.put(support,a.inputs['Color'])
            color=q.node('ShaderNodeRGB','Independent outline color')
            for component in range(4):drive(color.outputs[0],registry['materials'][index],'Outline Color',component)
            a=q.node('ShaderNodeOutputAOV','Outline premultiplied color');a.aov_name='RPT Eye Color';q.put(q.vec('SCALE',color.outputs[0],support),a.inputs['Color'])
        shell.material_slots[index].link='OBJECT';shell.material_slots[index].material=mat
    c=shell.constraints.new('COPY_TRANSFORMS');c.target=obj
    g=bpy.data.node_groups.new('RPT Inverted hull','GeometryNodeTree')
    for d in ['INPUT','OUTPUT']:g.interface.new_socket(name='Geometry',in_out=d,socket_type='NodeSocketGeometry')
    q=Graph(g);i=q.node('NodeGroupInput','Deformed source');normal=q.node('GeometryNodeInputNormal','Normal');scale=q.node('ShaderNodeVectorMath','Thickness');scale.operation='SCALE';q.put(normal.outputs[0],scale.inputs[0]);q.put(width_field(q,registry),scale.inputs['Scale'])
    offset=q.node('GeometryNodeSetPosition','Expand');q.put(i.outputs[0],offset.inputs['Geometry']);q.put(scale.outputs[0],offset.inputs['Offset'])
    flip=q.node('GeometryNodeFlipFaces','Reverse winding');q.put(offset.outputs[0],flip.inputs[0]);o=q.node('NodeGroupOutput','Hull');q.put(flip.outputs[0],o.inputs[0])
    mod=shell.modifiers.new('RPT Hull','NODES');mod.node_group=g;return shell

def setup_layers(scene,obj,shell,enabled):
    scene.view_layers[0].name='ZZZ_Beauty'
    if not enabled:return
    main=bpy.data.collections.new('RPT Beauty surfaces');aux=bpy.data.collections.new('RPT Eye visibility surfaces');scene.collection.children.link(main);scene.collection.children.link(aux)
    for src in [obj,shell]:
        for c in list(src.users_collection):c.objects.unlink(src)
        main.objects.link(src);target=src.copy();target.data=src.data;target.name='RPT Eye proxy '+src.name;aux.objects.link(target);target.hide_select=True
        if src==obj:c=target.constraints.new('COPY_TRANSFORMS');c.target=src
        mod=target.modifiers.new('RPT Remove selected bangs','NODES');mod.node_group=filter_group(BANG)
        if src==shell:target.modifiers.move(len(target.modifiers)-1,len(target.modifiers)-2)
    extra=scene.view_layers.new('ZZZ_EyeVisibility')
    for layer in scene.view_layers:
        layer.use_pass_z=True
        for name in ['RPT Hair','RPT Eye']:
            a=layer.aovs.add();a.name=name;a.type='COLOR'
        a=layer.aovs.add();a.name='RPT Eye Color';a.type='COLOR'
        layer.layer_collection.children[aux.name if layer.name=='ZZZ_Beauty' else main.name].exclude=True

def compositor(scene,registry,eye_enabled):
    g=bpy.data.node_groups.new('RPT Final image','CompositorNodeTree');g.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor');scene.compositing_node_group=g;scene.render.use_compositing=True;q=Graph(g)
    a=q.node('CompositorNodeRLayers','Beauty');a.layer='ZZZ_Beauty';color=a.outputs['Image']
    if eye_enabled:
        b=q.node('CompositorNodeRLayers','Actual visible eyes');b.layer='ZZZ_EyeVisibility'
        mask=q.math('MULTIPLY',a.outputs['RPT Hair'],b.outputs['RPT Eye']);behind=q.math('GREATER_THAN',b.outputs['Depth'],q.math('ADD',a.outputs['Depth'],.00001));mask=q.math('MULTIPLY',mask,behind)
        n=q.node('ShaderNodeValue','局部透眼强度');drive(n.outputs[0],registry['global'],'Eye Reveal Strength');mask=q.math('MULTIPLY',mask,n.outputs[0])
        # Beauty AA contains surrounding skin. Use matched premultiplied eye
        # color/coverage passes so pale skin cannot leak into narrow brow edges.
        eye_color=q.mix(b.outputs['RPT Eye Color'],q.math('MAXIMUM',b.outputs['RPT Eye'],.00001),1,'去除眼眉边缘的底色混入','DIVIDE')
        color=q.mix(color,eye_color,mask,'只混合眼部')
    bloom=q.node('CompositorNodeGlare','辉光');bloom.inputs['Type'].default_value='Bloom';q.put(color,bloom.inputs['Image'])
    drive(bloom.inputs['Threshold'],registry['global'],'Bloom Threshold');bloom.inputs['Strength'].default_value=1
    strength=q.node('ShaderNodeValue','辉光强度');drive(strength.outputs[0],registry['global'],'Bloom Strength')
    # Glare-only output is added without a 0..1 Mix clamp.
    color=q.mix(color,q.mix(bloom.outputs['Glare'],strength.outputs[0],1,'Scale glow','MULTIPLY'),1,'Add glow','ADD')
    alpha=q.node('CompositorNodeSetAlpha','Preserve silhouette');alpha.inputs['Type'].default_value='Replace Alpha';q.put(color,alpha.inputs['Image']);q.put(a.outputs['Alpha'],alpha.inputs['Alpha']);o=q.node('NodeGroupOutput','Final');q.put(alpha.outputs[0],o.inputs[0])
