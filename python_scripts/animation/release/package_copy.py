"""Build the installable RandomPlayCopy add-on from the checked-in source."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
source=ROOT/'addons/random_play_copy';dest=ROOT/'dist/random_play_copy_0.8.4.zip'
dest.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in sorted(source.rglob('*')):
  if p.is_file() and (p.suffix in {'.py','.md'} or p.name in {'LICENSE','NOTICE'}):
   info=zipfile.ZipInfo(str(p.relative_to(source.parent)).replace('\\','/'),date_time=(2026,9,25,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
   z.writestr(info,p.read_bytes())
print(dest,hashlib.sha256(dest.read_bytes()).hexdigest())
