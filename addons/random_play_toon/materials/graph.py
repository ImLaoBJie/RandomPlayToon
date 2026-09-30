"""Original EEVEE art-direction nodes; audited packed decoder remains unchanged.

SPDX-License-Identifier: GPL-3.0-or-later
This is an artist-oriented approximation, not a port of the full game renderer.
"""
import bpy


class Graph:
    def __init__(self, tree):
        self.t=tree; self.index=0

    def node(self, typ, name):
        n=self.t.nodes.new(typ); n.name=name; n.label=name
        n.location=((self.index//8)*230, -(self.index%8)*155)
        self.index+=1
        return n

    def put(self, v, s):
        if isinstance(v, bpy.types.NodeSocket): self.t.links.new(v,s)
        elif isinstance(v,(int,float)) and s.type=='RGBA': s.default_value=(v,v,v,1)
        elif isinstance(v,(int,float)) and s.type=='VECTOR': s.default_value=(v,v,v)
        else: s.default_value=v

    def math(self, op, a, b=None, name=None):
        n=self.node('ShaderNodeMath',name or op); n.operation=op
        self.put(a,n.inputs[0])
        if b is not None: self.put(b,n.inputs[1])
        return n.outputs[0]

    def vec(self, op, a, b=None, name=None):
        n=self.node('ShaderNodeVectorMath',name or op);n.operation=op
        self.put(a,n.inputs[0])
        if b is not None: self.put(b,n.inputs['Scale'] if op=='SCALE' else n.inputs[1])
        return n.outputs['Value' if op in ['DOT_PRODUCT','LENGTH','DISTANCE'] else 'Vector']

    def mix(self, a, b, fac, name='Mix', mode='MIX'):
        n=self.node('ShaderNodeMixRGB',name);n.blend_type=mode
        self.put(fac,n.inputs[0]);self.put(a,n.inputs[1]);self.put(b,n.inputs[2])
        return n.outputs[0]

    def smooth(self, value, lo, hi, name='Soft threshold'):
        x=self.math('DIVIDE',self.math('SUBTRACT',value,lo),self.math('MAXIMUM',self.math('SUBTRACT',hi,lo),.0001))
        x=self.math('MINIMUM',self.math('MAXIMUM',x,0),1)
        return self.math('MULTIPLY',self.math('MULTIPLY',x,x),self.math('SUBTRACT',3,self.math('MULTIPLY',x,2)),name)


def group(name, inputs, outputs):
    g=bpy.data.node_groups.new(name,'ShaderNodeTree');g.use_fake_user=True
    for label,typ,default in inputs:
        s=g.interface.new_socket(name=label,in_out='INPUT',socket_type=typ)
        s.default_value=default
    for label,typ in outputs:g.interface.new_socket(name=label,in_out='OUTPUT',socket_type=typ)
    q=Graph(g);i=q.node('NodeGroupInput','Inputs');o=q.node('NodeGroupOutput','Outputs')
    i.location=(-450,150);o.location=(3200,150)
    return g,q,i.outputs,o.inputs


def build_surface():
    F='NodeSocketFloat';C='NodeSocketColor';V='NodeSocketVector'
    inputs=[('Base Color',C,(.8,.8,.8,1)),('Normal',V,(0,0,1)),('Light Direction',V,(0,-1,1)),
        ('Shadow Bias',F,.5),('Bias Strength',F,.45),('Threshold',F,0),('Softness',F,.09),
        ('Shadow Tint',C,(.48,.43,.63,1)),('Key Tint',C,(1,.97,.94,1)),('Key Gain',F,1),
        ('Metal Mask',F,0),('Specular Mask',F,0),('Smoothness',F,.5),('Specular Strength',F,.2),
        ('Highlight Width',F,1),('Rim Strength',F,.035),('Emission Mask',F,0),('Emission Strength',F,0),
        ('Scene Shadow Strength',F,.35),('Material Slot',F,0)]
    g,q,i,o=group('ZZZ_ToonSurface_v1',inputs,[('Color',C),('Lit Factor',F),('Specular',F),('Scene Visibility',F)])
    geo=q.node('ShaderNodeNewGeometry','View / surface geometry')
    n=q.vec('NORMALIZE',i['Normal']);l=q.vec('NORMALIZE',i['Light Direction'])
    ndl=q.vec('DOT_PRODUCT',n,l,'Signed main-light cosine')
    bias=q.math('MULTIPLY',q.math('SUBTRACT',i['Shadow Bias'],.5),q.math('MULTIPLY',i['Bias Strength'],4))
    rampin=q.math('ADD',ndl,bias)
    lit=q.smooth(rampin,q.math('SUBTRACT',i['Threshold'],i['Softness']),q.math('ADD',i['Threshold'],i['Softness']))
    # Optional engine visibility: direct EEVEE white diffuse sees scene occluders.
    # The response is deliberately bounded; it is not an exact shadow-map extraction.
    d=q.node('ShaderNodeBsdfDiffuse','EEVEE white visibility probe');d.inputs['Color'].default_value=(1,1,1,1)
    q.put(n,d.inputs['Normal']);sr=q.node('ShaderNodeShaderToRGB','EEVEE scene visibility');q.put(d.outputs[0],sr.inputs[0])
    bw=q.node('ShaderNodeRGBToBW','Visibility luminance');q.put(sr.outputs['Color'],bw.inputs[0])
    vis=q.smooth(bw.outputs[0],.015,.16)
    visibility=q.math('SUBTRACT',1,q.math('MULTIPLY',q.math('SUBTRACT',1,vis),i['Scene Shadow Strength']))
    lit=q.math('MULTIPLY',lit,visibility)
    shade=q.mix(i['Shadow Tint'],i['Key Tint'],lit,'Art-directed shadow tint')
    color=q.mix(i['Base Color'],shade,1,'Multiply albedo by toon light','MULTIPLY')
    color=q.vec('SCALE',color,i['Key Gain'])
    h=q.vec('NORMALIZE',q.vec('ADD',l,geo.outputs['Incoming']))
    nh=q.math('MAXIMUM',q.vec('DOT_PRODUCT',n,h),0)
    exponent=q.math('DIVIDE',q.math('ADD',18,q.math('MULTIPLY',i['Smoothness'],160)),q.math('MAXIMUM',i['Highlight Width'],.1))
    spec=q.smooth(q.math('POWER',nh,exponent),.24,.64)
    spec=q.math('MULTIPLY',spec,q.math('MULTIPLY',i['Specular Mask'],i['Specular Strength']))
    # Numeric slots remain numeric: no automatic skin/hair semantics.
    slot_scale=q.math('ADD',.82,q.math('MULTIPLY',i['Material Slot'],.045))
    spec=q.math('MULTIPLY',q.math('MULTIPLY',spec,slot_scale),q.math('ADD',.15,q.math('MULTIPLY',lit,.85)))
    spectint=q.mix((1,.95,.99,1),i['Base Color'],q.math('MULTIPLY',i['Metal Mask'],.72),'Metal-tinted highlight')
    color=q.vec('ADD',color,q.vec('SCALE',spectint,spec))
    nv=q.math('MAXIMUM',q.vec('DOT_PRODUCT',n,geo.outputs['Incoming']),0)
    rim=q.math('MULTIPLY',q.math('POWER',q.math('SUBTRACT',1,nv),3),i['Rim Strength'])
    rim=q.math('MULTIPLY',rim,q.math('MAXIMUM',ndl,.12))
    color=q.vec('ADD',color,q.vec('SCALE',(.64,.69,1),rim))
    color=q.vec('ADD',color,q.vec('SCALE',i['Base Color'],q.math('MULTIPLY',i['Emission Mask'],i['Emission Strength'])))
    for name,value in [('Color',color),('Lit Factor',lit),('Specular',spec),('Scene Visibility',vis)]:q.put(value,o[name])
    g['description']='EEVEE toon art direction; bounded scene visibility, not full HoyoToon shader.'
    return g


def build_face():
    F='NodeSocketFloat';V='NodeSocketVector';C='NodeSocketColor'
    g,q,i,o=group('ZZZ_FaceDirection_v1',[
        ('Base Color',C,(1,.8,.7,1)),('Direction Field',C,(.5,1,.5,1)),('Feature Masks',C,(0,0,0,1)),
        ('Rest Position',V,(0,0,1.467)),('UV Correction',F,0),
        ('Head Right',V,(1,0,0)),('Head Forward',V,(0,-1,0)),('Head Up',V,(0,0,1)),('Light Direction',V,(0,-1,1)),
        ('Threshold',F,.05),('Softness',F,.14),('Nose Strength',F,.12),('Chin Strength',F,.18),
        ('Shadow Tint',C,(.72,.53,.61,1)),('Key Tint',C,(1,.97,.94,1)),('Key Gain',F,1)], [('Color',C),('Lit Factor',F)])
    # A small set of overlapping/subpixel UV triangles uses the same field
    # evaluated from interpolated rest position. No source UV is changed.
    pos=q.node('ShaderNodeSeparateXYZ','Rest position for UV exceptions');q.put(i['Rest Position'],pos.inputs[0])
    nx=q.math('MULTIPLY',q.math('MINIMUM',q.math('MAXIMUM',q.math('DIVIDE',pos.outputs['X'],.0713),-1),1),.91)
    ny=q.math('SQRT',q.math('MAXIMUM',q.math('SUBTRACT',1,q.math('MULTIPLY',nx,nx)),.08))
    nz=q.math('MULTIPLY',q.math('MINIMUM',q.math('MAXIMUM',q.math('DIVIDE',q.math('SUBTRACT',pos.outputs['Z'],1.467),.08),-.85),.8),.5)
    comb=q.node('ShaderNodeCombineXYZ','Analytic exception direction')
    for value,socket in zip([nx,ny,nz],comb.inputs):q.put(value,socket)
    replacement=q.vec('ADD',q.vec('SCALE',q.vec('NORMALIZE',comb.outputs[0]),.5),(.5,.5,.5))
    direction=q.mix(i['Direction Field'],replacement,i['UV Correction'],'Correct overlapping UV triangles')
    decode=q.vec('SCALE',q.vec('SUBTRACT',direction,(.5,.5,.5)),2)
    sep=q.node('ShaderNodeSeparateXYZ','Authored head-frame direction');q.put(decode,sep.inputs[0])
    world=q.vec('ADD',q.vec('ADD',q.vec('SCALE',i['Head Right'],sep.outputs['X']),q.vec('SCALE',i['Head Forward'],sep.outputs['Y'])),q.vec('SCALE',i['Head Up'],sep.outputs['Z']))
    l=q.vec('NORMALIZE',i['Light Direction'])
    cosine=q.vec('DOT_PRODUCT',q.vec('NORMALIZE',world),l)
    nx2=q.math('POWER',q.math('DIVIDE',pos.outputs['X'],.010),2)
    nz2=q.math('POWER',q.math('DIVIDE',q.math('SUBTRACT',pos.outputs['Z'],1.435),.012),2)
    nose_fix=q.math('EXPONENT',q.math('MULTIPLY',q.math('ADD',nx2,nz2),-1))
    chin_fix=q.smooth(pos.outputs['Z'],1.387,1.414)
    maskfix=q.node('ShaderNodeCombineXYZ','Exception feature masks');q.put(nose_fix,maskfix.inputs[0]);q.put(q.math('SUBTRACT',1,chin_fix),maskfix.inputs[1]);maskfix.inputs[2].default_value=1
    masks=q.node('ShaderNodeSeparateColor','R nose / G chin / B valid UV')
    q.put(q.mix(i['Feature Masks'],maskfix.outputs[0],i['UV Correction']),masks.inputs['Color'])
    lateral=q.math('ABSOLUTE',q.vec('DOT_PRODUCT',l,i['Head Right']))
    overhead=q.math('MAXIMUM',q.vec('DOT_PRODUCT',l,i['Head Up']),0)
    nose=q.math('MULTIPLY',q.math('MULTIPLY',masks.outputs[0],lateral),i['Nose Strength'])
    chin=q.math('MULTIPLY',q.math('MULTIPLY',masks.outputs[1],overhead),i['Chin Strength'])
    value=q.math('SUBTRACT',q.math('SUBTRACT',cosine,nose),chin)
    lit=q.smooth(value,q.math('SUBTRACT',i['Threshold'],i['Softness']),q.math('ADD',i['Threshold'],i['Softness']))
    tint=q.mix(i['Shadow Tint'],i['Key Tint'],lit)
    color=q.vec('SCALE',q.mix(i['Base Color'],tint,1,mode='MULTIPLY'),i['Key Gain'])
    q.put(color,o['Color']);q.put(lit,o['Lit Factor'])
    g['description']='Authored UV direction field, not recovered game SDF. Frame follows head bone.'
    return g
