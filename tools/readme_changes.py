"""Rebuild the README "Változások" block from BUGFIXES.md.

    python tools/readme_changes.py

User 2026-10-05: the bug fixes and implementations should be visible in the
README tab on GitHub.  BUGFIXES.md stays the single source; every
``## <day>`` section becomes a collapsible ``<details>`` block between the
README's CHANGES markers (the newest day open).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
START, END = "<!-- CHANGES:START -->", "<!-- CHANGES:END -->"


def day_sections(text: str) -> list[tuple[str, str]]:
    """[(day heading, body)] for every ``## `` section of BUGFIXES.md."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    sections = []
    for title, body in zip(parts[1::2], parts[2::2]):
        body = re.sub(r"\n-{3,}\s*$", "", body.strip()).strip()
        sections.append((title.strip(), body))
    return sections


def render(sections: list[tuple[str, str]]) -> str:
    blocks = []
    for index, (title, body) in enumerate(sections):
        fixes = len(re.findall(r"^- ", body.split("### Bug fixes", 1)[-1], flags=re.MULTILINE))
        features = len(re.findall(r"^- ", body.split("### Bug fixes", 1)[0], flags=re.MULTILINE))
        summary = f"<b>{title}</b> — {features} új funkció, {fixes} javítás"
        # Headings one level deeper so they nest under "Változások".
        body = re.sub(r"^(#{3,5}) ", lambda m: "#" + m[1] + " ", body, flags=re.MULTILINE)
        blocks.append(f"<details{' open' if index == 0 else ''}>\n<summary>{summary}</summary>\n\n"
                      f"{body}\n\n</details>")
    return "\n\n".join(blocks)


def update(readme: Path, bugfixes: Path) -> bool:
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"{readme.name}: missing {START} / {END}")
    block = render(day_sections(bugfixes.read_text(encoding="utf-8")))
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n{block}\n{END}{tail}"
    if new != text:
        readme.write_text(new, encoding="utf-8")
    return new != text


def main() -> int:
    changed = update(ROOT / "README.md", ROOT / "BUGFIXES.md")
    print("README.md frissítve" if changed else "README.md már naprakész")
    return 0


if __name__ == "__main__":
    sys.exit(main())
