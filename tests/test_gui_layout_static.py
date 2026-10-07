"""Issue #97: the binding-export bar and the detail text shared grid row 11
of the same parent, so the expanding Text covered the export controls.
tkinter is not available in every test environment: inspect gui.py's AST."""
import ast
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "src" / "wowbot" / "agent" / "gui.py"


def _grid_rows():
    rows = {}
    for node in ast.walk(ast.parse(GUI.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "grid"):
            target = ast.unparse(node.func.value)
            for keyword in node.keywords:
                if keyword.arg == "row" and isinstance(keyword.value, ast.Constant):
                    rows.setdefault(target, []).append(keyword.value.value)
    return rows


def _weighted_rows():
    weighted = []
    for node in ast.walk(ast.parse(GUI.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rowconfigure" and node.args
                and isinstance(node.args[0], ast.Constant)
                and any(k.arg == "weight" for k in node.keywords)):
            weighted.append(node.args[0].value)
    return weighted


def test_export_bar_and_detail_text_have_distinct_rows():
    rows = _grid_rows()
    export_row, = rows["export_bar"]
    detail_row, = rows["self.detail"]
    assert export_row != detail_row
    assert detail_row in _weighted_rows() and export_row not in _weighted_rows()
