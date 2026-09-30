"""Background worker: blender -b --factory-startup --python worker.py -- request.json."""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
request = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf8'))
status = Path(request.pop('status_file'))
try:
    from random_play_copy.core import build
    result = build(**request)
except Exception as exc:
    traceback.print_exc()
    result = dict(status='error', message=str(exc), traceback=traceback.format_exc())
status.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
if result['status'] != 'success':
    sys.exit(1)
