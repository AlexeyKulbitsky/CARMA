"""Execution and exploration contracts do not carry renderer-specific state."""

from carma.contracts import load_schema, validation_errors
from carma.execution.api import ExecutionFunction
from carma.api.schemas import Exploration


def test_committed_execution_schemas_match_models():
    assert load_schema("execution") == ExecutionFunction.model_json_schema()
    assert load_schema("exploration") == Exploration.model_json_schema()


def test_exploration_rejects_opaque_gui_state_and_invalid_camera():
    data = {"schema_version": "exploration/0.2", "entry": None, "mode": "execution", "views": {}}
    assert not validation_errors("exploration", data)
    assert validation_errors("exploration", {**data, "reactFlow": {}})
    assert validation_errors("exploration", {**data, "views": {"main": {"positions": {}, "expanded": {},
                                                               "camera": {"x": 0, "y": 0, "zoom": 0}}}})
