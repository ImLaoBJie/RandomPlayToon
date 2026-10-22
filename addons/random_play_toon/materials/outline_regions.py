"""Outline-only eye-hole exclusion; source skin, iris and lashes stay intact."""
import collections
import json
from ..preset_paths import ROOT as PRESETS
import numpy as np
from mathutils.kdtree import KDTree
from .graph import Graph
from .style_upgrade import source

ATTRIBUTE='RPT_EyeMouthOutlineDistance'
SEAM_VERTEX='RPT_OutlineSourceVertex'
SEAM_EDGES='RPT_HairSplitEdgeCodes'


def author_hair_split_edges(obj,registry):
    """Mark proven split-vertex seams without welding source vertices.

    PMX faces are triangles. A side quad inherits its source face's attributes
    and repeats each original endpoint twice. Its mean source vertex number
    therefore identifies exactly one edge of that source triangle. Unlike
    geometric proximity after extrusion, this remains stable under posing.
    """
    me=obj.data
    if len(me.vertices)>=2**22:
        return {'status':'skipped','reason':'source vertex IDs exceed exact float encoding range'}
    hair={e['slot'] for e in registry['materials'] if e['role']=='hair'}
    coords=[tuple(v.co) for v in me.vertices]
    armature=obj.find_armature()
    deform_names={b.name for b in armature.data.bones} if armature else None
    weight_groups={g.index for g in obj.vertex_groups
                   if (deform_names is None or g.name in deform_names)
                   and g.name not in {'mmd_vertex_order','mmd_edge_scale'}}
    weights=[tuple(sorted((g.group,g.weight) for g in v.groups if g.group in weight_groups)) for v in me.vertices]
    keys=list(me.shape_keys.key_blocks) if me.shape_keys else []
    normals=[tuple(n.vector) for n in me.corner_normals]
    excluded=me.attributes.get('rpt_duplicate_overlay')
    edges=collections.defaultdict(list)
    for face in me.polygons:
        if face.material_index not in hair or len(face.vertices)!=3:continue
        if excluded and excluded.data[face.index].value:continue
        for loop_index in face.loop_indices:
            other=face.loop_start+(loop_index-face.loop_start+1)%face.loop_total
            a,b=me.loops[loop_index].vertex_index,me.loops[other].vertex_index
            edges[(face.material_index,tuple(sorted((a,b))))].append((face.index,a,b,loop_index,other))
    grouped=collections.defaultdict(list);boundary=collections.Counter()
    for (slot,_),items in edges.items():
        if len(items)!=1:continue
        face,a,b,la,lb=items[0]
        if coords[a]==coords[b]:continue
        boundary[slot]+=1
        grouped[(slot,tuple(sorted((coords[a],coords[b]))))].append(items[0])
    codes=np.full((len(me.polygons),3),-1.,dtype=np.float32)
    marked=collections.Counter();pairs=0
    def same_vertex(a,b):
        return weights[a]==weights[b] and all(tuple(k.data[a].co)==tuple(k.data[b].co) for k in keys)
    for (slot,_),items in grouped.items():
        if len(items)!=2:continue  # Ambiguous overlapping sheets remain unchanged.
        f,a,b,la,lb=items[0];g,c,d,lc,ld=items[1]
        # A real adjoining surface traverses the shared edge in reverse.
        if coords[a]!=coords[d] or coords[b]!=coords[c]:continue
        if not same_vertex(a,d) or not same_vertex(b,c):continue
        if sum(x*y for x,y in zip(normals[la],normals[ld]))<.99:continue
        if sum(x*y for x,y in zip(normals[lb],normals[lc]))<.99:continue
        for face,u,v,loop,_ in items:
            codes[face,loop-me.polygons[face].loop_start]=(u+v+2)*.5
        marked[slot]+=2;pairs+=1
    for name,typ,domain,values in [(SEAM_VERTEX,'FLOAT','POINT',np.arange(1,len(me.vertices)+1,dtype=np.float32)),
                                  (SEAM_EDGES,'FLOAT_VECTOR','FACE',codes.ravel())]:
        attr=me.attributes.get(name) or me.attributes.new(name,typ,domain)
        if attr.data_type!=typ or attr.domain!=domain:raise ValueError('Unexpected outline attribute: '+name)
        attr.data.foreach_set('vector' if typ=='FLOAT_VECTOR' else 'value',values)
    report={'status':'authored','seam_pairs':pairs,'max_source_vertex_id':len(me.vertices),
            'slots':[{'slot':slot,'boundary_edges':boundary[slot],'split_edges':marked[slot],
                      'retained_boundary_edges':boundary[slot]-marked[slot]} for slot in sorted(hair)],
            'source_topology_changed':False}
    me['rpt_hair_boundary_topology']=json.dumps(report)
    return report


