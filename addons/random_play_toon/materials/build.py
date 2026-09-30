"""Semantic materials over one PMX mesh; matching is supplied by audited profiles."""
import bpy
from pathlib import Path
from .graph import Graph,build_surface
from .decoder import build_decoder,image_node
from . import controls

DETAIL={'eyes','eye_white','eye_highlight','eye_shadow','brows_lashes','mouth','mouth_line'}

def build(obj,profile,inputs,registry,directions):
    decoder=build_decoder();surface=build_surface();original=list(obj.data.materials)
    for mat in original:mat.use_fake_user=True
    for b in profile['materials']:
        idx=b['index'];role=b['role'];mat=bpy.data.materials.new(f"RPT_{profile['id']}_{idx:02d}_{b['name']}");mat.use_nodes=True;mat.surface_render_method='DITHERED'
        mat['rpt_role']=role;mat['rpt_slot']=idx;mat['rpt_asset_id']=profile['id'];mat['rpt_matching']=b['matching'];mat['rpt_source_texture']=b['source_texture'] or ''
        mat.use_backface_culling=not bool(b['draw_flags']&1)
        obj.data.materials[idx]=mat;t=mat.node_tree;t.nodes.clear();q=Graph(t)
        n,entry=controls.make_node(mat,'ZZZ_MaterialControls',controls.LOCAL);entry.update(slot=idx,role=role);registry['materials'].append(entry)
        if inputs['textures'].get(str(idx)):n.inputs['原色乘色'].default_value=(*b['diffuse'][:3],1.)
        if role in ['face','skin']:n.inputs['阴影乘色'].default_value=(.76,.57,.60,1)
        if role=='face':n.inputs['部位过渡倍率'].default_value=1.5
        if role=='metal':n.inputs['金属反光强度'].default_value=.5
        if role=='emissive':n.inputs['自发光强度'].default_value=.8
        if role=='stocking':n.inputs['部位高光倍率'].default_value=.55;n.inputs['部位过渡倍率'].default_value=2
        if role in DETAIL:n.inputs['部位高光倍率'].default_value=0
        for label,value in profile.get('parameter_overrides',{}).get(str(idx),{}).items():
            if label not in n.inputs:raise ValueError('角色配置使用未知参数：'+label)
            n.inputs[label].default_value=value
        n.inputs['表面不透明度'].default_value=b['diffuse'][3]
        glob={key:controls.output(q,registry['global'],key) for key in ['Key Gain','Body Threshold','Body Softness','Normal Strength','Global Specular','Rim Strength','Studio Mode','Eye Reveal Texture Influence','Eye Reveal Brow Strength']}
        direction=q.node('ShaderNodeGroup','Independent light / head pose');direction.node_tree=directions
        uv=q.node('ShaderNodeUVMap','Original PMX UV');uv.uv_map='UVMap';dds_uv=uv.outputs[0]
        if b.get('dds_flip_v',True):
            sep=q.node('ShaderNodeSeparateXYZ','DDS sampling');q.put(dds_uv,sep.inputs[0]);comb=q.node('ShaderNodeCombineXYZ','DDS V correction');q.put(sep.outputs[0],comb.inputs[0]);q.put(q.math('SUBTRACT',1,sep.outputs[1]),comb.inputs[1]);dds_uv=comb.outputs[0]
        path=inputs['textures'].get(str(idx));base=b['diffuse'];alpha=1.
        if path:
            im=image_node(t,path,data=False);im.name='PMX 原色（保留原配色）';q.put(uv.outputs[0],im.inputs['Vector']);base=im.outputs['Color']
            # This is the authored PMX diffuse, whose alpha is surface opacity.
            # Packed DDS alpha is deliberately never substituted here.
            alpha=im.outputs['Alpha']
        base=q.mix(base,n.outputs['Base Tint'],1,'原色乘色','MULTIPLY')
        geo=q.node('ShaderNodeNewGeometry','Surface');normal=geo.outputs['Normal'];decoded=None
        maps=inputs['maps'].get(str(idx),{})
        # Face/SDF and detail shaders do not interpret body control maps.
        if maps and role not in DETAIL|{'face','hair_overlay'}:
            decoded=q.node('ShaderNodeGroup','已审核的控制通道');decoded.node_tree=decoder;q.put(glob['Normal Strength'],decoded.inputs['Normal Strength'])
            for kind in ['NormalMap','LightMap','MaterialMap']:
                if kind in maps:
                    im=image_node(t,maps[kind],data=True);im.name=kind+' · Non-Color';q.put(dds_uv,im.inputs['Vector']);q.put(im.outputs['Color'],decoded.inputs[kind+' RGB'])
            if 'NormalMap' in maps:
                nm=q.node('ShaderNodeNormalMap','RG 重建 Z；原 UV 切线');nm.uv_map='UVMap';q.put(decoded.outputs['Normal TS Encoded'],nm.inputs['Color']);normal=nm.outputs[0]
        if role=='face':
            att=q.node('ShaderNodeAttribute','本模型脸部方向场');att.attribute_name='rpt_face_direction';sep=q.node('ShaderNodeSeparateXYZ','Head field');q.put(att.outputs['Vector'],sep.inputs[0])
            normal=q.vec('NORMALIZE',q.vec('ADD',q.vec('ADD',q.vec('SCALE',direction.outputs['Head Right'],sep.outputs[0]),q.vec('SCALE',direction.outputs['Head Forward'],sep.outputs[1])),q.vec('SCALE',direction.outputs['Head Up'],sep.outputs[2])))
        toon=q.node('ShaderNodeGroup','共享 EEVEE 卡通着色');toon.node_tree=surface
        for key,value in [('Base Color',base),('Normal',normal),('Light Direction',direction.outputs['Light Direction']),('Threshold',glob['Body Threshold']),('Softness',q.math('MULTIPLY',glob['Body Softness'],n.outputs['Local Softness'])),('Shadow Tint',n.outputs['Shadow Tint']),('Key Gain',q.math('MULTIPLY',glob['Key Gain'],n.outputs['Local Gain'])),('Specular Strength',q.math('MULTIPLY',glob['Global Specular'],n.outputs['Local Specular'])),('Rim Strength',glob['Rim Strength']),('Scene Shadow Strength',q.math('MULTIPLY',q.math('SUBTRACT',1,glob['Studio Mode']),.35))]:q.put(value,toon.inputs[key])
        toon.inputs['Bias Strength'].default_value=.25
        metal=1. if role=='metal' else 0.;emissionmask=1. if role in ['emissive','eyes'] else 0.;reveal=1.
        if decoded:
            for key in ['Shadow Bias','Material Slot','Metal Mask','Specular Mask','Smoothness']:q.put(decoded.outputs[key],toon.inputs[key])
            metal=decoded.outputs['Metal Mask'];emissionmask=decoded.outputs['Emission Remapped'];reveal=decoded.outputs['Eye Reveal Potential']
        color=toon.outputs['Color']
        if role in DETAIL:color=q.vec('SCALE',base,q.math('MULTIPLY',glob['Key Gain'],n.outputs['Local Gain']))
        # Stable stylized reflection in independent-light mode, masked by data.
        facing=q.node('ShaderNodeLayerWeight','Metal virtual environment');reflection=q.math('MULTIPLY',q.math('MULTIPLY',metal,n.outputs['Metal Reflection']),q.math('ADD',.2,q.math('MULTIPLY',facing.outputs['Facing'],.8)))
        color=q.vec('ADD',color,q.vec('SCALE',base,reflection))
        if role=='emissive':emissionmask=1.
        color=q.vec('ADD',color,q.vec('SCALE',base,q.math('MULTIPLY',emissionmask,n.outputs['Glow Strength'])))
        em=q.node('ShaderNodeEmission','Final stylized surface');q.put(color,em.inputs['Color'])
        alpha=q.math('MULTIPLY',alpha,n.outputs['Opacity']);tr=q.node('ShaderNodeBsdfTransparent','Surface transparency');mix=q.node('ShaderNodeMixShader','Independent surface alpha');q.put(alpha,mix.inputs[0]);q.put(tr.outputs[0],mix.inputs[1]);q.put(em.outputs[0],mix.inputs[2]);out=q.node('ShaderNodeOutputMaterial','Material Output');q.put(mix.outputs[0],out.inputs['Surface'])
        # AOVs are evaluated through normal geometry visibility, so closed lids,
        # hands and back hair still occlude the eye layer.
        eye=1. if role in ['eyes','eye_white','eye_highlight'] else glob['Eye Reveal Brow Strength'] if role=='brows_lashes' else 0.
        if role in ['eyes','eye_white','eye_highlight','brows_lashes']:
            support=q.math('MULTIPLY',eye,alpha,'Eye support × surface alpha')
            aov=q.node('ShaderNodeOutputAOV','Visible eye support');aov.aov_name='RPT Eye';q.put(support,aov.inputs['Color'])
            aov=q.node('ShaderNodeOutputAOV','Premultiplied eye color');aov.aov_name='RPT Eye Color';q.put(q.vec('SCALE',color,support),aov.inputs['Color'])
        if role=='hair':
            att=q.node('ShaderNodeAttribute','Selected front bangs');att.attribute_name='rpt_bangs'
            cosine=q.vec('DOT_PRODUCT',direction.outputs['Head Forward'],geo.outputs['Incoming']);angle=q.smooth(cosine,.17,.71)
            reveal=q.math('ADD',q.math('SUBTRACT',1,glob['Eye Reveal Texture Influence']),q.math('MULTIPLY',glob['Eye Reveal Texture Influence'],reveal))
            aov=q.node('ShaderNodeOutputAOV','Front bangs only');aov.aov_name='RPT Hair';q.put(q.math('MULTIPLY',att.outputs['Fac'],q.math('MULTIPLY',reveal,angle)),aov.inputs['Color'])
    return original
