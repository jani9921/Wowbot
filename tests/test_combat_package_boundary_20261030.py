"""The migrated combat primitives have one implementation and no agent imports."""
import ast
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]/'src'/'wowbot'


def test_old_imports_export_the_identical_canonical_classes_and_functions():
    from wowbot.agent import target_manager, models
    from wowbot.skills import ability_rules, combat_ability_catalog
    from wowbot.runtime import entity_identity
    import wowbot.combat_contracts as old_combat
    from wowbot.combat.target import system
    from wowbot.combat.ability import contracts, evaluator, catalog
    from wowbot.combat import contracts as combat, arbitrator
    import wowbot.entity_identity as identity
    from wowbot.value_helpers import number
    for name in ('TargetLifecycle','TargetScoringPolicy','TargetCandidate','TargetManager'):
        assert getattr(target_manager,name) is getattr(system,name)
    for name in ('AbilityTag','AbilityDefinition','AbilityRuntimeState','AbilityRule','AbilityCandidate'):
        assert getattr(ability_rules,name) is getattr(contracts,name)
    assert ability_rules.AbilityRuleEngine is evaluator.AbilityRuleEngine
    assert combat_ability_catalog.enrich_ability is catalog.enrich_ability
    assert combat_ability_catalog.ABILITY_DEFAULTS is catalog.ABILITY_DEFAULTS
    assert old_combat.CharacterProfile is combat.CharacterProfile
    assert old_combat.CastReference is combat.CastReference
    assert old_combat.CombatArbitrator is arbitrator.CombatArbitrator
    assert models.number is number
    for name in ('WorldEntityId','world_entity_id','check_entity_identity','IdentityCheck'):
        assert getattr(entity_identity,name) is getattr(identity,name)


def test_compatibility_modules_do_not_retain_independent_implementations():
    for name in ('agent/target_manager.py','skills/ability_rules.py','skills/combat_ability_catalog.py',
                 'runtime/entity_identity.py','combat_contracts.py'):
        nodes=ast.parse((ROOT/name).read_text(encoding='utf-8')).body
        assert not any(isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) for n in nodes),name


def test_core_combat_modules_cannot_import_agent_skills_navigation_vision_or_input():
    import importlib.util
    forbidden=('wowbot.agent','wowbot.skills','wowbot.navigation','wowbot.vision','wowbot.input',
               'adapters.windows_input')
    for path in (ROOT/'combat').rglob('*.py'):
        relative=path.relative_to(ROOT.parent).with_suffix('').parts
        module='.'.join(relative)
        package=module if path.name=='__init__.py' else module.rpartition('.')[0]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.Import):
                imports=[n.name for n in node.names]
            elif isinstance(node,ast.ImportFrom):
                name=node.module or ''
                imports=[importlib.util.resolve_name('.'*node.level+name,package) if node.level else name]
            else:
                continue
            assert not any(name==f or name.startswith(f+'.') for name in imports for f in forbidden),(path,imports)


def test_real_combat_import_and_evaluation_work_when_agent_and_skills_are_blocked():
    script = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==n or fullname.startswith(n+'.') for n in ('wowbot.agent','wowbot.skills','wowbot.navigation','wowbot.vision','adapters.windows_input')):
   raise AssertionError('forbidden core dependency: '+fullname)
sys.meta_path.insert(0,Block())
from wowbot.combat.ability.evaluator import AbilityRuleEngine
from wowbot.combat.target.system import TargetManager
from wowbot.combat.target.facing import bearing_error
from wowbot.combat.arbitrator import CombatArbitrator
from wowbot.entity_identity import check_entity_identity
state={'character_guid':'Player-1-1','session_id':'s','health':100,'max_health':100,'power':100,
 'target':{'guid':'Creature-1','attackable':True},
 'actionbar':[{'id':2,'action':'ACTIONBUTTON2','kind':'spell','is_harmful':True,'is_usable':True,
 'cooldown_remaining':0.,'in_range':True}]}
assert AbilityRuleEngine().choose(state,now=10.)['id']==2
assert TargetManager().snapshot()['lifecycle']=='NONE'
assert bearing_error({'x':0,'y':0},{'x':10,'y':0},0.)==0.
assert check_entity_identity({'guid':'Creature-1'},{'guid':'Creature-1'})
assert not any(n.startswith(('wowbot.agent','wowbot.skills','wowbot.vision')) for n in sys.modules)
'''
    result=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,
                          env={**os.environ,'PYTHONPATH':str(ROOT.parent)},timeout=15.)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('point,facing,expected',[
    ({'x':10,'y':0},0.,0.),({'x':0,'y':10},0.,math.pi/2),
    ({'x':0,'y':-10},0.,-math.pi/2),({'x':-10,'y':0},0.,-math.pi),
    ({'x':10,'y':0},math.pi/2,-math.pi/2),({'x':10,'y':0},2*math.pi,0.),
])
def test_facing_geometry_preserves_sign_wrap_and_original_turn_direction(point,facing,expected):
    from wowbot.combat.target.facing import bearing_error
    assert bearing_error({'x':0,'y':0},point,facing)==pytest.approx(expected)


@pytest.mark.parametrize('point,facing',[
    ({'x':.1,'y':.1},0.),({'x':math.inf,'y':1},0.),({'x':1,'y':math.nan},0.),
    ({'x':10,'y':1},True),({'x':10},0.),(None,0.),
])
def test_unknown_or_nonfinite_facing_input_does_not_create_a_turn(point,facing):
    from wowbot.combat.target.facing import bearing_error
    assert bearing_error({'x':0,'y':0},point,facing) is None


def test_selected_guid_check_stays_at_skill_boundary_and_does_not_move_into_geometry():
    from wowbot.skills.combat import CombatSkill
    state={'target':{'guid':'Creature-other','world_position':{'x':10,'y':10}},
           'player_world_position':{'x':0,'y':0},'orientation':0.}
    assert CombatSkill._target_bearing_error(state,'Creature-required') is None
    assert CombatSkill._target_bearing_error(state,'Creature-other')==pytest.approx(math.pi/4)


def test_production_consumers_construct_the_canonical_evaluator():
    from wowbot.combat.ability.evaluator import AbilityRuleEngine
    from wowbot.skills.combat import CombatSkill
    from wowbot.agent.combat_controller import CombatController
    from wowbot.combat.target.system import TargetManager
    assert type(CombatSkill().ability_rules) is AbilityRuleEngine
    controller=CombatController()
    assert type(controller.ability_rules) is AbilityRuleEngine
    assert type(controller.target_manager) is TargetManager