def wire_hair_split_edges(group):
    """Remove only marked Side faces; always retain the expanded Top hull."""
    if group.nodes.get('RPT Exclude split seam side walls'):return
    ext=group.nodes.get('Connected outline with boundary walls')
    delete=group.nodes.get('Keep expanded surface and boundary walls')
    if not ext or not delete:return
    q=Graph(group);previous=source(delete.inputs['Selection'])
    vertex=q.node('GeometryNodeInputNamedAttribute','RPT Source vertex for side face');vertex.data_type='FLOAT';vertex.inputs['Name'].default_value=SEAM_VERTEX
    edges=q.node('GeometryNodeInputNamedAttribute','RPT Proven split edge codes');edges.data_type='FLOAT_VECTOR';edges.inputs['Name'].default_value=SEAM_EDGES
    sep=q.node('ShaderNodeSeparateXYZ','RPT Source triangle split edges');q.put(edges.outputs['Attribute'],sep.inputs[0])
    matches=[]
    for i in range(3):
        match=q.node('ShaderNodeMath','RPT Side belongs to split edge '+str(i));match.operation='COMPARE'
        q.put(vertex.outputs['Attribute'],match.inputs[0]);q.put(sep.outputs[i],match.inputs[1]);match.inputs[2].default_value=.1
        matches.append(match.outputs[0])
    match=q.math('MAXIMUM',matches[0],q.math('MAXIMUM',matches[1],matches[2]))
    match=q.math('MULTIPLY',match,q.math('MULTIPLY',vertex.outputs['Exists'],edges.outputs['Exists']))
    side=q.math('MULTIPLY',ext.outputs['Side'],match,'RPT Only split seam side walls')
    q.put(q.math('MAXIMUM',previous,side,'RPT Exclude split seam side walls'),delete.inputs['Selection'])


def repair_hair_boundary_topology(scene):
    """Apply only the topology-based outline fix to an existing scene."""
    import bpy
    from .. import style_panel as ui
    registry=ui.registry(scene);obj=bpy.data.objects[registry['mesh_object']]
    report=author_hair_split_edges(obj,registry)
    groups={m.node_group for ob in scene.objects for m in ob.modifiers
            if m.type=='NODES' and m.node_group and m.node_group.nodes.get('Boundary walls only on hair')}
    for group in groups:wire_hair_split_edges(group)
    report['groups']=[group.name for group in groups]
    return report

def apply_boundary_policy(group, registry, identity):
    """Keep the hull, but omit seam walls on calibrated split-vertex hair.

    Only the generated outline changes; source topology/UVs/weights remain
    intact for animation caches. Safe to apply repeatedly to saved scenes.
    """
    options=json.loads((PRESETS/'shared/detail_profiles.json').read_text(encoding='utf8')).get(identity,{})
    enabled=options.get('hair_boundary_walls',True)
    switch=group.nodes['Boundary walls only on hair']
    changed=[]
    for i,entry in enumerate(registry['materials']):
        switch.inputs[i+1].default_value=entry['role']=='hair' and enabled
        if entry['role']=='hair' and not enabled:changed.append(entry['slot'])
    import bpy
    obj=bpy.data.objects.get(registry.get('mesh_object',''))
    topology=author_hair_split_edges(obj,registry) if obj else None
    if topology:wire_hair_split_edges(group)
    return {'identity':identity,'hair_boundary_walls':enabled,'suppressed_slots':changed,
            'expanded_hull_preserved':True,'split_edge_topology':topology}

def apply_default_scope(registry,identity):
    """Vivian's outline-only surface filtering, retaining explicit brow tuning."""
    from .. import style_panel as ui
    root=PRESETS/'shared'
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
