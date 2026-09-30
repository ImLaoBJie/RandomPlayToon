"""Outline-only eye-hole exclusion; source skin, iris and lashes stay intact."""
import collections
import json
from pathlib import Path
import numpy as np
from mathutils.kdtree import KDTree
from .graph import Graph
from .style_upgrade import source

ATTRIBUTE='RPT_EyeMouthOutlineDistance'

def apply_boundary_policy(group, registry, identity):
    """Keep the hull, but omit seam walls on calibrated split-vertex hair.

    Only the generated outline changes; source topology/UVs/weights remain
    intact for animation caches. Safe to apply repeatedly to saved scenes.
    """
    options=json.loads((Path(__file__).parents[1]/'specializations/detail_profiles.json').read_text(encoding='utf8')).get(identity,{})
    enabled=options.get('hair_boundary_walls',True)
    switch=group.nodes['Boundary walls only on hair']
    changed=[]
    for i,entry in enumerate(registry['materials']):
        switch.inputs[i+1].default_value=entry['role']=='hair' and enabled
        if entry['role']=='hair' and not enabled:changed.append(entry['slot'])
    return {'identity':identity,'hair_boundary_walls':enabled,'suppressed_slots':changed,
            'expanded_hull_preserved':True}

def apply_default_scope(registry,identity):
    """Vivian's outline-only surface filtering, retaining explicit brow tuning."""
    from .. import style_panel as ui
    root=Path(__file__).parents[1]/'specializations'
    options=json.loads((root/'detail_profiles.json').read_text(encoding='utf8')).get(identity,{})
    overrides=json.loads((root/'parameter_overrides.json').read_text(encoding='utf8'))['models'].get(identity,{}).get('materials',{})
    primary_face=next((e['slot'] for e in registry['materials'] if e['role']=='face'),None)
    explicit_off=set(options.get('no_outline',[])+options.get('eye_shadow_parts',[])+options.get('inverted_source_shells',[]));disabled=[]
    for e in registry['materials']:
        role=e['role'];slot=e['slot'];local=overrides.get(str(slot),{})
        off=role in {'eyes','eye_white','eye_shadow','eye_highlight','mouth','mouth_line','hair_overlay'} or (role=='face' and slot!=primary_face) or (role=='brows_lashes' and '部位描边倍率' not in local) or slot in explicit_off
        if off:ui.node(e).inputs['部位描边倍率'].default_value=0;disabled.append(slot)
    return {'excluded_slots':disabled,'reference':'Vivian stage7 outline main surfaces; source eye, mouth and brow/lash artwork retained','explicit_part_overrides_preserved':True}

def author_eye_rims(obj,registry):
    me=obj.data;face_slots={e['slot'] for e in registry['materials'] if e['role']=='face'};eye_slots={e['slot'] for e in registry['materials'] if e['role'] in {'eyes','eye_white','mouth','mouth_line'}}
    distance=np.full(len(me.polygons),1000.,dtype=np.float32);rim=set()
    if face_slots and eye_slots:
        pos=np.array([v.co[:] for v in me.vertices]);coords=[tuple(np.round(p,6)) for p in pos];eyeids={i for p in me.polygons if p.material_index in eye_slots for i in p.vertices};tree=KDTree(len(eyeids))
        for i in eyeids:tree.insert(pos[i],i)
        tree.balance();counts=collections.Counter()
        for p in me.polygons:
            if p.material_index not in face_slots:continue
            vs=list(p.vertices)
            for a,b in zip(vs,vs[1:]+vs[:1]):counts[tuple(sorted((coords[a],coords[b])))]+=1
        # Verify eye/mouth openings against their own original geometry.
        # The head silhouette and eyebrow recesses fail this proximity test.
        for (a,b),count in counts.items():
            if count==1 and tree.find(a)[2]<.0002 and tree.find(b)[2]<.0002:rim.update([a,b])
        if rim:
            rt=KDTree(len(rim))
            for i,p in enumerate(sorted(rim)):rt.insert(p,i)
            rt.balance();vertex_distance=np.array([rt.find(p)[2] for p in pos])
            for p in me.polygons:
                if p.material_index in face_slots:distance[p.index]=min(vertex_distance[list(p.vertices)])
    attribute=me.attributes.get(ATTRIBUTE) or me.attributes.new(ATTRIBUTE,'FLOAT','FACE');attribute.data.foreach_set('value',distance)
    return {'verified_eye_mouth_rim_vertices':len(rim),'adjacent_face_polygons':int((distance<.00001).sum()),'source_geometry_changed':False}

def wire_filter(group,registry):
    q=Graph(group);ext=group.nodes['Connected outline with boundary walls'];width=source(group.nodes['Thickness'].inputs['Scale'])
    att=q.node('GeometryNodeInputNamedAttribute','Verified face eye/mouth-hole distance');att.data_type='FLOAT';att.inputs['Name'].default_value=ATTRIBUTE
    rim=q.math('MULTIPLY',att.outputs['Exists'],q.math('LESS_THAN',att.outputs['Attribute'],q.math('MAXIMUM',q.math('MULTIPLY',width,3),.00001)))
    disabled=q.math('LESS_THAN',width,.00000001)
    delete=q.node('GeometryNodeDeleteGeometry','Exclude disabled outlines and face eye-hole rims');delete.domain='FACE';delete.mode='ALL'
    q.put(group.nodes['Deformed source'].outputs[0],delete.inputs['Geometry']);q.put(q.math('MAXIMUM',disabled,rim),delete.inputs['Selection']);q.put(delete.outputs[0],ext.inputs['Mesh'])
    ext.inputs['Offset Scale'].default_value=1
    # Vivian uses a plain inverted hull on the face. Boundary walls are only
    # needed for the requested disconnected hair edges; on facial holes they
    # create a new eye/lip ring even after the neighboring faces are excluded.
    index=q.node('GeometryNodeInputMaterialIndex','Outline region part');hair=q.node('GeometryNodeIndexSwitch','Boundary walls only on hair');hair.data_type='BOOLEAN'
    while len(hair.index_switch_items)<len(registry['materials']):hair.index_switch_items.new()
    q.put(index.outputs[0],hair.inputs['Index'])
    for i,e in enumerate(registry['materials']):hair.inputs[i+1].default_value=e['role']=='hair'
    keep=q.math('MAXIMUM',ext.outputs['Top'],q.math('MULTIPLY',ext.outputs['Side'],hair.outputs[0]))
    q.put(q.math('SUBTRACT',1,keep),group.nodes['Keep expanded surface and boundary walls'].inputs['Selection'])
