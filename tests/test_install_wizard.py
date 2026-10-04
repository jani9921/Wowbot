"""Installation wizard (user 2026-10-02): maps, vmaps and mmaps come from the
TrinityCore extractors in ``_retail_`` and are read from there; no zip."""
import json
import sys
import time

import pytest

from wowbot.install import checks

BUILD_INFO = ("Branch!STRING:0|Active!DEC:1|Version!STRING:0|Product!STRING:0\n"
              "eu|1|12.1.0.69933|wow\n")


def _retail(tmp_path, *, extractors=True):
    retail = tmp_path / "World of Warcraft" / "_retail_"
    retail.mkdir(parents=True)
    (retail.parent / ".build.info").write_text(BUILD_INFO, encoding="utf-8")
    (retail / "Wow.exe").write_bytes(b"")
    (retail / "common.dll").write_bytes(b"")
    if extractors:
        for name in checks.EXTRACTORS:
            (retail / name).write_bytes(b"")
    return retail


def test_retail_validation_reads_version_and_extractors(tmp_path):
    retail = _retail(tmp_path)
    result = checks.validate_retail(retail)
    assert result["ok"] and result["writable"] and result["version_ok"]
    assert result["client_version"] == "12.1.0.69933" and result["dll_count"] == 1
    assert checks.detect_retail([retail]) == retail
    missing = checks.validate_retail(_retail(tmp_path / "b", extractors=False))
    # A valid Retail client can be selected even when navigation extractors
    # must be supplied later; the navigation stage checks those separately.
    assert missing["ok"] and missing["extractors"]["mmaps_generator.exe"] is False


