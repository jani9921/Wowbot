"""User 2026-10-05: bug fixes + implementations shown in the GitHub README tab."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("readme_changes", ROOT / "tools" / "readme_changes.py")
readme_changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readme_changes)


def test_each_day_becomes_a_collapsible_block_newest_open(tmp_path):
    bugfixes = tmp_path / "BUGFIXES.md"
    bugfixes.write_text("# T\n\n---\n\n## 2026-10-05\n\n### Új funkciók / implementációk\n- a\n\n"
                        "### Bug fixes\n\n#### X\n- b\n- c\n\n---\n\n## 2026-10-04\n\n"
                        "### Új funkciók / implementációk\n- d\n\n### Bug fixes\n- e\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# R\n\n<!-- CHANGES:START -->\nold\n<!-- CHANGES:END -->\n\n## Tail\n", encoding="utf-8")
    assert readme_changes.update(readme, bugfixes)
    text = readme.read_text(encoding="utf-8")
    assert "<details open>\n<summary><b>2026-10-05</b> — 1 új funkció, 2 javítás</summary>" in text
    assert "<details>\n<summary><b>2026-10-04</b> — 1 új funkció, 1 javítás</summary>" in text
    assert "#### Új funkciók" in text and "##### X" in text and "old" not in text
    assert text.endswith("<!-- CHANGES:END -->\n\n## Tail\n")
    assert not readme_changes.update(readme, bugfixes)          # idempotent


def test_project_readme_is_in_sync_with_bugfixes():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme_changes.render(readme_changes.day_sections(
        (ROOT / "BUGFIXES.md").read_text(encoding="utf-8")))
    assert block in text
