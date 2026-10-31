"""Pure validation negative tests; no Unity writes or edits to authored records."""
from pathlib import Path
import copy
import json
from unittest.mock import patch
import patch_outside_i2 as p

HERE=Path(__file__).resolve().parent
payload=p.read_json(HERE/'outside_authored_strings.json')
real_read=p.read_json
fake_path=HERE/'__in_memory_translation_tests_only__.json'
results=[]

def run(name, change, expected_error=True):
    data=copy.deepcopy(payload)
    change(data)
    def read(path):return data if path==fake_path else real_read(path)
    try:
        with patch.object(p,'read_json',side_effect=read):p.load_selection(fake_path)
    except (ValueError,KeyError,TypeError) as exc:
        assert expected_error,(name,str(exc))
        results.append({'test':name,'status':'PASS_REJECTED','error':str(exc)})
    else:
        assert not expected_error,name
        results.append({'test':name,'status':'PASS_ACCEPTED'})

run('approved_and_review/protected_filter',lambda d:None,False)
run('duplicate_full_address',lambda d:d['strings'].append(copy.deepcopy(d['strings'][0])))
run('source_changed',lambda d:d['strings'][0].update(source='tampered'))
run('source_hash_changed',lambda d:d['strings'][0].update(source_sha256='0'*64))
run('original_file_hash_changed',lambda d:d['strings'][0].update(source_file_sha256='0'*64))
run('field_name_id_forbidden',lambda d:d['strings'][0]['resource_address'].update(field_path='m_Name'))
run('approved_role_REVIEW_rejected',lambda d:d['strings'][0].update(role='REVIEW'))
run('promoted_REVIEW_requires_reason',lambda d:next(x for x in d['strings'] if x['group']=='full_hackingText').pop('consumer_review_reason',None))
run('empty_approved_target',lambda d:d['strings'][0].update(target=''))
run('nonNFC_target',lambda d:d['strings'][0].update(target='a\u0301'))
run('NUL_target',lambda d:d['strings'][0].update(target='bad\0target'))
run('newline_changed',lambda d:d['strings'][0].update(target='bad\nline'))
run('richtext_tag_changed',lambda d:d['strings'][0].update(target='<b>bad</b>'))
run('review_renderer_cannot_selfapprove',lambda d:next(x for x in d['strings'] if x['group']=='renderer_display_review').update(role='REVIEW',translation_state='APPROVED',target='khong'))
run('review_renderer_explicit_promotion',lambda d:next(x for x in d['strings'] if x['group']=='renderer_display_review').update(role='TRANSLATE',translation_state='APPROVED',target='Hop cau chi',consumer_review_reason='Unit-test explicit staging display review; font gate separate'),False)
run('Xbox_identity_stays_blocked',lambda d:next(x for x in d['strings'] if x['source']=='GAMERTAG').update(role='TRANSLATE',translation_state='APPROVED',target='Sai',consumer_review_reason='Must still reject identity'))
run('hacking_code_bytes_changed',lambda d:next(x for x in d['strings'] if x['group']=='full_hackingText').update(target=next(x for x in d['strings'] if x['group']=='full_hackingText')['target'].replace(' ', 'X',1)))
_,selected,_=p.load_selection(HERE/'outside_authored_strings.json')
try:p.plan_inputs(selected,{},False,None)
except ValueError as exc:results.append({'test':'missing_explicit_composed_input','status':'PASS_REJECTED','error':str(exc)})
else:raise AssertionError('missing map accepted')
assert p.exact_equal({'a':[1,2.0]}, {'a':[1,2.0]})
assert not p.exact_equal({'a':[1,2.0]}, {'a':[1,2]})
assert not p.exact_equal({'a':1,'b':2},{'b':2,'a':1})
results.append({'test':'type_sensitive_exact_tree_comparison','status':'PASS'})
report={'status':'PASS','tests':len(results),'results':results,'limitations':'Validation unit tests only; actual Unity roundtrip proof in outside_staging_proof/invariants.json'}
(HERE/'outside_i2_patcher_tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print('PASS',len(results),'tests')
