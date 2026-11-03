"""Move existing pure entity pose helpers once; preserve exact AST bodies."""
import ast,hashlib,json
from pathlib import Path
root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
path=root/'src/wowbot/agent/packet_entity_facts.py'
value=path.read_text(encoding='utf-8-sig');lines=value.splitlines(keepends=True)
tree=ast.parse(value);names={'entity','best_position','travel_position'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert len(nodes)==3
target=root/'src/wowbot/entity_spatial.py';assert not target.exists()
code='"""Canonical pure projection of existing scoped entity facts; no input or planner."""\nfrom .value_helpers import number\n\n\n'
code+='\n\n'.join(''.join(lines[n.lineno-1:n.end_lineno]).rstrip() for n in nodes)+'\n'
target.write_text(code,encoding='utf-8')
for n in sorted(nodes,key=lambda n:n.lineno,reverse=True):
    del lines[n.lineno-1:n.end_lineno]
remaining=''.join(lines).replace('from .models import number',
    'from .models import number\nfrom wowbot.entity_spatial import entity, best_position, travel_position',1)
path.write_text(remaining,encoding='utf-8')
after={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)}
for n in nodes:assert ast.dump(n,include_attributes=False)==after[n.name]
Path(__file__).with_name('spatial-extraction-verification.json').write_text(json.dumps({
    'old_path':'src/wowbot/agent/packet_entity_facts.py','canonical':'src/wowbot/entity_spatial.py',
    'moved_exact_ast':sorted(names),'same_object_reexports':True},indent=2)+'\n')
print('3 actual helpers moved, exact AST bodies preserved')
