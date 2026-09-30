"""Complete shared display controls using the frozen Vivian defaults as authority."""
import bpy,json
from pathlib import Path
from .. import style_panel as ui
from .style_upgrade import add,source,Graph,output,drive

def color_value(q,entry,key):
    n=q.node('ShaderNodeRGB','Control color · '+key)
    for i in range(4):drive(n.outputs[0],entry,key,i)
    return n.outputs[0]

def scale_existing_output(q,socket,factor):
    sinks=[l.to_socket for l in socket.links]
    scaled=q.math('MULTIPLY',socket,factor)
    for s in sinks:q.put(scaled,s)

def apply(scene,identity):
    if scene.get('rpt_vivian_parity')==1:return
    r=ui.registry(scene)
    if not r.get('generic'):return
    spec=json.loads((Path(__file__).with_name('vivian_global_defaults.json')).read_text(encoding='utf8'))
    glob=r['global'];gn=ui.node(glob);old_spec=gn.inputs['基础高光强度'].default_value;old_width=gn.inputs['基础高光宽度'].default_value
    for e in [glob]+r['materials']:
        e['legacy_label_sets']=[e.get('legacy_labels',[]),[s.name for s in ui.node(e).inputs]]
    for key,label,default,lo,hi,desc in [
        ('Black Background','黑色出图背景',True,0,1,'仅最终合成改为黑色出图背景；关闭恢复透明背景，不改变世界照明。'),
        ('Studio Emission','展示自发光增强',1.6,0,8,'独立展示模式下增强各部位自发光；场景模式保持部位原值。'),
        ('Display Light','展示亮面亮度',1.12,.5,2,'仅独立展示：增强卡通亮面，不改变原色纹理。'),
        ('Display Shadow','展示暗面深度',1.5,1,3,'仅独立展示：加深阴影颜色；1不额外加深。'),
        ('Outline Tint','描边颜色',tuple(spec['defaults']['描边颜色']),0,1,'全局描边颜色；各部位可关闭颜色使用全局，保留单独颜色。'),
    ]:add(glob,key,label,default,lo,hi,'07 描边' if key=='Outline Tint' else '00 光照方式',desc)
    # Keep every baseline control, category and ordering; data-map strength is extra.
    existing={e['key']:e for e in glob['entries']};ordered=[]
    for canonical in spec['entries']:
        e=existing.pop(canonical['key']);e['category']=canonical['category'];ordered.append(e)
    for e in existing.values():e['category']='10 控制贴图';ordered.append(e)
    glob['entries']=ordered
    for label,value in spec['defaults'].items():gn.inputs[label].default_value=value
    # Group headings also match in the node interface, not only the N panel.
    panels={p.name:p for p in gn.node_tree.interface.items_tree if p.item_type=='PANEL'}
    positions={}
    for e in glob['entries']:
        cat=e['category']
        if cat not in panels:panels[cat]=gn.node_tree.interface.new_panel(name=cat)
        socket=next(p for p in gn.node_tree.interface.items_tree if p.item_type=='SOCKET' and p.in_out=='INPUT' and p.name==e['label'])
        gn.node_tree.interface.move_to_parent(socket,panels[cat],positions.get(cat,0));positions[cat]=positions.get(cat,0)+1
        socket.default_value=gn.inputs[e['label']].default_value
    for e in r['materials']:
        n=ui.node(e);mat=bpy.data.materials[e['material']];q=Graph(mat.node_tree);toon=mat.node_tree.nodes['共享 EEVEE 卡通着色']
        # Different materials retain their calibration under the same global unit.
        n.inputs['部位高光倍率'].default_value*=old_spec
        add(e,'Local Highlight Width','部位高光宽度倍率',old_width,.1,8,'03 基础高光与边缘光','乘以全局高光宽度，按材质独立校准。')
        q.put(q.math('MULTIPLY',output(q,glob,'Highlight Width'),n.outputs['Local Highlight Width']),toon.inputs['Highlight Width'])
        for item in e['entries']:
            if item['key'] in ['Local Threshold','Local Width']:item.update(global_control=True,source_socket='明暗使用全局')
        mode=output(q,glob,'Studio Mode');light=output(q,glob,'Display Light');depth=output(q,glob,'Display Shadow')
        key=source(toon.inputs['Key Tint']);shadow=source(toon.inputs['Shadow Tint'])
        q.put(q.mix(key,q.vec('SCALE',key[:3] if isinstance(key,tuple) else key,light),mode),toon.inputs['Key Tint'])
        sep=q.node('ShaderNodeSeparateColor','Display shadow RGB');q.put(shadow,sep.inputs[0]);comb=q.node('ShaderNodeCombineColor','Display shadow depth')
        for i in range(3):q.put(q.math('POWER',q.math('MAXIMUM',sep.outputs[i],0),depth),comb.inputs[i])
        q.put(q.mix(shadow,comb.outputs[0],mode),toon.inputs['Shadow Tint'])
        boost=q.math('ADD',1,q.math('MULTIPLY',mode,q.math('SUBTRACT',output(q,glob,'Studio Emission'),1)))
        scale_existing_output(q,n.outputs['Glow Strength'],boost)
        if 'Review Glow' in n.outputs:scale_existing_output(q,n.outputs['Review Glow'],boost)
        # Global outline color with a per-part opt-out; existing exceptional brow colors survive.
        custom=max(abs(a-b) for a,b in zip(n.inputs['部位描边颜色'].default_value,(.035,.024,.055,1)))>1e-5
        add(e,'Use Global Outline Color','描边颜色使用全局',not custom,0,1,'07 描边','关闭后使用本部位描边颜色；已单独校准的眉毛默认关闭。')
        for item in e['entries']:
            if item['key']=='Outline Color':item.update(global_control=True,source_socket='描边颜色使用全局')
        shell=bpy.data.materials.get('RPT_Outline_'+str(e['slot']))
        if shell:
            sq=Graph(shell.node_tree);col=sq.mix(color_value(sq,e,'Outline Color'),color_value(sq,glob,'Outline Tint'),output(sq,e,'Use Global Outline Color'))
            sq.put(col,shell.node_tree.nodes['Outline'].inputs['Color'])
            premul=shell.node_tree.nodes.get('Outline premultiplied color')
            if premul:
                support=source(shell.node_tree.nodes['Outline eye support'].inputs['Color']);sq.put(sq.vec('SCALE',col,support),premul.inputs['Color'])
        # Hair has an authored highlight shape. Do not gate it with a tiny round lobe.
        if e['role']=='hair':
            q.put(0.,toon.inputs['Specular Strength'])
            dec=mat.node_tree.nodes.get('已审核的控制通道')
            if dec and 'LightMap · Non-Color' in mat.node_tree.nodes:
                add(e,'Hair Highlights','发束图形高光强度',.12,0,2,'05 头发','使用已配对 LightMap B 的原始高光带形状，随虚拟来光柔和变化，不再裁成圆形亮斑。')
                direction=mat.node_tree.nodes['Independent light / head pose'].outputs['Light Direction'];normal=source(toon.inputs['Normal'])
                facing=q.math('MAXIMUM',q.vec('DOT_PRODUCT',normal,direction),0)
                strength=q.math('MULTIPLY',n.outputs['Hair Highlights'],output(q,glob,'Global Specular'))
                mask=dec.outputs['Specular Mask']
                if identity in {'Alice','SunnaMaid'}:
                    # Lift the weak parts of the authored band, not its peak.
                    mask=q.math('POWER',q.math('MAXIMUM',mask,0),.7)
                band=q.math('MULTIPLY',mask,q.math('MULTIPLY',strength,q.math('ADD',.25,q.math('MULTIPLY',facing,.75))))
                em=mat.node_tree.nodes['Final stylized surface'];base=source(toon.inputs['Base Color'])
                surface=source(em.inputs['Color'])
                if identity in {'Alice','SunnaMaid'}:
                    # Hue-preserving shoulder prevents isolated hair peaks from
                    # crossing the shared bloom threshold and whitening the band.
                    add(e,'Hair Peak Limit','头发亮部柔化上限',.70,.4,2,'05 头发','压低头发底层过亮处并保留颜色，为高光带留出亮度空间；不改变全局辉光和其他部位。')
                    color=surface;sep=q.node('ShaderNodeSeparateColor','Hair peak RGB');q.put(color,sep.inputs[0])
                    peak=q.math('MAXIMUM',q.math('MAXIMUM',sep.outputs[0],sep.outputs[1]),sep.outputs[2])
                    knee=q.math('MULTIPLY',n.outputs['Hair Peak Limit'],.72);span=q.math('SUBTRACT',n.outputs['Hair Peak Limit'],knee)
                    excess=q.math('MAXIMUM',q.math('SUBTRACT',peak,knee),0)
                    compressed=q.math('ADD',q.math('MINIMUM',peak,knee),q.math('DIVIDE',q.math('MULTIPLY',span,excess),q.math('ADD',span,excess)))
                    surface=q.vec('SCALE',color,q.math('DIVIDE',compressed,q.math('MAXIMUM',peak,.0001)))
                    band=q.math('MULTIPLY',band,.75)
                q.put(q.vec('ADD',surface,q.vec('SCALE',base,band)),em.inputs['Color'])
                mat['rpt_hair_highlight']='verified LightMap B shape; no isotropic specular gate'
    from ..specializations.surface_refinement import tune_parity
    tune_parity(r,identity)
    g=scene.compositing_node_group;q=Graph(g);alpha=g.nodes['Preserve silhouette'];old=source(alpha.inputs['Alpha']);black=output(q,glob,'Black Background')
    q.put(q.math('ADD',q.math('MULTIPLY',old,q.math('SUBTRACT',1,black)),black),alpha.inputs['Alpha'])
    scene['zzz_stage6_registry']=json.dumps(r,ensure_ascii=False)
    ui.set_light_angles(scene,spec['defaults']['虚拟光水平角（度）'],spec['defaults']['虚拟光俯仰角（度）'])
    scene['zzz_stage6_defaults']=json.dumps(ui.capture(scene),ensure_ascii=False)
    scene['rpt_vivian_parity']=1;ui.refresh(scene)
