# WoW Retail AI agent 

Autonomous questing agent for World of Warcraft Retail 12.1.
It reads the game through its own addon (pixel-strip telemetry), sees the 3D world with a
YOLO detector, plans with a shared WorldModel / planner / skill architecture and drives the
client with ordinary keyboard and mouse input for the selected process only. No memory
reading, injection or secret-value bypasses.

**📋 [Bug fixes / javítások](BUGFIXES.md)** — what the live tests found and how it was fixed, day by day.

## Install
1. Python 3.13 (64-bit) on Windows 10/11.
2. Run `INSTALL_WIZARD.bat` → "Minden egyben telepítés" (all-in-one):
   Python packages (CUDA torch on NVIDIA, `onnxruntime-directml` on AMD/Intel), WoW addon,
   navigation data (maps/vmaps/mmaps via the TrinityCore extractors placed in `_retail_`),
   the YOLO model for this GPU and the start shortcuts. A missing TensorRT engine or DirectML
   provider is reported as a warning (the YOLO then runs on PyTorch CUDA or the CPU); it no
   longer stops the install.
3. Optional login file for unattended start: `config/wow_account.txt`, `config/wow_password.txt`
   (created by you, never committed – see `.gitignore`).
4. Optional local LLM for complex quest text: the wizard's last step (after a confirmation)
   installs Ollama with winget, starts it and pulls the model named in
   `config/ai_decision.json` → `semantic.model` (`qwen3:4b-instruct-2507-q4_K_M`, ~2.5 GB).
   The quest-text interpreter is on by default and simply stays idle while Ollama is not
   running; the older Ollama *planner* advisor stays off. Turn the interpreter off with
   `semantic.enabled: false` or `AIPC_SEMANTIC_ENABLED=0`.

## Run
`START_AGENT.bat` (GUI) or `AUTO_START.bat`. See `HOW_TO_USE.md`.

`examples/bindings-cache.example.wtf` is a real exported binding cache for
reference. It is **not** selected automatically: choose a cache explicitly in
the GUI, and verify it matches the bindings of the running WoW client. On a
new machine, the addon export can create a fresh cache for that client.

## Bug fixes
The fixes of the live tests, grouped by day and area, with live-validated (✅) or
offline-tested (🧪) status: [BUGFIXES.md](BUGFIXES.md). Full detail:
[docs/LIVE_VALIDATION.md](docs/LIVE_VALIDATION.md).

## Not included
- TensorRT engines (built per GPU by the wizard), training datasets and runs, personal agent
  memory and logs, the TrinityCore spawn catalog (`data/tdb_spawn_catalog.sqlite3`, optional).
- Recast/Detour sources: a prebuilt `native/bin/aipc_detour.dll` is included; to rebuild it,
  clone https://github.com/recastnavigation/recastnavigation into `native/recastnavigation`
  and build `native/detour_shim` with CMake.
- `weights/yolo26n.pt` (Ultralytics base weights, only for training; downloaded by Ultralytics).

## Tests
`python -m pytest tests`
