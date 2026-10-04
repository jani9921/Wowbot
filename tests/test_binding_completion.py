import pytest
from tools.complete_selected_bindings import additions


def test_only_confirmed_missing_bindings_are_added():
    state = {"control_bindings": {"MOVEFORWARD": {"primary": "W", "source": "GET_BINDING_KEY"},
                                "JUMP": {"primary": "SPACE", "source": "GUESS"}},
             "actionbar": [{"action": "ACTIONBUTTON1", "binding_primary": "1"}]}
    assert additions('bind W MOVEFORWARD\n', state) == ['bind "1" "ACTIONBUTTON1"']


def test_completion_preserves_existing_key_assignments():
    with pytest.raises(ValueError, match="conflicts"):
        additions('bind W NONE\n', {"control_bindings": {"MOVEFORWARD": {"primary": "W", "source": "GET_BINDING_KEY"}}})
