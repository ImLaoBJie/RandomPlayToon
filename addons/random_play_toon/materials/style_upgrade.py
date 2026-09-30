"""Shared controls migrated from the verified Vivian workflow."""
import bpy,json,math
from .. import style_panel as ui
from .graph import Graph
from .controls import output,drive

def source(socket):
    if socket.is_linked:return socket.links[0].from_socket
    v=socket.default_value
    return v if isinstance(v,(bool,int,float)) else tuple(v)

def add(entry,key,label,value,lo,hi,category,description):
    n=ui.node(entry);g=n.node_tree
    if label in n.inputs:return
    typ='NodeSocketColor' if isinstance(value,(tuple,list)) else 'NodeSocketBool' if isinstance(value,bool) else 'NodeSocketFloat'
    panel=next((p for p in g.interface.items_tree if p.item_type=='PANEL' and p.name==category),None)
    if panel is None:panel=g.interface.new_panel(name=category)
    s=g.interface.new_socket(name=label,in_out='INPUT',socket_type=typ,parent=panel);s.default_value=value;s.description=description
    if typ=='NodeSocketFloat':s.min_value=lo;s.max_value=hi
    o=g.interface.new_socket(name=key,in_out='OUTPUT',socket_type=typ)
    gi=next(n for n in g.nodes if n.type=='GROUP_INPUT');go=next(n for n in g.nodes if n.type=='GROUP_OUTPUT');g.links.new(gi.outputs[s.identifier],go.inputs[o.identifier]);n.inputs[label].default_value=value
    entry['entries'].append({'key':key,'label':label,'category':category,'description':description})

def common_controls(s,r):
    glob=r['global'];gn=ui.node(glob);comp=s.compositing_node_group
    for spec in [
        ('Highlight Width','基础高光宽度',1.,.1,8,'03 基础高光与边缘光','增大卡通高光宽度，与高光强度分别控制。'),
        ('Eye Reveal Enabled','启用刘海透眼',True,0,1,'08 刘海透眼','关闭眼部合成，不改变头发和眼影本身。'),
        ('Eye Reveal Front Angle','开始衰减角度（度）',45.,0,89,'08 刘海透眼','正面观察夹角超过此值后开始衰减。'),
        ('Eye Reveal Side Angle','完全关闭角度（度）',80.,1,90,'08 刘海透眼','侧视达到此夹角时关闭；内部保证阈值至少相差1度。'),
        ('Bloom Size','光晕扩散范围',float(comp.nodes['辉光'].inputs['Size'].default_value),0,1,'09 画面效果','控制 F12 合成光晕扩散范围。'),
        ('Warmth','暖色调比例',0.,0,3,'09 画面效果','与薇薇安相同的暖色乘色公式；0保留当前颜色，1轻微暖化，3进一步增强。'),
    ]:add(glob,*spec)
    for e in glob['entries']:
        if e['key']=='Key Gain':e['category']='01 全局明暗'
        if e['key'] in ['Global Specular','Rim Strength']:e['category']='03 基础高光与边缘光'
    for e in r['materials']:
        n=ui.node(e);mat=bpy.data.materials[e['material']];q=Graph(mat.node_tree);toon=mat.node_tree.nodes['共享 EEVEE 卡通着色']
        if e['role'] not in {'eyes','eye_white','eye_highlight','eye_shadow','brows_lashes','mouth','mouth_line'}:
            add(e,'Use Global Lighting','明暗使用全局',True,0,1,'01 明暗','开启使用全局分界与宽度；关闭启用本部位独立设置，原部位倍率继续生效。')
            add(e,'Local Threshold','部位明暗分界',gn.inputs['身体明暗分界'].default_value,-1,1,'01 明暗','关闭明暗使用全局后生效。')
            add(e,'Local Width','部位过渡宽度',gn.inputs['身体过渡宽度'].default_value,.001,1,'01 明暗','关闭明暗使用全局后生效，再乘部位过渡倍率。')
            q.put(q.mix(n.outputs['Local Threshold'],output(q,glob,'Body Threshold'),n.outputs['Use Global Lighting']),toon.inputs['Threshold'])
            q.put(q.math('MULTIPLY',q.mix(n.outputs['Local Width'],output(q,glob,'Body Softness'),n.outputs['Use Global Lighting']),n.outputs['Local Softness']),toon.inputs['Softness'])
        q.put(output(q,glob,'Highlight Width'),toon.inputs['Highlight Width'])
        if e['role']=='hair':
            # Find the old angle smoothstep from its cosine dot-product source.
            geo=mat.node_tree.nodes['Surface'];direction=mat.node_tree.nodes['Independent light / head pose']
            cosine=q.vec('DOT_PRODUCT',direction.outputs['Head Forward'],geo.outputs['Incoming'])
            front=output(q,glob,'Eye Reveal Front Angle');side=output(q,glob,'Eye Reveal Side Angle')
            a=q.math('MINIMUM',front,q.math('SUBTRACT',side,1));b=q.math('MAXIMUM',side,q.math('ADD',front,1))
            fade=q.smooth(cosine,q.math('COSINE',q.math('MULTIPLY',b,math.pi/180)),q.math('COSINE',q.math('MULTIPLY',a,math.pi/180)))
            ao=mat.node_tree.nodes['Front bangs only'];att=mat.node_tree.nodes['Selected front bangs'];dec=mat.node_tree.nodes.get('已审核的控制通道')
            reveal=dec.outputs['Eye Reveal Potential'] if dec else 1.
            influence=output(q,glob,'Eye Reveal Texture Influence');reveal=q.math('ADD',q.math('SUBTRACT',1,influence),q.math('MULTIPLY',influence,reveal))
            q.put(q.math('MULTIPLY',att.outputs['Fac'],q.math('MULTIPLY',reveal,fade)),ao.inputs['Color'])
    q=Graph(comp)
    if '只混合眼部' in comp.nodes:
        mix=comp.nodes['只混合眼部'];q.put(q.math('MULTIPLY',source(mix.inputs[0]),output(q,glob,'Eye Reveal Enabled')),mix.inputs[0])
    drive(comp.nodes['辉光'].inputs['Size'],glob,'Bloom Size')
    alpha=comp.nodes['Preserve silhouette'];color=source(alpha.inputs['Image']);amount=output(q,glob,'Warmth');tint=q.node('CompositorNodeCombineColor','Review warmth')
    for i,d in enumerate([.06,-.015,-.07]):q.put(q.math('ADD',1,q.math('MULTIPLY',amount,d)),tint.inputs[i])
    q.put(q.mix(color,tint.outputs[0],1,'Warmth 0–3','MULTIPLY'),alpha.inputs['Image'])
