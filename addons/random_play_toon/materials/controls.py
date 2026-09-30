"""Shared, Chinese-labelled controls stored only in real shader sockets."""
import bpy,json,math
from mathutils import Vector
from .graph import Graph

# key, label, default, range, category, explanation
GLOBAL=[
 ('Key Gain','角色受光亮度',1.,0,3,'01 明暗','调整角色受光亮度，自发光独立。'),
 ('Body Threshold','身体明暗分界',0.,-1,1,'01 明暗','增大时暗部扩大，减小时亮部扩大。'),
 ('Body Softness','身体过渡宽度',.075,.001,1,'01 明暗','越小越接近硬边赛璐璐。'),
 ('Normal Strength','法线细节强度',.65,0,2,'01 明暗','只作用于已确认配对的法线 RG 通道。'),
 ('Global Specular','基础高光强度',.32,0,4,'03 高光','按 LightMap B 遮罩增强卡通高光。'),
 ('Rim Strength','边缘光强度',.035,0,1,'03 高光','掠视角的风格化亮边，不是几何描边。'),
 ('Outline Width','描边厚度（场景单位）',.00055,0,.005,'07 描边','保留原网格，以独立反面壳生成描边。'),
 ('Eye Reveal Strength','透眼强度',.8,0,1,'08 刘海透眼','只混合已标记刘海后实际可见的眼部，F12 查看。'),
 ('Eye Reveal Texture Influence','透眼贴图影响',.5,0,1,'08 刘海透眼','控制已配对的 MaterialMap R 对局部透眼的影响。'),
 ('Eye Reveal Brow Strength','眉睫透出比例',.5,0,1,'08 刘海透眼','眉睫相对眼白和虹膜的透出比例。'),
 ('Bloom Strength','辉光强度',.18,0,5,'09 画面效果','仅在亮度超过阈值处产生辉光，0 关闭。'),
 ('Bloom Threshold','辉光亮度阈值',1.,0,10,'09 画面效果','提高可避免普通亮部产生光晕。'),
 ('Studio Mode','独立展示光照',True,0,1,'00 光照','开启时由虚拟光向控制；关闭时增加 EEVEE 场景遮挡响应。'),
 ('Studio Azimuth','虚拟光水平角（度）',-125.,-180,180,'00 光照','绕角色旋转虚拟来光方向。'),
 ('Studio Elevation','虚拟光俯仰角（度）',45.,-90,90,'00 光照','调整虚拟来光的高度。'),
]
LOCAL=[
 ('Base Tint','原色乘色',(1.,1.,1.,1.),0,1,'02 原色与阴影','与原始贴图相乘；默认保留角色配色。'),
 ('Shadow Tint','阴影乘色',(.55,.49,.65,1),0,1,'02 原色与阴影','本部位的阴影色。'),
 ('Local Gain','部位亮度',1.,0,3,'01 明暗','在全局受光亮度上乘以本部位亮度。'),
 ('Local Softness','部位过渡倍率',1.,.1,5,'01 明暗','全局过渡宽度的倍率，可分别柔化脸部和身体。'),
 ('Local Specular','部位高光倍率',1.,0,5,'03 高光','本部位相对全局高光的倍率。'),
 ('Metal Reflection','金属反光强度',.2,0,3,'04 金属','由已确认金属遮罩限定的虚拟环境反光。'),
 ('Glow Strength','自发光强度',0.,0,8,'06 自发光','有 MaterialMap 时使用 B 发光遮罩；屏幕与能量核心可全表面发光。'),
 ('Opacity','表面不透明度',1.,0,1,'05 表面','真实表面透明度，与刘海选择性透眼独立。'),
 ('Outline Scale','部位描边倍率',1.,0,3,'07 描边','乘以全局描边厚度；0关闭本部位外扩描边，不改变贴图中原有的线条。'),
 ('Outline Color','部位描边颜色',(.035,.024,.055,1.),0,1,'07 描边','仅调整本部位的几何描边颜色；独立于原色贴图和其他部位。眉眼描边也参与局部透眼。'),
]

def make_node(mat,name,specs):
    g=bpy.data.node_groups.new(name+' · '+mat.name,'ShaderNodeTree')
    i=g.nodes.new('NodeGroupInput');o=g.nodes.new('NodeGroupOutput');o.location=(280,0);panels={};entries=[]
    for key,label,value,lo,hi,category,desc in specs:
        typ='NodeSocketColor' if isinstance(value,(tuple,list)) else 'NodeSocketBool' if isinstance(value,bool) else 'NodeSocketFloat'
        panel=panels.get(category)
        if panel is None:panel=g.interface.new_panel(name=category);panels[category]=panel
        s=g.interface.new_socket(name=label,in_out='INPUT',socket_type=typ,parent=panel);s.default_value=value;s.description=desc
        if typ=='NodeSocketFloat':s.min_value=lo;s.max_value=hi
        t=g.interface.new_socket(name=key,in_out='OUTPUT',socket_type=typ);g.links.new(i.outputs[s.identifier],o.inputs[t.identifier])
        entries.append({'key':key,'label':label,'category':category,'description':desc})
    n=mat.node_tree.nodes.new('ShaderNodeGroup');n.name=name;n.label='全局参数' if name=='ZZZ_GlobalControls' else '部位参数';n.node_tree=g;n.location=(-900,400);n.width=300
    return n,{'material':mat.name,'node':name,'entries':entries}

