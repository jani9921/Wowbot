"""Reproducible source distribution; excludes captures, databases and user caches."""
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    addon = ROOT / "addon" / "AIPlayerControllerExport"
    versioned = ROOT / "addon" / "AIPlayerControllerExport-12.1.0"
    versioned.mkdir(exist_ok=True)
    files = ("AIPlayerControllerExport.toc", "AIPlayerControllerExport.lua", "Transport.lua", "Bindings.lua")
    for name in files:
        shutil.copyfile(addon / name, versioned / name)
    output = ROOT / "output"
    addon_zip = output / "AIPlayerControllerExport-0.9.1-retail-12.1.0.zip"
    with zipfile.ZipFile(addon_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(addon / name, "AIPlayerControllerExport/" + name)
    agent_zip = output / "AIPC-Agent-0.9.4-live-world3d-debug-source.zip"
    with zipfile.ZipFile(agent_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("src", "tools", "tests"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and path.suffix in {".py", ".jsonl"} and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(ROOT).as_posix())
        for path in (ROOT / "config").rglob("*"):
            if path.is_file() and path.suffix in {".json", ".toml", ".yaml", ".yml"}:
                archive.write(path, path.relative_to(ROOT).as_posix())
        for path in [ROOT / "pyproject.toml", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md")),
                     output / "START_AGENT.bat", output / "REPLAY_AGENT.bat"]:
            archive.write(path, path.relative_to(ROOT).as_posix())
        for name in files:
            archive.write(addon / name, "addon/AIPlayerControllerExport/" + name)
            archive.write(versioned / name, "addon/AIPlayerControllerExport-12.1.0/" + name)
    print(addon_zip)
    print(agent_zip)


if __name__ == "__main__":
    main()
