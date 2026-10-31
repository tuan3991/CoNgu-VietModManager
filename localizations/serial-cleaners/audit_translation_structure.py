"""Independent structural checks and editorial warning inventory, offline only."""
from pathlib import Path
import json,re,collections,unicodedata,hashlib,datetime
W=Path(__file__).resolve().parent
rows=json.loads((W/'raw_strings.json').read_text(encoding='utf-8'))
errors=[]; warnings=[]; checked=0
# RichText recognized only as real name-led tags, not text emoticons such as <3.
TAG=re.compile(r'</?[A-Za-z][^>]*>')
PH=re.compile(r'\{[^{}]+\}|\[i2p_[^\]]+\]|%\d*\$?[sdif]')
for r in rows:
    if not r['target']:continue
    checked+=1;s=r['source'];t=r['target'];rid=r['id'];notes=r.get('notes','')
    for label,pat in [('placeholder',PH),('tag',TAG)]:
        if collections.Counter(pat.findall(s))!=collections.Counter(pat.findall(t)):errors.append({'id':rid,'kind':label,'source':pat.findall(s),'target':pat.findall(t)})
    if TAG.findall(s)!=TAG.findall(t):errors.append({'id':rid,'kind':'tag_sequence'})
    if re.findall(r'\r\n|\r|\n',s)!=re.findall(r'\r\n|\r|\n',t):errors.append({'id':rid,'kind':'newline_sequence'})
    if t!=unicodedata.normalize('NFC',t):errors.append({'id':rid,'kind':'NFC'})
    # Input tokens inside [] must remain even without curly outer wrapper.
    for x in re.findall(r'\[[^\]\r\n]*\]',s):
        if s.count(x)!=t.count(x):errors.append({'id':rid,'kind':'square_token','token':x})
    # Numeric warnings permit written-out numbers, leetspeak or names but demand review.
    def digits(v):return re.findall(r'\d+(?:[.:]\d+)*',TAG.sub('',PH.sub('',v)))
    if collections.Counter(digits(s))!=collections.Counter(digits(t)):
        warnings.append({'id':rid,'kind':'numeric_editorial_review','source':s,'target':t,'source_numbers':digits(s),'target_numbers':digits(t),'notes':notes})
    if s==t and not notes: warnings.append({'id':rid,'kind':'unchanged_without_reason','source':s})
    def tagbal(v):
        stack=[];issues=[]
        for match in TAG.findall(v):
            name=re.match(r'</?([A-Za-z][\w-]*)',match).group(1)
            if name in ['br','sprite','pause','glitchmitch','glitchhaha'] or match.endswith('/>'):continue
            if match.startswith('</'):
                if not stack or stack[-1]!=name:issues.append(match)
                else:stack.pop()
            else:stack.append(name)
        return issues+stack
    if tagbal(s):warnings.append({'id':rid,'kind':'preexisting_source_tag_imbalance','issues':tagbal(s),'source_preserved':TAG.findall(s)==TAG.findall(t)})
result={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dataset_sha256':hashlib.sha256((W/'raw_strings.json').read_bytes()).hexdigest(),'checked_translated':checked,'gate_status':'PASS' if not errors else 'FAIL','structural_errors':errors,'editorial_warnings':warnings,'scope':'Translation checkpoint only, not binary/font/runtime acceptance; warnings not build blockers'}
(W/'translation_structure_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checked':checked,'errors':len(errors),'warning_counts':dict(collections.Counter(x['kind'] for x in warnings))}));assert not errors,errors
