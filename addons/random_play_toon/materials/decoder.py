"""Create a reusable Blender shader node group for audited ZZZ packed channels.

SPDX-License-Identifier: GPL-3.0-or-later
Adapted mathematical decoding from HoyoToon (see experiment reference manifest).
This group is not a complete character shader. Image inputs must be Non-Color.
"""
import bpy

GROUP_NAME = 'ZZZ_PackedChannels_v1'

def build_decoder():
    existing = bpy.data.node_groups.get(GROUP_NAME)
    if existing:
        if existing.get('audit_schema') != 1:
            raise RuntimeError('Refusing to replace an unrecognized node group')
        return existing
    g = bpy.data.node_groups.new(GROUP_NAME, 'ShaderNodeTree')
    g['audit_schema'] = 1
    g['reference_commit'] = 'd9e5ca2f312bf16fba89dee67d32c08b482dcda4'
    g['scope'] = 'Body/Hair decode; not Face/Gem shader, not occlusion implementation'
    for name, typ, default in [
        ('NormalMap RGB','NodeSocketColor',(0.5,0.5,0.5,1)),
        ('LightMap RGB','NodeSocketColor',(0,0,0,1)),
        ('MaterialMap RGB','NodeSocketColor',(1,0.5,0,1)),
        ('Normal Strength','NodeSocketFloat',1),
        ('Flip Normal Y','NodeSocketFloat',0),
        ('Backface','NodeSocketFloat',0),
        ('Glossiness','NodeSocketFloat',0.5),
        ('Min Hair Opacity','NodeSocketFloat',0.2)]:
        s = g.interface.new_socket(name=name,in_out='INPUT',socket_type=typ)
        s.default_value = default
        if typ == 'NodeSocketFloat':
            s.min_value = 0; s.max_value = 5 if name=='Normal Strength' else 1
    outputs = ['Normal TS Encoded','Shadow Bias','Material ID Raw','Material Slot',
               'Metal Mask','Specular Mask','Hair Opacity','Eye Reveal Potential',
               'Smoothness','Roughness Approx','Emission Raw','Emission Remapped']
    for name in outputs:
        g.interface.new_socket(name=name,in_out='OUTPUT',socket_type='NodeSocketColor' if name=='Normal TS Encoded' else 'NodeSocketFloat')
    inp = g.nodes.new('NodeGroupInput'); inp.location = (-1000,0)
    out = g.nodes.new('NodeGroupOutput'); out.location = (1300,0)
    count = 0
    def node(typ,label):
        nonlocal count
        n = g.nodes.new(typ); n.label = label; n.name = label
        n.location = (-700+(count//7)*230,450-(count%7)*150); count += 1
        return n
    def put(value,socket):
        if isinstance(value,(int,float)): socket.default_value=value
        else: g.links.new(value,socket)
    def math(op,a,b=None,label=None):
        n=node('ShaderNodeMath',label or op); n.operation=op; put(a,n.inputs[0])
        if b is not None: put(b,n.inputs[1])
        return n.outputs[0]
    def separate(name):
        n=node('ShaderNodeSeparateColor',name); n.mode='RGB'
        g.links.new(inp.outputs[name+' RGB'],n.inputs['Color']);return n.outputs
    normal=separate('NormalMap'); ids=separate('LightMap'); surface=separate('MaterialMap')
    x=math('MULTIPLY',math('SUBTRACT',math('MULTIPLY',normal[0],2),1),inp.outputs['Normal Strength'],'Normal X')
    y=math('MULTIPLY',math('SUBTRACT',math('MULTIPLY',normal[1],2),1),inp.outputs['Normal Strength'],'Normal Y')
    y=math('MULTIPLY',y,math('SUBTRACT',1,math('MULTIPLY',inp.outputs['Flip Normal Y'],2)))
    zz=math('SUBTRACT',1,math('ADD',math('MULTIPLY',x,x),math('MULTIPLY',y,y)))
    z=math('SQRT',math('MAXIMUM',zz,0),label='Reconstruct Z (never use stored B)')
    z=math('MULTIPLY',z,math('SUBTRACT',1,math('MULTIPLY',inp.outputs['Backface'],2)))
    combine=node('ShaderNodeCombineXYZ','Signed tangent normal')
    for value,socket in zip([x,y,z],combine.inputs):put(value,socket)
    norm=node('ShaderNodeVectorMath','Normalize tangent normal');norm.operation='NORMALIZE'
    g.links.new(combine.outputs[0],norm.inputs[0])
    scale=node('ShaderNodeVectorMath','Encode scale');scale.operation='SCALE';scale.inputs['Scale'].default_value=.5
    g.links.new(norm.outputs['Vector'],scale.inputs[0])
    bias=node('ShaderNodeVectorMath','Encode bias');bias.operation='ADD';bias.inputs[1].default_value=(.5,.5,.5)
    g.links.new(scale.outputs['Vector'],bias.inputs[0]);g.links.new(bias.outputs['Vector'],out.inputs['Normal TS Encoded'])
    slot=math('LESS_THAN',ids[0],.2)
    for threshold in [.4,.6,.8]:slot=math('ADD',slot,math('LESS_THAN',ids[0],threshold))
    opacity=math('MAXIMUM',surface[0],inp.outputs['Min Hair Opacity'])
    rough=math('SUBTRACT',1,math('MULTIPLY',surface[1],inp.outputs['Glossiness']))
    remap=math('MINIMUM',math('MAXIMUM',math('MULTIPLY',math('SUBTRACT',surface[2],.2),1.25),0),1)
    bindings={'Shadow Bias':normal[2],'Material ID Raw':ids[0],'Material Slot':slot,
              'Metal Mask':ids[1],'Specular Mask':ids[2],'Hair Opacity':opacity,
              'Eye Reveal Potential':math('SUBTRACT',1,opacity),'Smoothness':surface[1],
              'Roughness Approx':rough,'Emission Raw':surface[2],'Emission Remapped':remap}
    for name,value in bindings.items():g.links.new(value,out.inputs[name])
    g.use_fake_user=True
    return g

def image_node(tree,path,*,data=True):
    """Keep data images separate from color images, preventing color-space conflicts."""
    import os
    path=os.path.abspath(path)
    role='data' if data else 'color'
    key=f'{path}|{role}'
    image=next((im for im in bpy.data.images if im.get('zzz_source_role')==key),None)
    if image is None:
        image=bpy.data.images.load(path,check_existing=False)
        image.colorspace_settings.name='Non-Color' if data else 'sRGB'
        image.alpha_mode='CHANNEL_PACKED' if data else 'STRAIGHT'
        image['zzz_source_role']=key
    node=tree.nodes.new('ShaderNodeTexImage');node.image=image
    node.extension='REPEAT';node.interpolation='Linear'
    return node
