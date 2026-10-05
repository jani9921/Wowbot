# WoW Retail AI agent 

Autonomous questing agent for World of Warcraft Retail 12.1 on a private sandbox server.
It reads the game through its own addon (pixel-strip telemetry), sees the 3D world with a
YOLO detector, plans with a shared WorldModel / planner / skill architecture and drives the
client with ordinary keyboard and mouse input for the selected process only. No memory
reading, injection or secret-value bypasses.

## Install
1. Python 3.13 (64-bit) on Windows 10/11.
2. Run `INSTALL_WIZARD.bat` → "Minden egyben telepítés" (all-in-one):
   Python packages (CUDA torch on NVIDIA, `onnxruntime-directml` on AMD/Intel), WoW addon,
   navigation data (maps/vmaps/mmaps via the TrinityCore extractors placed in `_retail_`),
   the YOLO model for this GPU and the start shortcuts.
3. Optional login file for unattended start: `config/wow_account.txt`, `config/wow_password.txt`
   (created by you, never committed – see `.gitignore`).
4. The GUI starts with Ollama disabled and has no Ollama switch. The agent does
   not require Ollama for normal use.

## Run
`START_AGENT.bat` (GUI) or `AUTO_START.bat`. See `HOW_TO_USE.md`.

`examples/bindings-cache.example.wtf` is a real exported binding cache for
reference. It is **not** selected automatically: choose a cache explicitly in
the GUI, and verify it matches the bindings of the running WoW client. On a
new machine, the addon export can create a fresh cache for that client.

## Not included
- TensorRT engines (built per GPU by the wizard), training datasets and runs, personal agent
  memory and logs, the TrinityCore spawn catalog (`data/tdb_spawn_catalog.sqlite3`, optional).
- Recast/Detour sources: a prebuilt `native/bin/aipc_detour.dll` is included; to rebuild it,
  clone https://github.com/recastnavigation/recastnavigation into `native/recastnavigation`
  and build `native/detour_shim` with CMake.
- `weights/yolo26n.pt` (Ultralytics base weights, only for training; downloaded by Ultralytics).

## Tests
`python -m pytest tests`
