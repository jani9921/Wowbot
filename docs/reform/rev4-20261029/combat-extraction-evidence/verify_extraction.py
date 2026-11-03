import ast
import hashlib
import json
from pathlib import Path
import zipfile

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work=Path(__file__).parent


def declarations(text):
    return {n.name:n for n in ast.parse(text).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}


class Imports(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        if node.module=='wowbot.combat.arbitrator':node.module='wowbot.combat_contracts'
        return node


rows=[]
with zipfile.ZipFile(work/'baseline.zip') as archive:
    for before,after,names in (
        ('agent/target_manager.py','combat/target/system.py',('TargetLifecycle','TargetScoringPolicy','TargetCandidate','TargetManager')),
        ('skills/ability_rules.py','combat/ability/contracts.py',('AbilityTag','AbilityDefinition','AbilityRuntimeState','AbilityRule','AbilityCandidate')),
        ('skills/ability_rules.py','combat/ability/evaluator.py',('AbilityRuleEngine','_milliseconds','_belief','_condition_matches','_condition_name')),
        ('skills/combat_ability_catalog.py','combat/ability/catalog.py',('enrich_ability',)),
        ('combat_contracts.py','combat/contracts.py',('CharacterProfile','CastReference','CombatCandidate')),
        ('combat_contracts.py','combat/arbitrator.py',('CombatArbitrator',)),
        ('runtime/entity_identity.py','entity_identity.py',('WorldEntityId','world_entity_id','template_id','identity_fields','guid_template','IdentityCheck','check_entity_identity')),
        ('agent/models.py','value_helpers.py',('number',)),
    ):
        old=declarations(archive.read('src/wowbot/'+before).decode('utf-8-sig'))
        new=declarations((root/'src/wowbot'/after).read_text(encoding='utf-8-sig'))
        for name in names:
            # Only the lazy import path to the same arbitrator changes inside an evaluator body.
            old_dump=ast.dump(Imports().visit(old[name]),include_attributes=False)
            new_dump=ast.dump(Imports().visit(new[name]),include_attributes=False)
            assert old_dump==new_dump,(before,after,name)
            rows.append({'name':name,'before':before,'after':after,'ast_body_unchanged':True})
doc=root/'docs/reform/rev4-20261029/input/SRC_MIGRACIOS_TERV_20261029_HU.md'
assert hashlib.sha256(doc.read_bytes()).hexdigest()=='d4c7136232748c71e03400e0ed97fadec40f55189b1d2d9132831dde5310c1e4'
result={'declarations':rows,'unchanged_ast_declarations':len(rows),
        'supplement_bytes_preserved':True,'new_rotation_or_input_policy':False}
(work/'extraction-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='declarations'}))
