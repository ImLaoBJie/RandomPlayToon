"""Blender CPU test: mixed transparency is independent of frame tessellation.

Run with --background --factory-startup --python-exit-code 1 --python FILE.
An optional path after -- receives a JSON result; no rendering is required.
"""
import json
import sys
from pathlib import Path
import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
from random_play_toon.materials.controls import LOCAL,make_node,drive
from random_play_toon.materials.detail_review import (
    alpha_area_fractions,is_eyewear_material,apply_mixed_transparency,transparent_surfaces)

bpy.ops.wm.read_factory_settings(use_empty=True)
checks=[]

def fixture(frame_faces=1,role='cloth',uncalibrated=True,alpha=None,opacity=1.,texture=True,name='墨镜'):
    slot=len(checks)
    mat=bpy.data.materials.new('Source '+str(slot));mat.use_nodes=True
    mat.node_tree.nodes.clear();mat.surface_render_method='DITHERED';mat.use_transparency_overlap=True
    node,entry=make_node(mat,'ZZZ_MaterialControls',LOCAL);entry.update(slot=slot,role=role,source_name=name)
    node.inputs['表面不透明度'].default_value=opacity
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.name='PMX 原色（保留原配色）'
    mix=mat.node_tree.nodes.new('ShaderNodeMixShader');mix.name='Independent surface alpha'
    product=mat.node_tree.nodes.new('ShaderNodeMath');product.operation='MULTIPLY'
    mat.node_tree.links.new(tex.outputs['Alpha'],product.inputs[0]);mat.node_tree.links.new(node.outputs['Opacity'],product.inputs[1])
    mat.node_tree.links.new(product.outputs[0],mix.inputs[0])
    shell=bpy.data.materials.new('RPT_Outline_'+str(slot));shell.use_nodes=True;shell.node_tree.nodes.clear()
    shell.surface_render_method='DITHERED'
    st=shell.node_tree.nodes.new('ShaderNodeTexImage');st.name='Source alpha'
    value=shell.node_tree.nodes.new('ShaderNodeValue');value.name='Source opacity';drive(value.outputs[0],entry,'Opacity')
    sm=shell.node_tree.nodes.new('ShaderNodeMixShader');sm.name='Preserve source holes'
    shell.node_tree.links.new(st.outputs['Alpha'],sm.inputs[0])
    a=np.asarray(alpha if alpha is not None else [.64]+[1.]*frame_faces)
    area=np.asarray([.07]+[.93/frame_faces]*frame_faces)
    if len(a)!=len(area):area=np.ones(len(a))
    data={slot:{'rgba':np.column_stack([np.ones((len(a),3)),a]),'area':area,'texture':tex if texture else None}}
    registry={'materials':[entry],'uncalibrated':uncalibrated}
    checks.append({'slot':slot,'role':role})
    return registry,data,mat,shell,node

def node_counts(mat,shell):return len(mat.node_tree.nodes),len(shell.node_tree.nodes),len(mat.node_tree.links),len(shell.node_tree.links)

# The lens covers 7% of the surface in both meshes. Only the opaque frame has
# been subdivided: old face-count logic changes from 50% to less than 1%.
fractions=[]
for count in [1,100,1000]:
    r,d,mat,shell,node=fixture(frame_faces=count)
    before_inputs=[s.name for s in node.inputs]
    source_link=mat.node_tree.nodes['Independent surface alpha'].inputs[0].links[0].from_socket
    audit=transparent_surfaces(None,r,d,{})
    assert mat.surface_render_method=='BLENDED' and not mat.use_transparency_overlap
    assert shell.surface_render_method=='DITHERED'
    assert mat.node_tree.nodes['Independent surface alpha'].inputs[0].links[0].from_socket==source_link
    assert [s.name for s in node.inputs]==before_inputs
    assert len(audit)==1 and abs(audit[0]['fraction']-.07)<1e-12
    fractions.append(audit[0]['fraction'])
    p=shell.node_tree.nodes['RPT Mixed surface opacity'];cut=shell.node_tree.nodes['RPT Opaque outline coverage']
    assert p.operation=='MULTIPLY' and cut.operation=='GREATER_THAN'
    assert p.inputs[0].links[0].from_node.name=='Source alpha'
    assert p.inputs[0].links[0].from_socket.name=='Alpha'
    assert p.inputs[1].links[0].from_node.name=='Source opacity'
    assert cut.inputs[0].links[0].from_node==p and abs(cut.inputs[1].default_value-.975)<1e-6
    assert shell.node_tree.nodes['Preserve source holes'].inputs[0].links[0].from_node==cut
    # The live opacity driver, rather than a snapshot of its default, reaches
    # the cutoff. Transparent lenses and faded frames must not retain a hull.
    driver=next(fc for fc in shell.node_tree.animation_data.drivers if 'Source opacity' in fc.data_path)
    assert driver.driver.variables[0].targets[0].id==mat
    assert '表面不透明度' in driver.driver.variables[0].targets[0].data_path
    for tex_alpha,local_opacity,expected in [(.64,1.,False),(1.,1.,True),(1.,.5,False),(0.,1.,False)]:
        assert (tex_alpha*local_opacity>cut.inputs[1].default_value)==expected
    counts=node_counts(mat,shell)
    assert apply_mixed_transparency(r,d)==audit
    assert node_counts(mat,shell)==counts
    assert transparent_surfaces(None,r,d,{})==audit and node_counts(mat,shell)==counts
    checks[-1].update(frame_faces=count,area_fraction=audit[0]['fraction'],idempotent=True)
