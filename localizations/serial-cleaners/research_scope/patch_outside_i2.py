"""Finite fail-closed outside-I2 staging patcher; never writes input/game files.

Python 3.11 + UnityPy 1.25.4. Explicit composed inputs; new output directory only.
APPROVED is the explicit selection state (ready_to_patch is inventory audit metadata).
No inferred translations, name/ID changes, lookup substitutions, network or game launch.
"""
from __future__ import annotations
import argparse
import collections
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
INVENTORY_SHA256 = '72433059f08fff63b6560c3333991ed07560f02597c869c586d8caa0e884b167'
MANIFEST_FIELDS = ('id', 'file_source', 'resource_address', 'source', 'source_sha256', 'source_file_sha256', 'group')
ALLOWED_FIELDS = {'credits_role': '_displayName', 'credits_header': '_header',
                  'hacking_prefix': '_prefixText', 'full_hackingText': '_hackingText',
                  'patch_popup': 'm_text', 'renderer_display_review': None}
TAG = re.compile(r'<[^<>]+>')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def address(row):
    a = row['resource_address']
    require(type(a['path_id']) is int, 'path_id must be a JSON integer')
    require(isinstance(a['cab'], str) and isinstance(a['field_path'], str), 'Invalid address')
    return row['file_source'], a['cab'], a['path_id'], a['field_path']


def load_selection(translations):
    inventory_path = HERE / 'outside_i2_strings.json'
    require(file_sha(inventory_path) == INVENTORY_SHA256, 'Immutable inventory hash mismatch')
    inventory = read_json(inventory_path)['strings']
    require(len(inventory) == 412, 'Inventory count mismatch')
    lookup = {address(row): row for row in inventory}
    require(len(lookup) == 412, 'Duplicate inventory address')
    manifest = read_json(PROJECT / 'original_manifest.json')
    manifest_hashes = {row['path']: row['sha256'] for row in manifest['files']}
    for row in inventory:
        require(sha(row['source'].encode('utf8')) == row['source_sha256'], 'Inventory source hash mismatch')
        require(manifest_hashes.get(row['file_source']) == row['source_file_sha256'], 'Original manifest hash mismatch')
    payload = read_json(translations)
    if isinstance(payload, dict):
        if 'inventory_sha256' in payload:
            require(payload['inventory_sha256'] == INVENTORY_SHA256, 'Translation inventory hash mismatch')
        rows = payload['strings']
    else:
        rows = payload
    require(isinstance(rows, list), 'Translations must be a list or {strings: [...]}')
    seen, selected, skipped = set(), [], collections.Counter()
    for row in rows:
        key = address(row)
        require(key not in seen, f'Duplicate translation address: {key}')
        seen.add(key)
        require(key in lookup, f'Address not in locked inventory: {key}')
        original = lookup[key]
        for field in MANIFEST_FIELDS:
            require(field in row and row[field] == original[field], f'Immutable {field} mismatch: {key}')
        require('target' in row and 'translation_state' in row, f'Missing target/state: {key}')
        state = row['translation_state']
        require(state in {'APPROVED', 'NOT_TRANSLATED', 'NEEDS_REVIEW', 'PROTECTED'}, f'Unknown state: {state}')
        if state != 'APPROVED':
            skipped[state] += 1
            continue
        require(original['role'] != 'PROTECT', f'Inventory PROTECT cannot be approved: {key}')
        require(row.get('role') == 'TRANSLATE', f'APPROVED requires explicit TRANSLATE role: {key}')
        if original['role'] == 'REVIEW':
            require(bool(row.get('consumer_review_reason')), f'Promoted REVIEW requires consumer_review_reason: {key}')
        allowed_field = ALLOWED_FIELDS[original['group']]
        if original['group'] == 'renderer_display_review':
            go_path = original['context']['go_path']
            require(not go_path.startswith(('XboxAccountPicker/', 'ConfirmationPromptSystem/')), f'Platform/account identity or overwritten prompt remains REVIEW: {key}')
            require(original['context']['class'] in ('Text', 'TextMeshProUGUI'), f'Unrecognized renderer class: {key}')
            allowed_field = 'm_text' if original['context']['class'] == 'TextMeshProUGUI' else 'm_Text'
        require(key[3] == allowed_field, f'Unsafe field: {key}')
        target = row['target']
        require(isinstance(target, str) and bool(target.strip()), f'Empty APPROVED target: {key}')
        if target == original['source']:
            skipped['APPROVED_UNCHANGED'] += 1
            continue
        require('\0' not in target, f'NUL in target: {key}')
        require(unicodedata.normalize('NFC', target) == target, f'Non-NFC target: {key}')
        require(TAG.findall(target) == TAG.findall(original['source']), f'Rich-text tag sequence changed: {key}')
        require(target.count('\n') == original['source'].count('\n') and target.count('\r') == original['source'].count('\r'), f'Newline count changed: {key}')
        if original['group'] == 'full_hackingText':
            # Only single-line // comments may differ; every code byte before // stays exact.
            before, after = original['source'].splitlines(keepends=True), target.splitlines(keepends=True)
            require(len(before) == len(after), f'Hacking line count changed: {key}')
            for left, right in zip(before, after):
                require(('//' in left) == ('//' in right), f'Hacking comment marker changed: {key}')
                require(left.split('//', 1)[0] == right.split('//', 1)[0] if '//' in left else left == right, f'Hacking non-comment bytes changed: {key}')
        selected.append(row)
    require(bool(selected), 'No APPROVED non-noop records selected; refusing empty patch')
    return inventory, selected, dict(skipped)