def test_runtime_model_status_names_the_selected_yolo_backend(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    stem = "world3d_units_3class_v10_e65"
    (models / f"{stem}.pt").write_bytes(b"model")
    assert checks.runtime_model_status(tmp_path, "UNKNOWN")["backend"] == "CPU"
    assert checks.runtime_model_status(tmp_path, "NVIDIA", torch_cuda=True)["model_name"] == f"{stem}.pt"
    (models / f"{stem}.onnx").write_bytes(b"onnx")
    assert checks.runtime_model_status(tmp_path, "AMD", directml=True)["backend"] == "DirectML"
    assert checks.runtime_model_status(tmp_path, "INTEL", directml=True)["model_name"] == f"{stem}.onnx"
    (models / f"{stem}.engine").write_bytes(b"engine")
    assert checks.runtime_model_status(tmp_path, "NVIDIA", torch_cuda=True) == {
        "backend": "TensorRT", "pt": True, "onnx": True, "engine": True,
        "model_name": f"{stem}.engine", "accelerated": True}


def test_missing_navigation_extractors_fail_cleanly(tmp_path):
    from wowbot.install.wizard import InstallWizard
    retail = _retail(tmp_path, extractors=False)
    app = InstallWizard.__new__(InstallWizard)
    app.retail = type("Value", (), {"get": lambda self: str(retail)})()
    app.threads = type("Value", (), {"get": lambda self: 1})()
    app._navigation = lambda: {"focus": {checks.EXILES_REACH_MAP_ID:
                                        {"maps": False, "vmaps": False, "mmaps": False}}}
    lines = []
    app.write = lines.append
    for stage in (app._stage_maps, app._stage_vmaps, app._stage_mmaps):
        outcomes = []
        stage(outcomes.append)
        assert outcomes == [False]
    assert len(lines) == 3 and all("Hiányzik" in line for line in lines)


def test_all_in_one_finishes_with_backend_summary(tmp_path, monkeypatch):
    from wowbot.install import wizard
    app = wizard.InstallWizard.__new__(wizard.InstallWizard)
    app.retail = type("Value", (), {"get": lambda self: str(tmp_path)})()
    app.runner = type("Runner", (), {"busy": False})()
    app.torch_cuda = False
    app.directml_ready = True
    app._has_gpu = lambda: False
    app.vendor = lambda: "AMD"
    lines, pages, messages = [], [], []
    app.write = lines.append
    app.show = pages.append
    monkeypatch.setattr(wizard.checks, "validate_retail",
                        lambda _path: {"ok": True, "writable": True})
    monkeypatch.setattr(wizard.checks, "runtime_model_status",
                        lambda *_args, **_kwargs: {"backend": "DirectML",
                                                 "model_name": "world3d_units_3class_v10_e65.onnx"})
    monkeypatch.setattr(wizard.messagebox, "showinfo",
                        lambda title, message: messages.append((title, message)))
    for name in ("_stage_packages", "_stage_tensorrt", "_stage_directml", "_stage_addon",
                 "_stage_maps", "_stage_vmaps", "_stage_mmaps", "_stage_engine",
                 "_stage_verify", "_stage_save", "_stage_shortcuts"):
        setattr(app, name, lambda done: done(True))
    app.run_all()
    assert pages == [wizard.STEPS.index("Befejezés")]
    assert "DirectML" in messages[0][1]
    assert "world3d_units_3class_v10_e65.onnx" in messages[0][1]
    assert "Agent logika: CPU" in messages[0][1]


def test_navigation_status_per_map_from_the_extractor_layout(tmp_path):
    retail = _retail(tmp_path)
    (retail / "maps").mkdir()
    for name in ("2175.tilelist", "2175_08_25.map", "0000.tilelist"):
        (retail / "maps" / name).write_bytes(b"")
    (retail / "vmaps" / "2175").mkdir(parents=True)
    (retail / "vmaps" / "2175" / "2175.vmtree").write_bytes(b"")
    (retail / "vmaps" / "0000").mkdir()                     # no vmtree: not complete
    status = checks.navigation_status(retail)
    assert (status["maps_count"], status["vmaps_count"], status["mmaps_count"]) == (2, 1, 0)
    assert status["focus"][2175] == {"maps": True, "vmaps": True, "mmaps": False}
    (retail / "mmaps").mkdir()
    for name in ("2175.mmap", "2175_08_43.mmtile"):
        (retail / "mmaps" / name).write_bytes(b"")
    status = checks.navigation_status(retail)
    assert status["mmap_ids"] == [2175] and status["focus"][2175]["mmaps"] is True


def test_extraction_commands_match_extractor_bat_without_prompts(tmp_path):
    retail = tmp_path
    assert checks.extraction_commands("maps", retail) == [[str(retail / "mapextractor.exe")]]
    assert checks.extraction_commands("vmaps", retail)[1] == [
        str(retail / "vmap4assembler.exe"), "Buildings", "vmaps"]
    selected = checks.extraction_commands("mmaps", retail, map_ids=[2175, 0], threads=6)
    assert selected == [[str(retail / "mmaps_generator.exe"), "2175", "--silent", "--threads", "6"],
                        [str(retail / "mmaps_generator.exe"), "0", "--silent", "--threads", "6"]]
    assert checks.extraction_commands("mmaps", retail, map_ids=None, threads=0) == [
        [str(retail / "mmaps_generator.exe"), "--silent", "--threads", "1"]]
    with pytest.raises(ValueError):
        checks.extraction_commands("dbc", retail)


def test_map_id_parsing():
    assert checks.parse_map_ids("2175, 0 1;2175") == [2175, 0, 1]
    for bad in ("", "abc", "21x"):
        with pytest.raises(ValueError):
            checks.parse_map_ids(bad)


def test_exit_codes_are_explained():
    assert checks.explain_exit_code(0) == "kész"
    assert "DLL" in checks.explain_exit_code(0xC0000135)
    assert "DLL" in checks.explain_exit_code(-1073741515)
    assert checks.explain_exit_code(3) == "hibakód: 3"


def _status(**versions):
    rows = [(m, d, p, versions.get(d, "1.0")) for m, d, p in checks.REQUIRED_PACKAGES]
    return {"required": rows, "optional": []}


def test_pip_installs_only_what_is_missing_and_cuda_torch_from_its_index():
    assert checks.pip_commands("py", _status(), gpu=True, torch_cuda=True) == []
    commands = checks.pip_commands("py", _status(dxcam=None, torch=None), gpu=True, torch_cuda=None)
    assert commands[0] == ["py", "-m", "pip", "install", "dxcam"]
    assert commands[1][-2:] == ["--index-url", checks.TORCH_CUDA_INDEX]
    cpu_torch = checks.pip_commands("py", _status(), gpu=True, torch_cuda=False)
    assert "--force-reinstall" in cpu_torch[0] and checks.TORCH_CUDA_INDEX in cpu_torch[0]
    assert checks.pip_commands("py", _status(torch=None), gpu=False, torch_cuda=None) == [
        ["py", "-m", "pip", "install", "torch", "torchvision"]]


def test_addon_install_and_version_compare(tmp_path):
    project, retail = tmp_path / "projekt", _retail(tmp_path)
    source = project / "addon" / "AIPlayerControllerExport-12.1.0"
    source.mkdir(parents=True)
    (source / "AIPlayerControllerExport.toc").write_text("## Interface: 120100\n## Version: 0.9.37-12.1.0\n",
                                                         encoding="utf-8")
    (source / "Transport.lua").write_text("-- lua", encoding="utf-8")
    before = checks.addon_status(project, retail)
    assert before["installed_version"] is None and not before["up_to_date"]
    assert checks.install_addon(project, retail) == ["AIPlayerControllerExport.toc", "Transport.lua"]
    assert checks.addon_status(project, retail)["up_to_date"]


def test_saved_paths_point_the_agent_at_retail(tmp_path):
    retail = _retail(tmp_path)
    env = checks.write_local_env(tmp_path / "projekt", retail).read_text(encoding="utf-8")
    assert f'set "WOWBOT_WORLD_DATA_PATH={retail}"' in env
    assert f'set "WOWBOT_MMAP_PATH={retail / "mmaps"}"' in env and "chcp" not in env
    accented = checks.write_local_env(tmp_path / "p2", tmp_path / "Új" / "_retail_").read_text(encoding="utf-8")
    assert "@chcp 65001 >nul" in accented
    config = tmp_path / "agent_gui.json"
    config.write_text(json.dumps({"bindings_cache": "x.wtf", "goal": "Questelj",
                                  "mmap_path": "C:/Downloads/mmaps.zip"}), encoding="utf-8")
    data = checks.update_gui_config(config, retail / "mmaps")
    assert data == {"bindings_cache": "x.wtf", "goal": "Questelj", "mmap_path": str(retail / "mmaps")}


def _wait(predicate, timeout=20.):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not predicate():
        time.sleep(.05)
    return predicate()


def test_process_runner_streams_output_stops_on_error_and_cancels(tmp_path):
    from wowbot.install.wizard import ProcessRunner
    runner, done = ProcessRunner(), []
    runner.start([[sys.executable, "-c", "print('egy'); print('ketto')"],
                  [sys.executable, "-c", "import sys; sys.exit(3)"],
                  [sys.executable, "-c", "print('never')"]], tmp_path, done.append)
    assert _wait(lambda: done)
    lines = []
    while not runner.lines.empty():
        lines.append(runner.lines.get())
    assert done == [3] and "egy" in lines and "ketto" in lines
    assert not any("never" in line for line in lines if not line.startswith(">"))
    runner.start([[sys.executable, "-c", "import time; time.sleep(30)"]], tmp_path, done.append)
    assert _wait(lambda: runner.process is not None)
    runner.cancel()
    assert _wait(lambda: len(done) == 2) and done[1] is None


def test_every_wizard_page_renders(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from wowbot.install import wizard
    retail = _retail(tmp_path)
    monkeypatch.setattr(wizard.checks, "detect_retail", lambda *a, **k: retail)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    try:
        app = wizard.InstallWizard(root)
        app.torch_cuda = True          # skip the slow torch import check
        for index in range(len(wizard.STEPS)):
            app.show(index)
            root.update()
        assert _wait(lambda: (root.update(), app.status.get("Navigációs adatok"))[1], 10)
        assert app.status["WoW mappa"] == "ok"
        assert app.status["Navigációs adatok"] == "bad"    # nothing extracted in the fake folder
    finally:
        root.destroy()


def test_fresh_pc_autostart_login_env_and_shortcuts(tmp_path):
    """User 2026-10-03: the wizard leaves a fresh PC ready for AUTO_START."""
    from wowbot.install import checks
    assert checks.autostart_status(tmp_path) == {"account": "", "password_saved": False}
    checks.write_autostart_login(tmp_path, "user@example.com", "")
    assert checks.autostart_status(tmp_path) == {"account": "user@example.com", "password_saved": False}
    checks.write_autostart_login(tmp_path, "user@example.com", "typed-by-user")
    assert checks.autostart_status(tmp_path)["password_saved"] is True
    checks.write_autostart_login(tmp_path, "user@example.com", "")          # empty keeps the file
    assert checks.autostart_status(tmp_path)["password_saved"] is True
    env = checks.write_local_env(tmp_path, tmp_path / "_retail_").read_text(encoding="utf-8")
    assert 'set "AIPC_WOW_EXE=' in env and "Wow.exe" in env
    command = checks.shortcut_command(tmp_path)
    assert command[0] == "powershell" and "AUTO_START.bat" in command[-1]
