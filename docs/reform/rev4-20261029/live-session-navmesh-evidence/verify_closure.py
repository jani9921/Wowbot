import ast, hashlib, json, zipfile
from pathlib import Path

root = Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work = Path(__file__).parent
result = {}
for directory in ('src', 'tests'):
    paths = sorted((root/directory).rglob('*.py'))
    for path in paths:
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    result[directory+'_python_files'] = len(paths)
result['test_modules'] = len(list((root/'tests').rglob('test_*.py')))
ast.parse((root/'tools/build_power_reference.py').read_text(encoding='utf-8-sig'))
with zipfile.ZipFile(work/'baseline.zip') as z:
    old = z.read('docs/CURRENT_SOURCE_COVERAGE.md').decode('utf-8-sig')
current = (root/'docs/CURRENT_SOURCE_COVERAGE.md').read_text(encoding='utf-8-sig')
rows = lambda value:[line for line in value.splitlines() if line.startswith(('| V4-', '| DESIGN-'))]
assert rows(current) == rows(old) and len(rows(current)) == 203
result['numbered_coverage_rows'] = 203
names = ('AIPlayerControllerExport.lua','AIPlayerControllerExport.toc','Bindings.lua','Transport.lua')
for name in names:
    assert (root/'addon/AIPlayerControllerExport'/name).read_bytes() == (root/'addon/AIPlayerControllerExport-12.1.0'/name).read_bytes()
result['addon_packages_identical'] = True
ymir = root/'runtime/ymir/ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe'
result['ymir_sha256'] = hashlib.sha256(ymir.read_bytes()).hexdigest()
assert result['ymir_sha256'] == '77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9'
(work/'source-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
