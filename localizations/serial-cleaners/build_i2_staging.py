"""Build both I2 copies from immutable originals; no install, no launch."""
from pathlib import Path
import argparse,json,hashlib,copy,collections,UnityPy
W=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--allow-partial',action='store_true');a=ap.parse_args();out=a.out.resolve();assert out.is_relative_to(W) and not out.exists();out.mkdir(parents=True)
 rows=json.loads((W/'raw_strings.json').read_text(encoding='utf-8')); manifest=json.loads((W/'original_manifest.json').read_text(encoding='utf-8'))
 # initialallowedfiles remainoriginalbackups, do not derive additional patchscope here
 allowed=json.loads((W/'allowed_files.json').read_text(encoding='utf-8'));life=next(x for x in allowed if '/lifetimesystems_' in x);boot='SerialCleaners_Data/data.unity3d'
 pending=[r['id'] for r in rows if r['role']=='TRANSLATE' and not(r['translation_state']=='APPROVED' and r['ready_to_patch'])]
 assert a.allow_partial or not pending,('Incomplete translation approval',pending)
 expected={r['path']:r['sha256'] for r in manifest['files']}
 for rel in [life,boot]:assert sha(W/'original'/rel)==expected[rel],('Originalbackupchanged',rel)
 origlife=W/'original'/life;le=UnityPy.load(str(origlife));lo=next(o for o in le.objects if o.path_id==-871675835955643378);nodes=lo.serialized_type.nodes
 reports=[];source_trees=[]
 for rel,pid in [(life,-871675835955643378),(boot,906)]:
  src=W/'original'/rel;env=UnityPy.load(str(src));obj=next(o for o in env.objects if o.path_id==pid and o.type.name=='MonoBehaviour');old=obj.read_typetree(nodes=nodes);t=copy.deepcopy(old);terms=t['mSource']['mTerms'];assert len(terms)==len(rows)==3951
  n=0
  for r in rows:
   i=r['resource_address']['term_index'];term=terms[i];assert term['Term']==r['resource_address']['term_key'] and term['Languages'][0]==r['source']
   if r['ready_to_patch'] and r['translation_state']=='APPROVED':assert r['target'];term['Languages'][0]=r['target'];n+=1
  before={(o.assets_file.name,o.path_id):(o.type.name,hashlib.sha256(o.get_raw_data()).hexdigest()) for o in env.objects};obj.save_typetree(t,nodes=nodes);data=next(iter(env.files.values())).save(packer='lz4');dst=out/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
  e=UnityPy.load(str(dst));o=next(o for o in e.objects if o.path_id==pid and o.type.name=='MonoBehaviour');rt=o.read_typetree(nodes=nodes);assert rt==t
  after={(o.assets_file.name,o.path_id):(o.type.name,hashlib.sha256(o.get_raw_data()).hexdigest()) for o in e.objects};assert before.keys()==after.keys();changed=[k for k in before if before[k]!=after[k]];assert changed==[(obj.assets_file.name,pid)]
  restored=copy.deepcopy(rt)
  for i,x in enumerate(old['mSource']['mTerms']):restored['mSource']['mTerms'][i]['Languages'][0]=x['Languages'][0]
  assert restored==old
  source_trees.append(rt['mSource'])
  reports.append({'file':rel,'approved_cells':n,'sha256':sha(dst),'bytes':len(data),'i2_raw_sha256':hashlib.sha256(o.get_raw_data()).hexdigest(),'original_sha256':sha(src),'changed_objects':changed,'protected_languages_and_tree_exact':True,'unrelated_raw_objects_exact':True,'object_count':len(before)})
  print(rel,n,len(data),flush=True)
 for field in source_trees[0]:
  if field!='Assets':assert source_trees[0][field]==source_trees[1][field],('I2copydifference',field)
 # AssetsPPtrs intentionally differ: lifetime external-font references vsboot localIDs.
 # Per-copy original-tree restoration above guarantees these remain byte-appropriate.
 report={'gate_status':'PASS_STATIC_NOT_DEPLOYED','release_ready':False,'pending_ids':pending,'dataset_sha256':sha(W/'raw_strings.json'),'files':reports,'warning':'Only I2 staging, finalfont/outside/catalog/runtimeproof required'}
 (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
