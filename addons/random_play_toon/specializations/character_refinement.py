"""Small, explicit art-direction exceptions over the preserved 0.7.6 pipeline.

Used by both fresh PMX reconstruction and the non-destructive scene migration.
No source geometry, textures, shared node groups or global defaults are edited.
"""
import json
from pathlib import Path
import bpy
from .. import style_panel as ui
from ..materials.style_upgrade import Graph,add,source

REVISION=1

def pearl_metal(entry):
    mat=bpy.data.materials[entry['material']];n=ui.node(entry);q=Graph(mat.node_tree)
    n.inputs['表面反射强度'].default_value=1.1
    n.inputs['表面反射粗糙度'].default_value=.24
    n.inputs['反射区底色保留'].default_value=.35
    add(entry,'Pearl Tint Strength','金属冷色混色',.85,0,1,'04 金属与塑料','以已配对法线和金属遮罩限定冷蓝、青紫混色；是参考图校准的艺术反射，不是原游戏 MatCap。')
    toon=mat.node_tree.nodes['共享 EEVEE 卡通着色'];normal=source(toon.inputs['Normal']);geo=mat.node_tree.nodes['Surface']
    nv=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,geo.outputs['Incoming']),0)
    noise=q.node('ShaderNodeTexNoise','Calibrated pearl variation from mapped normal');q.put(normal,noise.inputs['Vector']);noise.inputs['Scale'].default_value=4.;noise.inputs['Detail'].default_value=2.
    fac=q.math('ADD',q.math('MULTIPLY',noise.outputs['Fac'],.6),q.math('MULTIPLY',nv,.4))
    ramp=q.node('ShaderNodeValToRGB','Cool silver / cyan / violet reflection');q.put(fac,ramp.inputs[0]);ramp.color_ramp.interpolation='EASE'
    colors=[(0,(.34,.42,.75,1)),(.36,(.58,.45,.70,1)),(.49,(.36,.75,.86,1)),(.63,(.63,.69,.83,1)),(1,(.78,.87,1,1))]
    cr=ramp.color_ramp;cr.elements.remove(cr.elements[1]);cr.elements[0].position=colors[0][0];cr.elements[0].color=colors[0][1]
    for position,color in colors[1:]:cr.elements.new(position).color=color
    dec=mat.node_tree.nodes.get('已审核的控制通道')
    mask=dec.outputs['Metal Mask'] if dec else 1.
    # PMX separates the plate slots; some shoulder atlas G values are low.
    # Preserve that distinction while retaining a modest plate-only coating.
    mask=q.math('MAXIMUM',mask,.8)
    factor=q.math('MULTIPLY',mask,n.outputs['Pearl Tint Strength'])
    em=mat.node_tree.nodes['Final stylized surface'];old=source(em.inputs['Color'])
    q.put(q.vec('MULTIPLY',old,q.mix((1,1,1,1),ramp.outputs['Color'],factor)),em.inputs['Color'])
    mat['rpt_pearl_source']='verified source normal + LightMap G; view-dependent calibrated cool palette'