def exact_equal(left, right):
    """Type-sensitive tree equality; preserve dict order, list shape and float NaNs."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return list(left) == list(right) and all(exact_equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(exact_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return left == right


def object_map(env):
    result = {}
    for obj in env.objects:
        key = obj.assets_file.name, obj.path_id
        require(key not in result, f'Duplicate Unity object identity: {key}')
        result[key] = obj
    return result


def environment_metadata(env):
    """Object set, schema/external identities and non-serialized bundle payloads."""
    from UnityPy.files import SerializedFile
    result = {}
    def walk(container, prefix=''):
        for name, item in container.files.items():
            key = prefix + '/' + name
            if isinstance(item, SerializedFile):
                types = []
                for st in item.types:
                    types.append((st.class_id, st.is_stripped_type, st.script_type_index,
                                  st.script_id, st.old_type_hash, st.type_dependencies,
                                  st.node.dump_structure() if st.node else None))
                result[key] = ('serialized', item.header.version, item.header.endian,
                               str(item.unity_version), item.target_platform, item._enable_type_tree,
                               tuple((e.path, e.guid, e.type, e.temp_empty) for e in item.externals), types)
            elif hasattr(item, 'files'):
                walk(item, key)
            else:
                result[key] = ('raw', sha(item.bytes))
    walk(env.file)
    return result


def plan_inputs(selected, input_map, allow_originals, original_root):
    require(isinstance(input_map, dict), 'Input map must be basename -> composed path object')
    for name, path in input_map.items():
        require(Path(name).name == name and isinstance(path, str), f'Invalid map entry: {name}')
    groups = collections.defaultdict(list)
    for row in selected:
        groups[row['file_source']].append(row)
    jobs = []
    for source, rows in sorted(groups.items()):
        name = Path(source).name
        if name in input_map:
            inp = Path(input_map[name]).resolve(strict=True)
            # Read explicit inputs only; never probe installed files for a newer copy.
            require(inp.is_relative_to(PROJECT), f'Composed input must be staged inside project: {inp}')
            fallback = False
        else:
            require(allow_originals and original_root is not None, f'Missing explicit composed input for {name}; no silent original fallback')
            inp = (original_root / source).resolve(strict=True)
            require(inp.is_relative_to(original_root.resolve()), 'Original path escapes root')
            require(file_sha(inp) == rows[0]['source_file_sha256'], f'Original file hash mismatch: {inp}')
            fallback = True
        require(inp.is_file(), f'Not a file: {inp}')
        jobs.append((source, inp, rows, fallback))
    return jobs


def patch_bundle(inp, rows):
    import UnityPy
    raw = inp.read_bytes()
    env = UnityPy.load(raw)
    objects = object_map(env)
    metadata = environment_metadata(env)
    # Snapshot ALL decompressed object bytes before mutation, not just candidate classes.
    originals = {key: (obj.class_id, sha(obj.get_raw_data())) for key, obj in objects.items()}
    expected, records = {}, []
    grouped = collections.defaultdict(list)
    for row in rows:
        a = row['resource_address']
        grouped[(a['cab'], a['path_id'])].append(row)
    for key, edits in grouped.items():
        require(key in objects, f'Unity object missing: {key}')
        obj = objects[key]
        require(obj.type.name == 'MonoBehaviour', f'Unexpected object type: {key}')
        tree = obj.read_typetree(check_read=True)
        expected[key] = copy.deepcopy(tree)
        for row in edits:
            field = row['resource_address']['field_path']
            require(field in tree and type(tree[field]) is str, f'Exact top-level string field missing: {key} {field}')
            require(tree[field] == row['source'] and sha(tree[field].encode('utf8')) == row['source_sha256'], f'Composed field differs from locked source: {key} {field}')
            expected[key][field] = row['target']
            records.append({'id': row['id'], 'cab': key[0], 'path_id': key[1], 'field': field,
                            'source_sha256': row['source_sha256'], 'target_sha256': sha(row['target'].encode('utf8'))})
        obj.save_typetree(expected[key])
    output = env.file.save(packer='lz4')
    # Independent reload from serialized output bytes; all checks precede writing a bundle.
    reloaded = UnityPy.load(output)
    after = object_map(reloaded)
    require(set(after) == set(objects), 'Unity object address set changed')
    require(exact_equal(metadata, environment_metadata(reloaded)), 'Bundle/schema/external metadata changed')
    unchanged = changed = 0
    for key, obj in after.items():
        require(obj.class_id == originals[key][0], f'Class ID changed: {key}')
        if key in expected:
            require(exact_equal(obj.read_typetree(check_read=True), expected[key]), f'Exact expected TypeTree mismatch: {key}')
            changed += 1
        else:
            require(sha(obj.get_raw_data()) == originals[key][1], f'Unselected raw object changed: {key}')
            unchanged += 1
    require(file_sha(inp) == sha(raw), f'Input changed during patch: {inp}')
    return output, {'input_sha256': sha(raw), 'output_sha256': sha(output),
                    'modified_fields': records, 'modified_objects': changed,
                    'other_raw_objects_unchanged': unchanged, 'object_count': len(objects),
                    'exact_expected_typetrees': True, 'schema_externals_and_other_payloads_unchanged': True,
                    'input_unchanged': True}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--translations', type=Path, required=True)
    ap.add_argument('--input-map', type=Path, required=True, help='JSON basename -> composed file path (relative paths use cwd)')
    ap.add_argument('--out', type=Path, required=True, help='NEW directory beneath research_scope; never an existing directory')
    ap.add_argument('--allow-originals-readonly', action='store_true', help='Explicitly permit unmapped untouched original inputs (never use for previously composed files)')
    ap.add_argument('--original-root', type=Path)
    ap.add_argument('--validate-only', action='store_true', help='Validate translations/map and print plan; do not load/write Unity files or create output dir')
    a = ap.parse_args(argv)
    require(not a.allow_originals_readonly or a.original_root is not None, '--allow-originals-readonly requires --original-root')
    require(a.original_root is None or a.allow_originals_readonly, '--original-root requires explicit readonly opt-in')
    out = a.out.resolve()
    require(out != HERE and out.is_relative_to(HERE), '--out must be a new child directory of research_scope')
    require(not out.exists(), f'Refusing existing output directory: {out}')
    inventory, selected, skipped = load_selection(a.translations)
    input_map = read_json(a.input_map)
    jobs = plan_inputs(selected, input_map, a.allow_originals_readonly, a.original_root)
    # Known prior composition must NEVER silently fall back to originals.
    composed_prefixes = ('ui_assets_', 'dlcdino_creditssystems_assets_')
    for _, inp, _, fallback in jobs:
        require(not fallback or not inp.name.startswith(composed_prefixes), f'Previously composed bundle requires --input-map: {inp.name}')
    locks = {p.resolve(): file_sha(p) for p in (a.translations, a.input_map, HERE / 'outside_i2_strings.json', PROJECT / 'original_manifest.json')}
    report = {'status': 'VALIDATED_PLAN_ONLY' if a.validate_only else 'IN_PROGRESS',
              'inventory_sha256': INVENTORY_SHA256, 'translation_sha256': file_sha(a.translations),
              'selection': 'role == TRANSLATE AND translation_state == APPROVED; ready_to_patch is not an approval gate',
              'original_hash_lock': 'Immutable inventory SHA + every exact source SHA + original manifest source-file SHA; composed inputs locked separately by actual SHA',
              'selected_records': len(selected), 'skipped_by_state': skipped,
              'selected_groups': dict(collections.Counter(r['group'] for r in selected)),
              'planned_files': [{'source': source, 'input': str(inp), 'selected_records': len(rows), 'original_readonly_fallback': fallback} for source, inp, rows, fallback in jobs],
              'results': [], 'limits': ['No game write/launch/network; outputs are staging only', 'Not final translation/font/layout/catalog/runtime release QA', 'Rebuild catalog from final composed bundle bytes', 'Renderer REVIEW requires explicit TRANSLATE promotion and consumer_review_reason; Xbox/account/prompt remain blocked; name/ID fields forbidden', 'Existing composed input must contain exact original field source; replay/conflicting edits fail']}
    if a.validate_only:
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    out.mkdir(parents=False, exist_ok=False)
    report_path = out / 'invariants.json'
    try:
        for source, inp, rows, fallback in jobs:
            print('PATCH_STAGING', inp.name, len(rows), flush=True)
            output, checks = patch_bundle(inp, rows)
            dest = out / Path(source).name
            with dest.open('xb') as stream:
                stream.write(output)
            require(file_sha(dest) == checks['output_sha256'], 'On-disk output hash mismatch')
            checks.update({'source': source, 'input': str(inp), 'output': str(dest),
                           'source_file_sha256': rows[0]['source_file_sha256'], 'original_readonly_fallback': fallback})
            report['results'].append(checks)
        require(all(file_sha(p) == digest for p, digest in locks.items()), 'Inventory/translation/manifest/input-map changed during execution')
        report['status'] = 'PASS_STATIC_OUTSIDE_I2_NOT_DEPLOYED'
        report['locked_control_inputs_unchanged'] = True
    except Exception as exc:
        report['status'] = 'FAIL_NOT_DEPLOYABLE'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(report['status'], len(selected), 'records', len(jobs), 'files', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'FAIL: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
