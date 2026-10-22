"""Blender CPU test: split hair seams lose Side walls, not real boundaries.

Run with --background --factory-startup --python-exit-code 1 --python <this>
-- <output directory>. No rendering or source model modifications are needed.
"""
import json
import sys
from pathlib import Path
import bpy

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
from random_play_toon.materials.graph import Graph
from random_play_toon.materials.outline_regions import (
    author_hair_split_edges,wire_hair_split_edges,apply_boundary_policy)
from random_play_toon.specializations.vivian.core import mesh_snapshot

out=Path(sys.argv[sys.argv.index('--')+1]).resolve();out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.preferences.filepaths.file_preview_type='NONE'
bpy.context.preferences.filepaths.save_version=0


def fixture(name,mode='split',padding=0):
    coords=[(0,0,0),(1,0,0),(1,1,0),(0,0,0),(1,1,0),(0,1,0)]
    faces=[(0,1,2),(3,4,5)]
    if mode=='open':coords=coords[:3];faces=faces[:1]
    if mode=='reversed':faces[1]=(5,4,3)
    if mode=='coincident':coords=coords[:3]*2
    if mode=='ambiguous':coords+=coords[3:6];faces.append((6,7,8))
    coords=[(9,9,9)]*padding+coords
    faces=[tuple(v+padding for v in face) for face in faces]
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(coords,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(bpy.data.materials.new(name+' hair'))
    uv=mesh.uv_layers.new(name='UVMap')
    for i,loop in enumerate(uv.data):loop.uv=(i/len(uv.data),.5)
    group=obj.vertex_groups.new(name='head');group.add(list(range(len(coords))),1.,'REPLACE')
    # MMD's ordering metadata differs between split duplicates but is not a
    # skeletal weight and must not prevent identification of the same surface.
    order=obj.vertex_groups.new(name='mmd_vertex_order')
    for i in range(padding,len(coords)):order.add([i],(i+1)/len(coords),'REPLACE')
    if mode=='weights':
        group.remove([padding+3,padding+4,padding+5])
        obj.vertex_groups.new(name='moving strand').add([padding+3,padding+4,padding+5],1.,'REPLACE')
    obj.shape_key_add(name='Basis');key=obj.shape_key_add(name='shape')
    if mode=='shape':key.data[padding+3].co.z=.25
    else:
        for i in [padding,padding+3]:
            if i<len(coords):key.data[i].co.z=.25
    registry={'mesh_object':obj.name,'materials':[{'slot':0,'role':'hair'}]}
    tree=bpy.data.node_groups.new(name+' hull','GeometryNodeTree')
    for direction in ['INPUT','OUTPUT']:tree.interface.new_socket(name='Geometry',in_out=direction,socket_type='NodeSocketGeometry')
    q=Graph(tree);inp=q.node('NodeGroupInput','Deformed source')
    ext=q.node('GeometryNodeExtrudeMesh','Connected outline with boundary walls');ext.mode='FACES';ext.inputs['Individual'].default_value=False
    ext.inputs['Offset'].default_value=(0,0,.1);ext.inputs['Offset Scale'].default_value=1
    q.put(inp.outputs[0],ext.inputs['Mesh'])
    switch=q.node('GeometryNodeIndexSwitch','Boundary walls only on hair');switch.data_type='BOOLEAN'
    switch.inputs[1].default_value=True
    keep=q.math('MAXIMUM',ext.outputs['Top'],q.math('MULTIPLY',ext.outputs['Side'],switch.outputs[0]))
    delete=q.node('GeometryNodeDeleteGeometry','Keep expanded surface and boundary walls');delete.domain='FACE';delete.mode='ALL'
    q.put(ext.outputs[0],delete.inputs['Geometry']);q.put(q.math('SUBTRACT',1,keep),delete.inputs['Selection'])
    output=q.node('NodeGroupOutput','Output');q.put(delete.outputs[0],output.inputs[0])
    mod=obj.modifiers.new('test outline','NODES');mod.node_group=tree
    return obj,tree,registry


def evaluated(obj):
    bpy.context.view_layer.update()
    current=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=current.to_mesh()
    try:
        tops=[p for p in mesh.polygons if len(p.vertices)==3]
        sides=[p for p in mesh.polygons if len(p.vertices)==4]
        top_positions=sorted(tuple(sorted(tuple(round(c,6) for c in mesh.vertices[v].co) for v in p.vertices)) for p in tops)
        return {'top':len(tops),'side':len(sides),'top_positions':top_positions}
    finally:current.to_mesh_clear()


checks=[]
for mode in ['split','open','weights','shape','reversed','coincident','ambiguous']:
    obj,tree,registry=fixture(mode,mode)
    source=mesh_snapshot(obj);before=evaluated(obj)
    report=author_hair_split_edges(obj,registry);wire_hair_split_edges(tree)
    after=evaluated(obj)
    expected=1 if mode=='split' else 0
    assert report['seam_pairs']==expected,(mode,report)
    assert after['top']==before['top'] and after['top_positions']==before['top_positions'],mode
    assert after['side']==before['side']-expected*2,(mode,before,after)
    assert mesh_snapshot(obj)==source,mode
    count=len(tree.nodes);author_hair_split_edges(obj,registry);wire_hair_split_edges(tree)
    assert len(tree.nodes)==count and evaluated(obj)==after,mode
    checks.append({'case':mode,'before':{k:v for k,v in before.items() if k!='top_positions'},
                   'after':{k:v for k,v in after.items() if k!='top_positions'},'seam_pairs':report['seam_pairs']})

# Test IDs beyond the largest current random-sample model (38,619 vertices).
# Their half-integer edge codes must remain exact through real field adaptation.
obj,tree,registry=fixture('high_indices','split',40000)
armature=bpy.data.armatures.new('test head rig');rig=bpy.data.objects.new('test head rig',armature)
bpy.context.scene.collection.objects.link(rig);bpy.context.view_layer.objects.active=rig;rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT');bone=armature.edit_bones.new('head');bone.head=(0,0,0);bone.tail=(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
deform=obj.modifiers.new('real skeletal deformation','ARMATURE');deform.object=rig;obj.modifiers.move(len(obj.modifiers)-1,0)
source=mesh_snapshot(obj);report=author_hair_split_edges(obj,registry);wire_hair_split_edges(tree)
assert report['max_source_vertex_id']==40006 and report['seam_pairs']==1
assert evaluated(obj)['top']==2 and evaluated(obj)['side']==4
obj.data.shape_keys.key_blocks['shape'].value=.65
rig.pose.bones['head'].rotation_mode='XYZ';rig.pose.bones['head'].rotation_euler=(.2,.3,.1)
posed=evaluated(obj);assert posed['top']==2 and posed['side']==4
assert mesh_snapshot(obj)==source

# Explicit existing calibration still wins, including its true outer boundaries.
calibrated,cal_tree,cal_registry=fixture('calibrated')
policy=apply_boundary_policy(cal_tree,cal_registry,'YeShunguang')
assert policy['hair_boundary_walls'] is False
assert evaluated(calibrated)['top']==2 and evaluated(calibrated)['side']==0

dest=out/'hair_boundary_topology.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(dest),compress=True)
bpy.ops.wm.open_mainfile(filepath=str(dest),use_scripts=False)
obj=bpy.data.objects['high_indices']
assert evaluated(obj)==posed and mesh_snapshot(obj)==source
(out/'validation.json').write_text(json.dumps({'passed':True,'cases':checks,
    'real_evaluated_mesh':True,'high_index_encoding':40006,'posed_seam_stable':True,
    'top_and_real_boundary_preserved':True,'source_mesh_uv_shapes_weights_preserved':True,
    'calibrated_policy_preserved':True,'idempotent':True,'saved_reopened':True},indent=2),encoding='utf8')
print('HAIR_BOUNDARY_TOPOLOGY_PASS',flush=True)
