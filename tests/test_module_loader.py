from bootcode._module_loader import load_module


def test_load_module_puts_the_stage_dir_on_sys_path_for_sibling_imports(tmp_path):
    # Without this, a solution/test file that does `import polynomial` (a
    # sibling module in the same pulled directory) fails with
    # ModuleNotFoundError, since `bootcode` is an installed console-script --
    # sys.path[0] is its own install location, never the student's cwd.
    (tmp_path / "helper.py").write_text("VALUE = 42\n")
    (tmp_path / "main.py").write_text("import helper\n\ndef get():\n    return helper.VALUE\n")

    module = load_module(tmp_path / "main.py")

    assert module.get() == 42