assert np.allclose(fractions,.07)

# Calibrated scenes retain their existing choices. The targeted saved-project
# API also leaves eye surfaces, authored hair, full translucency and no-texture
# materials untouched, including their transparency-overlap setting.
for options in [dict(uncalibrated=False),dict(role='eyes'),dict(role='eye_white'),
                dict(role='eye_shadow'),dict(role='eye_highlight'),dict(role='brows_lashes'),
                dict(role='hair'),dict(role='hair_overlay'),dict(alpha=[.64,.64]),
                dict(opacity=.5),dict(texture=False),dict(name='半透明衣摆'),
                dict(name='glass fabric'),dict(name='')]:
    r,d,mat,shell,node=fixture(**options)
    counts=node_counts(mat,shell);mat.surface_render_method='BLENDED';mat.use_transparency_overlap=True
    assert apply_mixed_transparency(r,d)==[]
    assert mat.surface_render_method=='BLENDED' and mat.use_transparency_overlap
    assert shell.surface_render_method=='DITHERED' and node_counts(mat,shell)==counts
    if options.get('role') in {'eyes','eye_white'}:
        transparent_surfaces(None,r,d,{})
        assert mat.surface_render_method=='DITHERED' and node.inputs['部位描边倍率'].default_value==0
    if options.get('alpha') or options.get('opacity'):
        transparent_surfaces(None,r,d,{})
        assert mat.surface_render_method=='BLENDED' and mat.use_transparency_overlap
    checks[-1].update(unchanged_by_targeted_api=True)

for name in ['眼镜','墨镜','镜片2','眼鏡','メガネ','サングラス','レンズ',
             'Eyeglass','eye_glasses','Sunglasses','SunGlassFrame','Glasses','Lens01','Lenses']:
    assert is_eyewear_material(name),name
for name in ['半透明衣摆','丝袜','glass fabric','fiberglass armor','lensflare','']:
    assert not is_eyewear_material(name),name

# Old saved projects can pass authoritative report names explicitly. The
# generated material name is deliberately misleading and must never be used.
r,d,mat,shell,node=fixture(frame_faces=100,name='')
entry=r['materials'][0];mat.name='RPT_SunglassesCharacter_00_半透明衣摆';entry['material']=mat.name
assert apply_mixed_transparency(r,d)==[]
assert len(apply_mixed_transparency(r,d,{entry['slot']:'墨镜'}))==1
assert not entry['source_name']
checks[-1].update(explicit_legacy_source_name=True)

assert alpha_area_fractions([],[])==(0.,0.)
assert alpha_area_fractions([.5,1.],[0.,0.])==(0.,0.)
assert alpha_area_fractions([.5,1.,np.nan],[1.,1.,100.])==(.5,.5)
assert alpha_area_fractions([.5,1.],[np.inf,1.])==(0.,1.)

result={'passed':True,'checks':checks,'renders':0}
if '--' in sys.argv:
    destination=Path(sys.argv[sys.argv.index('--')+1]);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print('SURFACE_ALPHA_POLICY_PASS',json.dumps(result,ensure_ascii=False),flush=True)