def apply(scene,identity):
    options=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf8')).get(identity)
    if not options:return None
    if scene.get('rpt_character_refinement_revision')==REVISION:return json.loads(scene['rpt_character_refinement'])
    r=ui.registry(scene);entries={e['slot']:e for e in r['materials']};changes=[]
    for entry in entries.values():
        labels=[s.name for s in ui.node(entry).inputs]
        legacy=entry.setdefault('legacy_label_sets',[entry.get('legacy_labels',labels)])
        if labels not in legacy:legacy.append(labels)
    for slot,params in options.get('parameters',{}).items():
        n=ui.node(entries[int(slot)])
        for label,value in params.items():
            n.inputs[label].default_value=value
        changes.append({'slot':int(slot),'parameters':params})
    for slot in options.get('pearl_metal_parts',[]):
        pearl_metal(entries[slot]);changes.append({'slot':slot,'effect':'calibrated cold metal tint; source normal and metal mask'})
    if 'faceted_halo' in options:
        slot=options['faceted_halo'];entry=entries[slot];n=ui.node(entry);mat=bpy.data.materials[entry['material']];q=Graph(mat.node_tree)
        add(entry,'Halo Facet Depth','光环切面层次',.35,0,1,'06 自发光','保留紫色发光，同时用原几何切面与独立光向呈现明暗层次。')
        geo=mat.node_tree.nodes['Surface'];direction=mat.node_tree.nodes['Independent light / head pose']
        lit=q.math('MAXIMUM',q.vec('DOT_PRODUCT',geo.outputs['True Normal'],direction.outputs['Light Direction']),0)
        gain=q.math('ADD',q.math('SUBTRACT',1,n.outputs['Halo Facet Depth']),q.math('MULTIPLY',lit,n.outputs['Halo Facet Depth']))
        em=mat.node_tree.nodes['Final stylized surface'];q.put(q.vec('SCALE',source(em.inputs['Color']),gain),em.inputs['Color'])
        changes.append({'slot':slot,'effect':'original geometric facets modulate purple halo'})
    if options.get('sleeve_layers'):
        cloth_slot,skin_slot=options['sleeve_layers'];entry=entries[skin_slot]
        mat=bpy.data.materials[entry['material']];q=Graph(mat.node_tree);n=ui.node(entry)
        body=bpy.data.materials[entries[cloth_slot]['material']].node_tree.nodes['PMX 原色（保留原配色）'].image
        obj=bpy.data.objects[r['mesh_object']];me=obj.data
        values=[]
        for p in me.polygons:
            # Audited arm surface on this exact PMX fingerprint. Rest positions
            # avoid cutting across the several separate arm UV islands.
            # Alpha-zero pixels here are the omitted CLOTH layer, not holes.
            values.append(float(p.material_index==skin_slot and abs(p.center.x)>.16 and p.center.z>.85))
        att=me.attributes.get('RPT_WhiteSleeveRegion') or me.attributes.new('RPT_WhiteSleeveRegion','FLOAT','FACE')
        att.data.foreach_set('value',values)
        region=q.node('ShaderNodeAttribute','Verified sleeve cloth island');region.attribute_name=att.name
        tex=q.node('ShaderNodeTexImage','Sleeve cloth from original PMX body atlas');tex.image=body
        q.put(mat.node_tree.nodes['Original PMX UV'].outputs[0],tex.inputs['Vector'])
        original=mat.node_tree.nodes['PMX 原色（保留原配色）']
        missing=q.math('MULTIPLY',region.outputs['Fac'],q.math('SUBTRACT',1,original.outputs['Alpha']))
        base=mat.node_tree.nodes['原色乘色']
        q.put(q.mix(original.outputs['Color'],tex.outputs['Color'],missing),base.inputs[1])
        coverage=q.math('MAXIMUM',original.outputs['Alpha'],region.outputs['Fac'])
        q.put(q.math('MULTIPLY',coverage,n.outputs['Opacity']),mat.node_tree.nodes['Independent surface alpha'].inputs[0])
        mat.surface_render_method='DITHERED'
        shell=bpy.data.materials.get('RPT_Outline_'+str(skin_slot))
        if shell:
            sq=Graph(shell.node_tree);a=sq.node('ShaderNodeAttribute','Verified sleeve cloth island');a.attribute_name=att.name
            alpha=sq.math('MAXIMUM',shell.node_tree.nodes['Source alpha'].outputs['Alpha'],a.outputs['Fac'])
            sq.put(sq.math('MULTIPLY',alpha,shell.node_tree.nodes['Source opacity'].outputs[0]),shell.node_tree.nodes['Preserve source holes'].inputs[0])
            shell.surface_render_method='DITHERED'
        changes.append({'slot':skin_slot,'effect':'restore missing sleeve cloth from original body atlas inside audited arm island; skin unchanged','region_faces':int(sum(values)),'source_image':body.name})
    report={'revision':REVISION,'identity':identity,'changes':changes,'source_mesh_and_images_unchanged':True}
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    scene['zzz_stage6_defaults']=json.dumps(ui.capture(scene),ensure_ascii=False)
    scene['rpt_character_refinement_revision']=REVISION
    scene['rpt_character_refinement']=json.dumps(report,ensure_ascii=False)
    ui.refresh(scene)
    return report
