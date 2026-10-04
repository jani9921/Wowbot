"""Index every current user-supplied implementation/design source."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ("V4", ROOT / "wow_agent_FINAL_M0_M1_master_prompt_v4.txt", 101, 0),
    ("DESIGN", ROOT / "wow_agent_complete_functional_design_spec.txt", 102, 1),
    ("V5", ROOT / "wow_v4_to_v5_m1_m6_implementation_spec_v3_10of10_obstacle_upgrade.txt", 169, None),
)


def requirements():
    for prefix, path, expected_count, first_section in SOURCES:
        content = path.read_text(encoding="utf-8-sig")
        sections = []
        lines = content.splitlines()
        if prefix == "V5":
            # The V5 document uses semantic M1--M6 labels rather than one
            # consecutive numeric sequence. Track every milestone heading and
            # every explicitly named acceptance case, including TEST M1-A..D.
            for index, line in enumerate(lines):
                title = line.strip()
                next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
                next_next = lines[index + 2].strip() if index + 2 < len(lines) else ""
                headed = (bool(re.fullmatch(r"[=-]{10,}", next_line))
                          or bool(re.fullmatch(r"={10,}", next_next)))
                acceptance_case = bool(re.match(r"^M[1-6]-[A-Z](?:\s|:|$)", title))
                m1_case = bool(re.match(r"^TEST M1-[A-Z](?:\s|:|$)", title))
                milestone = bool(re.match(
                    r"^M[1-6](?:(?:\.\d+[A-Z]?)|(?:-[A-Z]))?(?:\s|:|$)", title))
                if (milestone and (headed or acceptance_case)) or m1_case:
                    sections.append((len(sections), title, index + 1))
            if len(sections) != expected_count:
                raise ValueError(f"Invalid V5 source section structure: {path.name}")
        else:
            for index, line in enumerate(lines[:-1]):
                match = re.match(r"^(\d+)\.\s+(.+)$", line.strip())
                if match and re.fullmatch(r"={10,}", lines[index + 1].strip()):
                    sections.append((int(match.group(1)), match.group(2).strip(), index + 1))
            if (len(sections) != expected_count
                    or [number for number, _, _ in sections]
                    != list(range(first_section, first_section + expected_count))):
                raise ValueError(f"Invalid current source section structure: {path.name}")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for number, title, line in sections:
            yield {"id": f"{prefix}-{number:03}", "title": title,
                   "line": line, "file": path.name, "source_sha256": source_hash}


def main():
    entries = list(requirements())
    lines = ["# Current-source coverage ledger", "",
             "This ledger tracks all three current user-supplied sources. Tracking is not implementation or live validation.", "",
             "| Requirement | Current source | Status |", "|---|---|---|"]
    for item in entries:
        lines.append(f"| {item['id']} | {item['title']} ({item['file']}:{item['line']}) | TRACKED — audit/implementation/validation required |")
    lines.extend(["", "## Source hashes", ""])
    for _, path, _, _ in SOURCES:
        lines.append(f"- {path.name}: `{hashlib.sha256(path.read_bytes()).hexdigest()}`")
    (ROOT / "docs" / "CURRENT_SOURCE_COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
