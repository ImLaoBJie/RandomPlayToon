"""Exercise the real build operator with an unregistered, renamed PMX.

Blender --background --factory-startup --python-exit-code 1 --python <this>
-- <uncalibrated PMX> <output directory>
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path
import bpy

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
import random_play_toon as addon
from random_play_toon.core import identify,preflight,PROFILES
from random_play_toon import style_panel as ui
from random_play_toon.specializations.generic import material_role

# LucySummer uses these names; accessories and mixed body atlases stay separate.
for name,expected in {'目高光 内':'eye_highlight','目高光 外':'eye_highlight',
    '后发':'hair','前发':'hair','口':'mouth','脖子':'skin',
    '发圈':'cloth','颈环':'cloth','体1':'cloth'}.items():
    assert material_role(name)==expected,(name,material_role(name))

source,out=(Path(arg).resolve() for arg in sys.argv[sys.argv.index('--')+1:])
out.mkdir(parents=True,exist_ok=True)
before_hash=hashlib.sha256(source.read_bytes()).hexdigest()
profile=identify(source)
assert profile['uncalibrated'] and profile['kind']=='uncalibrated'
assert profile['id'].startswith('Generic_')
renamed=out/'renamed_unknown.pmx';shutil.copy2(source,renamed)
assert identify(renamed)['id']==profile['id']
prepared,inputs=preflight(str(renamed),str(source.parent),'')
assert prepared['uncalibrated'] and inputs['textures']
assert all(not maps for maps in inputs['maps'].values())

# Existing exact profiles still take precedence and retain their map bindings.
for identity in ['Vivian','SunnaMaid']:
    expected=json.loads((PROFILES/(identity+'.json')).read_text(encoding='utf8'))
    known=ROOT/'assets_preprocessed'/expected['pmx']
    actual=identify(known)
    assert actual['id']==identity and not actual.get('uncalibrated')
    assert actual['materials']==expected['materials']

broken=out/'broken.pmx';broken.write_bytes(b'not a PMX')
try:identify(broken)
except ValueError:pass
else:raise AssertionError('Invalid PMX must still be rejected')

addon.register();scene=bpy.context.scene;settings=scene.rpt
assert bpy.ops.rpt.choose_pmx('EXEC_DEFAULT',filepath=str(renamed))=={'FINISHED'}
assert '未校准' in settings.status
settings.textures=str(source.parent);settings.assets=''
settings.output=str(out/'operator_result.blend');settings.auto_open=False
original_objects=tuple((o.name,o.as_pointer()) for o in scene.objects)
assert bpy.ops.rpt.build('EXEC_DEFAULT')=={'FINISHED'}
job=addon._job
try:job['process'].wait(timeout=180)
except Exception:
    job['process'].terminate()
    raise
addon.job_tick()
assert job['process'].returncode==0,job['log'].read_text(encoding='utf8',errors='replace')
assert tuple((o.name,o.as_pointer()) for o in scene.objects)==original_objects
assert settings.result==settings.output
result=json.loads(Path(settings.report).read_text(encoding='utf8'))
assert result['status']=='success'
bpy.ops.wm.open_mainfile(filepath=settings.output,use_scripts=False)
r=ui.registry(bpy.context.scene)
assert r['uncalibrated'] and len(r['materials'])==len(profile['materials'])
report=json.loads(bpy.context.scene['rpt_report'])
assert all(report['source_preserved'].values())
assert before_hash==hashlib.sha256(source.read_bytes()).hexdigest()
(out/'validation.json').write_text(json.dumps({'passed':True,'profile':profile['id'],
    'operator_without_assets':True,'renamed_model':True,'known_profiles_preserved':True,
    'invalid_file_rejected':True,'source_scene_preserved':True,'saved_reopened':True,
    'source_preserved':report['source_preserved']},ensure_ascii=False,indent=2),encoding='utf8')
print('GENERIC_OPERATOR_PASS',flush=True)
