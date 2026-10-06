"""Freeze the approved 0.9.3 UI into the independently installable ABC add-on."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / 'addons/random_play_toon/style_panel.py'
s = source.read_text(encoding='utf8')
# Namespace UI identifiers only: scene registry/character/node names remain shared.
s = s.replace('RPT_', 'RPCSTYLE_').replace('rpt.', 'rpcstyle.')
for name in ['style_slot', 'style_help', 'lighting_mode', 'studio_azimuth', 'studio_elevation', 'character_tab_handler']:
    s = s.replace('rpt_' + name, 'rpc_style_' + name)
s = s.replace("'rpt_'+entry", "'rpc_style_'+entry")
s = s.replace("bl_category='Vivian'", "bl_category='ABC渲染'")
s = s.replace("return context.scene.get('zzz_stage6_schema') in [1,2]", "return bool(context.scene.get('rpc_transfer')) and context.scene.get('zzz_stage6_schema') in [1,2]")
s = s.replace("label=scene.get('rpt_character','Vivian')", "label='ABC渲染'")
s = s.replace("label='ABC渲染' if scene is not None else 'Vivian'", "label='ABC渲染'")
s = s.replace('def make_preset(scene,name):', 'def source_make_preset(scene,name):')
pos = s.index('class RPCSTYLE_OT_preset')
adapter = '''def make_preset(scene,name):
    values=source_make_preset(scene,name)
    report=json.loads(scene.get('rpc_transfer','{}'))
    scale=report.get('head',{}).get('source_to_cache_scale',1.)
    r=registry(scene)
    for item in r['global']['entries']:
        if item['key']=='Outline Width':
            values[r['global']['material']][item['label']]*=scale
    return values

'''
s = s[:pos] + adapter + s[pos:]
source_header="bl_info={'name':'RandomPlayToon · 参数面板','author':'Vivian rendering experiment','version':(0,9,3)"
copy_header="bl_info={'name':'RandomPlayCopy · 参数面板','author':'Vivian rendering experiment','version':(0,8,7)"
assert source_header in s
s=s.replace(source_header,copy_header,1)
header = '# Frozen from RandomPlayToon 0.9.3; regenerate with sync_copy_style_panel.py.\n# Source SHA256: ' + hashlib.sha256(source.read_bytes()).hexdigest() + '\n'
(ROOT/'addons/random_play_copy/style_panel.py').write_text(header+s, encoding='utf8')
print('Independent style panel synchronized')
