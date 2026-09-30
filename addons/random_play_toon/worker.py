"""Entry point for Blender --background --python worker.py -- request.json."""
import sys,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
request=Path(sys.argv[sys.argv.index('--')+1]);args=json.loads(request.read_text(encoding='utf8'))
status=Path(args.pop('status_file'))
try:
    from random_play_toon.core import build
    result=build(**args)
except Exception as exc:
    traceback.print_exc();result={'status':'error','message':str(exc),'traceback':traceback.format_exc()}
status.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
if result['status']!='success':sys.exit(1)
