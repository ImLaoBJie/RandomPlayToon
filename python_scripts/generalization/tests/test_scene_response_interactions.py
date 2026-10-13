"""Actual EEVEE interactions: nose side, bangs, light direction and light colour.

Run with -- input.blend. Input is never saved. Includes graph checks to ensure
colour does not drive the nose or bangs masks and scene tint is not repeated.
"""
import sys,json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
from random_play_toon import style_panel as ui
from random_play_toon.materials.scene_response import apply,contains_toon_colour

path=Path(sys.argv[sys.argv.index('--')+1]).resolve()
OUT=ROOT/'experiments/SceneResponseReview/Interactions'/path.stem;OUT.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(path),use_scripts=False);s=bpy.context.scene
before=ui.capture(s);audit=apply(s);assert ui.capture(s)==before
r=ui.registry(s);glob=r['global']
def setkey(key,value):
 label=next(e['label'] for e in glob['entries'] if e['key']==key)
 ui.node(glob).inputs[label].default_value=value
def ancestors(socket,seen=None):
 seen=set() if seen is None else seen
 for link in socket.links:
  n=link.from_node
  if link.from_socket.as_pointer() in seen:continue
  seen.add(link.from_socket.as_pointer());yield link.from_socket
  if n.type!='GROUP':
   for i in n.inputs:yield from ancestors(i,seen)

# The nose mask must never depend on the lit colour input.
ng=bpy.data.node_groups['RPT Stylized Nose v1']
go=next(n for n in ng.nodes if n.type=='GROUP_OUTPUT')
mask_inputs={x.name for x in ancestors(go.inputs['Mask']) if x.node.type=='GROUP_INPUT'}
assert 'Original' not in mask_inputs and 'Nose Direction' in mask_inputs,mask_inputs
checked=0
for e in r['materials']:
 tree=bpy.data.materials[e['material']].node_tree
 for node in tree.nodes:
  if node.type=='OUTPUT_AOV' and ('bang' in node.aov_name.lower() or node.aov_name=='RPT Hair'):
   assert not any('scene irradiance' in x.node.name.lower() for x in ancestors(node.inputs['Color']))
   checked+=1
  if node.name.startswith(('RPT tint supplementary reflected light','RPT authored highlight light colour')) and contains_toon_colour(node.inputs[0]):
   assert node.inputs[1].links[0].from_node.name.startswith('RPT prevent repeated scene tint')
assert checked

a=json.loads(s['rpt_nose_audit']);obj=bpy.data.objects[r.get('mesh_object','Vivian_Mapping')]
center=obj.matrix_world@(Vector(a['tip'])+Vector((0,0,a['face_width']*.15)))
s.camera.data.type='ORTHO';s.camera.data.ortho_scale=a['face_width']*1.8
s.camera.location=center+Vector((0,-2,0));s.camera.rotation_euler=(center-s.camera.location).to_track_quat('-Z','Y').to_euler()
s.render.resolution_x=s.render.resolution_y=320;s.render.resolution_percentage=100;s.eevee.taa_render_samples=64
for o in s.objects:
 if o.type=='LIGHT':o.hide_render=True
w=bpy.data.worlds.new('Interaction black world');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=0;s.world=w
lamp=bpy.data.objects.new('Interaction sun',bpy.data.lights.new('Interaction sun','SUN'));s.collection.objects.link(lamp);lamp.data.energy=.45
def render(name):
 ui.refresh(s);s.render.filepath=str(OUT/(name+'.png'));bpy.ops.render.render(write_still=True)
 im=bpy.data.images.load(s.render.filepath,check_existing=False);p=np.array(im.pixels[:]).reshape(im.size[1],im.size[0],4)[...,:3];bpy.data.images.remove(im)
 print('INTERACTION_RENDER',name,flush=True);return p
def changed(a,b):return int(np.count_nonzero(np.max(np.abs(a-b),axis=2)>2/255))

report={'source':str(path),'audit':audit,'nose_mask_inputs':sorted(mask_inputs),'bangs_masks_checked':checked,'modes':{}}
for mode in [0,1]:
 label='scene' if mode==0 else 'studio';ui.lighting_set(s,mode)
 setkey('Nose Enabled',True);setkey('Nose Opacity',.9);setkey('Nose Direction',35.)
 setkey('Eye Reveal Enabled',True);setkey('Eye Reveal Strength',1.)
 setkey('Light Color',(1,1,1,1));ui.set_light_angles(s,30.,35.)
 lamp.data.color=(1,1,1);lamp.rotation_euler=Vector((-.8,1,-.8)).to_track_quat('-Z','Y').to_euler()
 baseline=render(label+'_baseline')
 setkey('Nose Direction',-35.);nose=render(label+'_nose_other_side');setkey('Nose Direction',35.)
 if mode:ui.set_light_angles(s,-60.,35.)
 else:lamp.rotation_euler=Vector((.8,1,-.8)).to_track_quat('-Z','Y').to_euler()
 direction=render(label+'_other_light_direction')
 if mode:setkey('Light Color',(.12,.3,1,1))
 else:lamp.data.color=(.12,.3,1)
 blue=render(label+'_blue')
 setkey('Eye Reveal Enabled',False);no_eye=render(label+'_blue_no_eye_reveal')
 stats={'nose_side_pixels':changed(baseline,nose),'light_direction_pixels':changed(baseline,direction),'light_colour_pixels':changed(direction,blue),'eye_reveal_under_blue_pixels':changed(blue,no_eye)}
 assert all(n>10 for n in stats.values()),stats
 saved=ui.capture(s)
 for switch in [0,1,0,1,mode]:ui.lighting_set(s,switch)
 for mat,values in saved.items():
  for key,value in values.items():
   if key!='独立展示光照':assert ui.capture(s)[mat][key]==value
 report['modes'][label]=stats
# Older Vivian face controls are separate from the view-driven stylized nose.
face_controls={key:[ui.node(e).inputs[item['label']] for e in r['materials'] for item in e['entries'] if item['key']==key]
               for key in ['Nose Shadow','Chin Shadow','Face Softness']}
if face_controls['Nose Shadow']:
 ui.lighting_set(s,0);setkey('Nose Enabled',False);setkey('Eye Reveal Enabled',True)
 lamp.data.color=(1,1,1);lamp.data.energy=.4;lamp.rotation_euler=Vector((0,1,-.2)).to_track_quat('-Z','Y').to_euler()
 for key in ['Nose Shadow','Chin Shadow']:
  for socket in face_controls[key]:socket.default_value=0.
 zero=render('legacy_face_zero')
 for socket in face_controls['Nose Shadow']:socket.default_value=1.
 nose=render('legacy_face_nose')
 for socket in face_controls['Nose Shadow']:socket.default_value=0.
 for socket in face_controls['Chin Shadow']:socket.default_value=1.
 chin=render('legacy_face_chin')
 assert changed(zero,nose)>10 and changed(zero,chin)>10
 for socket in face_controls['Chin Shadow']:socket.default_value=0.
 for socket in face_controls['Face Softness']:socket.default_value=.02
 narrow=render('face_softness_002')
 for socket in face_controls['Face Softness']:socket.default_value=.04
 wider=render('face_softness_004')
 assert changed(narrow,wider)>10
 report['legacy_face']={'nose_pixels':changed(zero,nose),'chin_pixels':changed(zero,chin),'softness_below_008_pixels':changed(narrow,wider)}
(OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('INTERACTIONS_PASS',report['modes'],flush=True)
