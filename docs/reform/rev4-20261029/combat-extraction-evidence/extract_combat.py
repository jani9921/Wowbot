"""One-time audited extraction; no client process or user-state operations."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
work = Path(__file__).parent
base = json.loads((work/'baseline.json').read_text(encoding='utf-8'))
hashes = {r['path']:r['sha256'] for r in base['files']}
sha = lambda v:hashlib.sha256(v).hexdigest()
pending = {}


def source(name):
    data = (root/name).read_bytes()
    assert sha(data) == hashes[name], 'preserve intervening changes: '+name
    return data.decode('utf-8-sig').replace('\r\n','\n')


def changed(name, text):
    ast.parse(text,filename=name)
    pending[name] = text.encode('utf-8')


def added(name, text):
    assert not (root/name).exists(), 'new path already exists: '+name
    changed(name,text)


def reexports(name, target, names):
    changed(name,'"""Compatibility imports; canonical implementation: '+target+'."""\n'
        +'from '+target+' import ('+', '.join(names)+')\n'
        +'__all__ = '+repr(tuple(n for n in names if not n.startswith('_')))+'\n')


for name in ('combat','combat/target','combat/ability'):
    added('src/wowbot/'+name+'/__init__.py','"""Deterministic shared combat capability; no input or agent ownership."""\n')

models = source('src/wowbot/agent/models.py')
number = next(n for n in ast.parse(models).body if isinstance(n,ast.FunctionDef) and n.name=='number')
lines = models.splitlines(True)
number_body = ''.join(lines[number.lineno-1:number.end_lineno])
added('src/wowbot/value_helpers.py','"""Shared finite-number normalization, independent of agent composition."""\n'
      +'from typing import Any\nimport math\n\n\n'+number_body+'\n')
changed('src/wowbot/agent/models.py',''.join(lines[:number.lineno-1])
        +'from wowbot.value_helpers import number  # compatibility export of the shared function\n'
        +''.join(lines[number.end_lineno:]))

identity = source('src/wowbot/runtime/entity_identity.py')
added('src/wowbot/entity_identity.py',identity)
identity_names = ('WorldEntityId','world_entity_id','template_id','identity_fields',
                  'guid_template','IdentityCheck','check_entity_identity','_VISUAL_REFERENCE','_ENTRY_GUID')
reexports('src/wowbot/runtime/entity_identity.py','wowbot.entity_identity',identity_names)

target = source('src/wowbot/agent/target_manager.py')
assert target.count('from wowbot.runtime import WorldEntityId, world_entity_id')==1
added('src/wowbot/combat/target/system.py',target.replace(
      'from wowbot.runtime import WorldEntityId, world_entity_id',
      'from wowbot.entity_identity import WorldEntityId, world_entity_id'))
reexports('src/wowbot/agent/target_manager.py','wowbot.combat.target.system',
          ('TargetLifecycle','TargetScoringPolicy','TargetCandidate','TargetManager'))

ability = source('src/wowbot/skills/ability_rules.py')
lines = ability.splitlines(True)
nodes = {n.name:n for n in ast.parse(ability).body if isinstance(n,ast.ClassDef)}
start, engine = nodes['AbilityTag'].lineno-1, nodes['AbilityRuleEngine'].lineno-1
added('src/wowbot/combat/ability/contracts.py',
      '"""Ability data contracts; no sensor, planner or executor dependencies."""\n'
      +'from __future__ import annotations\nfrom dataclasses import dataclass\nfrom enum import StrEnum\n\n\n'
      +''.join(lines[start:engine]))
evaluation = ('"""Canonical deterministic evaluation over the existing ability rules."""\n'
      +'from __future__ import annotations\nfrom typing import Iterable, Mapping\n'
      +'from wowbot.value_helpers import number\nfrom .catalog import enrich_ability\n'
      +'from .contracts import AbilityTag, AbilityDefinition, AbilityRuntimeState, AbilityRule, AbilityCandidate\n\n\n'
      +''.join(lines[engine:]))
evaluation = evaluation.replace('from wowbot.combat_contracts import CombatArbitrator',
                                'from wowbot.combat.arbitrator import CombatArbitrator')
added('src/wowbot/combat/ability/evaluator.py',evaluation)
added('src/wowbot/combat/ability/catalog.py',source('src/wowbot/skills/combat_ability_catalog.py'))
reexports('src/wowbot/skills/combat_ability_catalog.py','wowbot.combat.ability.catalog',
          ('ABILITY_DEFAULTS','enrich_ability'))
changed('src/wowbot/skills/ability_rules.py','"""Compatibility exports; one canonical combat ability evaluator."""\n'
      +'from wowbot.combat.ability.contracts import (AbilityTag, AbilityDefinition, AbilityRuntimeState, AbilityRule, AbilityCandidate)\n'
      +'from wowbot.combat.ability.evaluator import (AbilityRuleEngine, _milliseconds, _belief, _condition_matches, _condition_name)\n'
      +'__all__ = ("AbilityTag","AbilityDefinition","AbilityRuntimeState","AbilityRule","AbilityCandidate","AbilityRuleEngine")\n')

combat = source('src/wowbot/combat_contracts.py')
lines = combat.splitlines(True)
arbitrator = next(n for n in ast.parse(combat).body if isinstance(n,ast.ClassDef) and n.name=='CombatArbitrator')
added('src/wowbot/combat/contracts.py',''.join(lines[:arbitrator.lineno-1]))
added('src/wowbot/combat/arbitrator.py','"""One deterministic arbitration policy over eligible combat actions."""\n'
      +'import math\nfrom .contracts import CharacterProfile, CastReference, CombatCandidate\n\n\n'
      +''.join(lines[arbitrator.lineno-1:]))
changed('src/wowbot/combat_contracts.py','"""Compatibility exports of canonical shared combat contracts/policy."""\n'
      +'from wowbot.combat.contracts import CharacterProfile, CastReference, CombatCandidate\n'
      +'from wowbot.combat.arbitrator import CombatArbitrator\n'
      +'__all__ = ("CharacterProfile","CastReference","CombatCandidate","CombatArbitrator")\n')

for name, swaps in {
 'src/wowbot/agent/combat_controller.py':{
  'from .target_manager import TargetManager':'from wowbot.combat.target.system import TargetManager',
  'from wowbot.skills.ability_rules import AbilityCandidate, AbilityRuleEngine':
  'from wowbot.combat.ability.evaluator import AbilityRuleEngine\nfrom wowbot.combat.ability.contracts import AbilityCandidate'},
 'src/wowbot/agent/skills.py':{'from wowbot.skills.ability_rules import AbilityRuleEngine':
                           'from wowbot.combat.ability.evaluator import AbilityRuleEngine'},
 'src/wowbot/skills/__init__.py':{'from .ability_rules import (AbilityCandidate, AbilityDefinition, AbilityRule,\n                            AbilityRuleEngine, AbilityRuntimeState, AbilityTag)':
 'from wowbot.combat.ability.contracts import (AbilityCandidate, AbilityDefinition, AbilityRule,\n                                             AbilityRuntimeState, AbilityTag)\nfrom wowbot.combat.ability.evaluator import AbilityRuleEngine'},
 'src/wowbot/agent/reasoner.py':{'from wowbot.combat_contracts import CharacterProfile':
                               'from wowbot.combat.contracts import CharacterProfile'},
 'src/wowbot/agent/world_state_projection.py':{'from wowbot.combat_contracts import CharacterProfile':
                                             'from wowbot.combat.contracts import CharacterProfile'},
}.items():
    value = source(name)
    for before, after in swaps.items():
        assert value.count(before)==1, (name,before)
        value = value.replace(before,after)
    changed(name,value)

skill = source('src/wowbot/skills/combat.py')
skill = skill.replace('from .ability_rules import AbilityRuleEngine',
                      'from wowbot.combat.ability.evaluator import AbilityRuleEngine')
before = '''        px, py, facing = number(player.get("x")), number(player.get("y")), number(world_state.get("orientation"))
        if None in (px, py, facing) or math.hypot(point["x"]-px, point["y"]-py) < .5:
            return None
        bearing = math.atan2(point["y"]-py, point["x"]-px)
        return (bearing-facing+math.pi) % math.tau - math.pi'''
assert skill.count(before)==1
skill = skill.replace(before,'''        from wowbot.combat.target.facing import bearing_error
        return bearing_error(player, point, world_state.get("orientation"))''')
changed('src/wowbot/skills/combat.py',skill)
added('src/wowbot/combat/target/facing.py','''"""Pure facing geometry; target/source authorization and input stay outside."""
import math
from collections.abc import Mapping
from wowbot.value_helpers import number


def bearing_error(player, target, orientation):
    if not isinstance(player, Mapping) or not isinstance(target, Mapping):
        return None
    px, py, tx, ty, facing = (number(v) for v in (
        player.get('x'), player.get('y'), target.get('x'), target.get('y'), orientation))
    if None in (px, py, tx, ty, facing) or math.hypot(tx-px, ty-py) < .5:
        return None
    return (math.atan2(ty-py, tx-px)-facing+math.pi) % math.tau-math.pi
''')

supplement = Path(r'C:/Users/<user>/Downloads/SRC_MIGRACIOS_TERV_20261029_HU.md')
doc = supplement.read_bytes()
assert sha(doc)=='d4c7136232748c71e03400e0ed97fadec40f55189b1d2d9132831dde5310c1e4'
docname = 'docs/reform/rev4-20261029/input/SRC_MIGRACIOS_TERV_20261029_HU.md'
assert not (root/docname).exists()
pending[docname]=doc
manifest = {'received':'2026-10-30','original_zip_unchanged':True,
 'source':str(supplement),'stored_path':docname,'bytes':len(doc),'sha256':sha(doc),
 'status':'supplementary migration plan; not implementation or live acceptance',
 'numbering':'document M0-M8 maps to existing P0-P9; not a replacement master',
 'capture_input_authority_expanded':False}
pending['docs/reform/rev4-20261029/supplement-manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
assert not (root/'docs/reform/rev4-20261029/supplement-manifest.json').exists()

for name,data in pending.items():
    destination=root/name
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(data)
(work/'extraction-files.json').write_text(json.dumps({'files':[
 {'path':name,'sha256':sha(data),'bytes':len(data)} for name,data in pending.items()]},indent=2),encoding='utf-8')
print(json.dumps({'written_files':len(pending),'new_combat_modules':len([n for n in pending if n.startswith('src/wowbot/combat/')]),'source_sha_verified':True}))