def drive(socket,entry,key,component=None):
    label=next(x['label'] for x in entry['entries'] if x['key']==key)
    fc=socket.driver_add('default_value') if component is None else socket.driver_add('default_value',component)
    d=fc.driver;d.type='SCRIPTED';v=d.variables.new();v.name='v';v.type='SINGLE_PROP';t=v.targets[0];t.id_type='MATERIAL';t.id=bpy.data.materials[entry['material']]
    t.data_path='node_tree.nodes['+json.dumps(entry['node'])+'].inputs['+json.dumps(label,ensure_ascii=False)+'].default_value'+('['+str(component)+']' if component is not None else '')
    d.expression='v'

def output(q,entry,key):
    n=q.node('ShaderNodeValue','全局 · '+key);drive(n.outputs[0],entry,key);return n.outputs[0]

def location_output(q,obj):
    n=q.node('ShaderNodeCombineXYZ',obj.name+' world position')
    for j in range(3):
        d=n.inputs[j].driver_add('default_value').driver;d.type='SCRIPTED';v=d.variables.new();v.name='v';v.type='TRANSFORMS';v.targets[0].id=obj;v.targets[0].transform_type=['LOC_X','LOC_Y','LOC_Z'][j];v.targets[0].transform_space='WORLD_SPACE';d.expression='v'
    return n.outputs[0]

def empty(name):
    o=bpy.data.objects.new(name,None);bpy.context.scene.collection.objects.link(o);o.empty_display_size=.1;return o

def initialize(scene,obj,profile):
    mat=bpy.data.materials.new('RPT_全局风格控制');mat.use_nodes=True;mat.node_tree.nodes.clear();n,glob=make_node(mat,'ZZZ_GlobalControls',GLOBAL);mat.use_fake_user=True
    dashboard=bpy.data.objects.new('ZZZ_StyleDashboard',bpy.data.meshes.new('RPT Dashboard'));scene.collection.objects.link(dashboard);dashboard.data.materials.append(mat);dashboard.hide_render=True;dashboard.hide_set(True)
    ctrl=empty('ZZZ_StyleControls');ctrl.hide_render=True
    light=empty('ZZZ_StudioLightDirection');light.empty_display_type='SINGLE_ARROW';light.empty_display_size=.6;light.location=(.6,0,1.5)
    a,b=math.radians(-125),math.radians(45);light.rotation_euler=(0,math.pi/2-b,a)
    tip=empty('RPT_LightTip');tip.parent=light;tip.location=(0,0,1);tip.hide_set(True)
    g=bpy.data.node_groups.new('RPT_Directions','ShaderNodeTree');q=Graph(g);out=q.node('NodeGroupOutput','Directions')
    def put(key,value):
        s=g.interface.new_socket(name=key,in_out='OUTPUT',socket_type='NodeSocketVector');q.put(value,out.inputs[s.identifier])
    put('Light Direction',q.vec('NORMALIZE',q.vec('SUBTRACT',location_output(q,tip),location_output(q,light))))
    arm=obj.find_armature();bone=next((b for b in arm.data.bones if b.name in ['頭','head','Head']),None) if arm else None
    head=empty('RPT_HeadFrame')
    if bone:
        c=head.constraints.new('COPY_TRANSFORMS');c.target=arm;c.subtarget=bone.name;rest=(arm.matrix_world@bone.matrix_local).to_3x3()
    for label,axis in [('Right',(1,0,0)),('Forward',(0,-1,0)),('Up',(0,0,1))]:
        if bone:
            t=empty('RPT_Head'+label);t.parent=head;t.location=rest.inverted()@Vector(axis);t.hide_set(True)
            value=q.vec('NORMALIZE',q.vec('SUBTRACT',location_output(q,t),location_output(q,head)))
        else:value=axis
        put('Head '+label,value)
    head.hide_set(True)
    return {'global':glob,'materials':[],'controller':light.name,'mesh_object':obj.name,'generic':True,'revision':2,'live_preview':True},g

def preset_values(scene,name):
    from ..style_panel import generic_preset_values
    return generic_preset_values(scene,name)
