from pathlib import Path
import ast,zipfile,hashlib,json
ROOT=Path(__file__).resolve().parents[3];package=ROOT/'addons/random_play_toon'
assert (package/'LICENSE').is_file() and (package/'NOTICE').is_file()
tree=ast.parse((package/'__init__.py').read_text(encoding='utf-8-sig'))
info=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='bl_info' for t in node.targets))
version='.'.join(str(v) for v in info['version'])
assert (package/'_vendor/mmd_tools/LICENSE').is_file() and (package/'_vendor/mmd_tools/UPSTREAM.json').is_file()
target=ROOT/f'dist/random_play_toon_{version}.zip';files=sorted(p for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
target.parent.mkdir(parents=True,exist_ok=True)
manifest={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for p in files:archive.write(p,'random_play_toon/'+p.relative_to(package).as_posix())
report={'name':'RandomPlayToon','version':version,'zip':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'files':manifest}
target.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print({k:v for k,v in report.items() if k!='files'})
