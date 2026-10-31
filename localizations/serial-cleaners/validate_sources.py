"""Offline validation of this source-only export; no network/game/process access."""
from pathlib import Path
import json,hashlib,unicodedata,collections
W=Path(__file__).resolve().parent
load=lambda p:json.loads((W/p).read_text(encoding='utf-8'))
rows=load('raw_strings.json');assert len(rows)==3951;assert len({r['id'] for r in rows})==3951
for r in rows:
 assert hashlib.sha256(r['source'].encode('utf-8')).hexdigest()==r['source_sha256'],r['id']
 if r['role']=='TRANSLATE':assert r['translation_state']=='APPROVED' and r['ready_to_patch'] and r['target'],r['id']
 assert unicodedata.normalize('NFC',r['target'])==r['target'],r['id']
assert collections.Counter(r['role'] for r in rows)=={'TRANSLATE':3947,'PROTECT':4}
from research_scope.patch_outside_i2 import load_selection
inventory,selected,skipped=load_selection(W/'research_scope/outside_authored_strings.json');assert len(inventory)==412 and len(selected)==386
outside=load('research_scope/outside_authored_strings.json')['strings'];assert collections.Counter(r['translation_state'] for r in outside)=={'APPROVED':388,'PROTECTED':21,'NEEDS_REVIEW':3}
manifest=load('publication_manifest.json');assert len(manifest['files'])==len({r['path'] for r in manifest['files']})
actual={p.relative_to(W).as_posix() for p in W.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in {'publication_manifest.json','translation_structure_audit.json','outside_i2_patcher_tests.json'}}
assert actual=={r['path'] for r in manifest['files']},actual^{r['path'] for r in manifest['files']}
for r in manifest['files']:
 p=W/r['path'];assert p.resolve().is_relative_to(W);raw=p.read_bytes();assert len(raw)==r['bytes'] and hashlib.sha256(raw).hexdigest()==r['sha256'],r['path']
print('PASS:3951I2records(3947approved/4protected),412outside(386actualfieldchanges),allpublicationhashes')
