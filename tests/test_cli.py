from unittest.mock import MagicMock, patch

import base64

from click.testing import CliRunner

from bootcode.cli import cli
from bootcode.config import Config
from bootcode.workspace import Stage


def test_help_lists_all_subcommands():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in ["login", "logout", "pull", "run", "submit", "status", "configure"]:
        assert name in result.output


def test_version_flag_reports_a_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "bootcode" in result.output


def test_logout_clears_the_stored_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    Config(cli_token="tok-xyz").save()

    result = CliRunner().invoke(cli, ["logout"])

    assert result.exit_code == 0
    assert Config.load().cli_token == ""


def test_config_file_is_saved_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    Config(cli_token="tok-xyz").save()

    path = tmp_path / "config" / "config.toml"
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_pull_reports_a_friendly_message_when_the_stage_is_locked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))

    fake_response = MagicMock()
    fake_response.ok = False
    fake_response.status_code = 403
    fake_response.json.return_value = {
        "error": {"code": "STAGE_LOCKED", "message": "prerequisite stages must be completed first"},
    }

    with patch("bootcode.cli.requests.get", return_value=fake_response):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw0-primes"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "is locked" in result.output


def test_pull_reports_a_friendly_error_instead_of_crashing_when_tests_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))

    fake_response = MagicMock()
    fake_response.ok = True
    fake_response.json.return_value = {
        "type": "cli-hidden",
        "entry": "add.py",
        "starter_files": [{"path": "add.py", "content": "def add(a, b):\n    pass\n"}],
        "tests_file": None,
        "language": "python",
    }

    with patch("bootcode.cli.requests.get", return_value=fake_response):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw0-add"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "no test file" in result.output


def _fake_pull_response(*, add_overwrite: bool | None = None, tests_overwrite: bool | None = None) -> MagicMock:
    starter_file = {"path": "add.py", "content": "def add(a, b):\n    return a + b\n"}
    tests_file = {"path": "add_tests.py", "content": "import bootcode\n"}
    if add_overwrite is not None:
        starter_file["overwrite"] = add_overwrite
    if tests_overwrite is not None:
        tests_file["overwrite"] = tests_overwrite
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "type": "cli-hidden",
        "entry": "add.py",
        "starter_files": [starter_file],
        "tests_file": tests_file,
        "language": "python",
    }
    return response


def test_pull_does_not_overwrite_an_existing_local_file_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "add.py").write_text("def add(a, b):\n    return a + b  # my in-progress edit\n")

    with patch("bootcode.cli.requests.get", return_value=_fake_pull_response()):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw0-add"])

    assert result.exit_code == 0
    assert "my in-progress edit" in (tmp_path / "add.py").read_text()
    assert "Kept existing local file(s)" in result.output
    assert "add.py" in result.output
    # tests_file is freshly written since it didn't exist locally yet.
    assert (tmp_path / "add_tests.py").exists()


def test_pull_overwrites_an_existing_local_file_when_files_yml_opts_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "add.py").write_text("stale content\n")

    with patch("bootcode.cli.requests.get", return_value=_fake_pull_response(add_overwrite=True)):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw0-add"])

    assert result.exit_code == 0
    assert (tmp_path / "add.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert "Kept existing local file(s)" not in result.output


def test_pull_writes_a_binary_file_as_raw_bytes_from_base64(tmp_path, monkeypatch):
    # binary: true files carry base64 in `content` -- must round-trip to the
    # exact original bytes, not the base64 text itself (see 00-design.md's
    # binary-files doc and app/api/cli/.../route.ts's `binary` passthrough).
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    raw_bytes = bytes(range(256))
    encoded = base64.b64encode(raw_bytes).decode("ascii")

    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "type": "cli-hidden",
        "entry": "classify_zero_one.py",
        "starter_files": [
            {"path": "classify_zero_one.py", "content": "def classify_zero_one(x):\n    pass\n"},
            {"path": "mnist_01_subset.npz", "content": encoded, "binary": True},
        ],
        "tests_file": {"path": "classify_zero_one_tests.py", "content": "import bootcode\n"},
        "language": "python",
    }

    with patch("bootcode.cli.requests.get", return_value=response):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw1-classify-zero-one"])

    assert result.exit_code == 0
    assert (tmp_path / "mnist_01_subset.npz").read_bytes() == raw_bytes


def test_pull_creates_subdirectories_for_a_nested_path(tmp_path, monkeypatch):
    # `path` may put a file under a subdirectory (e.g. "data/foo.png") --
    # the parent dir must be created, it won't already exist on a fresh pull.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))

    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "type": "cli-hidden",
        "entry": "classify_zero_one.py",
        "starter_files": [
            {"path": "classify_zero_one.py", "content": "def classify_zero_one(x):\n    pass\n"},
            {"path": "data/labels.txt", "content": "01101\n"},
        ],
        "tests_file": {"path": "classify_zero_one_tests.py", "content": "import bootcode\n"},
        "language": "python",
    }

    with patch("bootcode.cli.requests.get", return_value=response):
        result = CliRunner().invoke(cli, ["pull", "modernai-hw/hw1-classify-zero-one"])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "labels.txt").read_text() == "01101\n"



def test_login_polls_status_then_exchanges_for_a_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))

    post_login_codes = MagicMock()
    post_login_codes.json.return_value = {"code": "abc123"}
    post_login_codes.raise_for_status.return_value = None

    get_status_confirmed = MagicMock(ok=True)
    get_status_confirmed.json.return_value = {"status": "confirmed"}

    exchange_response = MagicMock()
    exchange_response.json.return_value = {"token": "tok-xyz", "expires_at": None}
    exchange_response.raise_for_status.return_value = None

    whoami_response = MagicMock()
    whoami_response.json.return_value = {"handle": "octocat"}
    whoami_response.raise_for_status.return_value = None

    exchanged_calls = []

    def fake_post(url, **kwargs):
        if url.endswith("/api/cli/login-codes"):
            return post_login_codes
        if url.endswith("/exchange"):
            exchanged_calls.append(kwargs)
            return exchange_response
        raise AssertionError(f"unexpected POST {url}")

    with (
        patch("bootcode.cli.requests.post", side_effect=fake_post),
        patch("bootcode.cli.requests.get", side_effect=[get_status_confirmed, whoami_response]),
        patch("bootcode.cli.webbrowser.open"),
        patch("bootcode.cli.time.sleep"),
        patch("bootcode.cli._DEVICE_NAME", "alices-macbook"),
    ):
        result = CliRunner().invoke(cli, ["login"])

    assert result.exit_code == 0
    assert "Logged in as octocat" in result.output
    # the local hostname is sent so the device isn't stuck showing as
    # "未命名设备" in the Web "CLI 登录设备" list (a real bug found and fixed).
    assert exchanged_calls == [{"json": {"name": "alices-macbook"}, "timeout": 30}]

    from bootcode.config import Config

    assert Config.load().cli_token == "tok-xyz"


def test_login_raises_a_clear_error_when_the_code_expires(monkeypatch):
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", "/tmp/unused-bootcode-config-dir")

    post_login_codes = MagicMock()
    post_login_codes.json.return_value = {"code": "abc123"}
    post_login_codes.raise_for_status.return_value = None
    get_status_expired = MagicMock(ok=True)
    get_status_expired.json.return_value = {"status": "expired"}

    with (
        patch("bootcode.cli.requests.post", return_value=post_login_codes),
        patch("bootcode.cli.requests.get", return_value=get_status_expired),
        patch("bootcode.cli.webbrowser.open"),
        patch("bootcode.cli.time.sleep"),
    ):
        result = CliRunner().invoke(cli, ["login"])

    assert result.exit_code != 0
    assert "expired" in result.output


def test_login_fails_fast_on_a_genuine_polling_error_instead_of_retrying_for_5_minutes(monkeypatch):
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", "/tmp/unused-bootcode-config-dir")

    post_login_codes = MagicMock()
    post_login_codes.json.return_value = {"code": "abc123"}
    post_login_codes.raise_for_status.return_value = None
    get_status_error = MagicMock(ok=False, status_code=500)
    get_status_error.json.return_value = {"error": {"code": "INTERNAL", "message": "db unavailable"}}

    with (
        patch("bootcode.cli.requests.post", return_value=post_login_codes),
        patch("bootcode.cli.requests.get", return_value=get_status_error) as mock_get,
        patch("bootcode.cli.webbrowser.open"),
        patch("bootcode.cli.time.sleep"),
    ):
        result = CliRunner().invoke(cli, ["login"])

    assert result.exit_code != 0
    assert "db unavailable" in result.output
    # a non-429 error must not be retried -- only the one poll should happen
    mock_get.assert_called_once()


def _write_add_stage(tmp_path, implementation: str) -> None:
    (tmp_path / "add.py").write_text(implementation)
    (tmp_path / "add_tests.py").write_text("def test_add(add):\n    assert add(2, 3) == 5\n")
    Stage(course_slug="modernai-hw", stage_slug="hw0-add", entry="add.py", tests_file="add_tests.py").save(cwd=tmp_path)


def test_run_passes_for_a_correct_solution_with_no_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_add_stage(tmp_path, "def add(a, b):\n    return a + b\n")

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 0
    assert "PASS" in result.output


def test_run_fails_for_a_wrong_solution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_add_stage(tmp_path, "def add(a, b):\n    return a - b\n")

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_run_fails_cleanly_when_the_test_raises_a_non_assertion_exception(tmp_path, monkeypatch):
    # An unimplemented stub returning None can make a test raise something
    # other than AssertionError/AttributeError depending on what touches the
    # None value first (e.g. hw1's torch-based tests) -- must not crash with
    # a raw traceback.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "add.py").write_text("def add(a, b):\n    pass\n")
    (tmp_path / "add_tests.py").write_text("def test_add(add):\n    return int(add(2, 3))\n")
    Stage(course_slug="modernai-hw", stage_slug="hw0-add", entry="add.py", tests_file="add_tests.py").save(cwd=tmp_path)

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "FAIL: TypeError" in result.output


def test_run_hints_at_a_missing_return_when_the_exception_mentions_nonetype(tmp_path, monkeypatch):
    # Friendlier UX on top of the generic except-Exception fallback above --
    # "not NoneType" appears in the message of most of these stub-returned-
    # None failures (torch/numpy internals included), so a substring check
    # is a decent generic proxy for "you forgot a return" without needing to
    # know anything about the specific stage's test.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "add.py").write_text("def add(a, b):\n    pass\n")
    (tmp_path / "add_tests.py").write_text("def test_add(add):\n    return int(add(2, 3))\n")
    Stage(course_slug="modernai-hw", stage_slug="hw0-add", entry="add.py", tests_file="add_tests.py").save(cwd=tmp_path)

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 1
    assert "你的函数目前没有返回值" in result.output


def test_run_without_a_pulled_stage_fails_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "bootcode pull" in result.output


def _write_add_stage_with_submit(tmp_path, implementation: str) -> None:
    (tmp_path / "add.py").write_text(implementation)
    (tmp_path / "add_tests.py").write_text(
        "import bootcode\n\n"
        "def test_add(add):\n    assert add(2, 3) == 5\n\n"
        "def submit_add(add):\n    bootcode.submit(add(2, 3))\n    bootcode.submit(add(1, 1))\n"
    )
    Stage(course_slug="modernai-hw", stage_slug="hw0-add", entry="add.py", tests_file="add_tests.py").save(cwd=tmp_path)


def test_submit_collects_all_values_locally_then_posts_once_and_prints_each_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    _write_add_stage_with_submit(tmp_path, "def add(a, b):\n    return a + b\n")

    fake_response = MagicMock()
    fake_response.ok = True
    fake_response.json.return_value = {
        "submission_id": "sub-1",
        "test_run": {
            "status": "fail",
            "raw_results": [
                {"testCaseIndex": 0, "correct": True},
                {"testCaseIndex": 1, "correct": False},
            ],
        },
    }

    with patch("bootcode.cli.protocol.submit_batch", return_value=fake_response) as mock_submit_batch:
        result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code == 0
    assert "[0] correct" in result.output
    assert "[1] incorrect" in result.output
    assert "Submitted." in result.output

    # submit_add(add) called bootcode.submit(add(2, 3)) then bootcode.submit(add(1, 1))
    # -- the collected, encode_json-encoded values are POSTed in that same order.
    mock_submit_batch.assert_called_once()
    values = mock_submit_batch.call_args[0][-1]
    assert values == [5, 2]


def test_submit_raises_when_the_server_rejects_the_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    _write_add_stage_with_submit(tmp_path, "def add(a, b):\n    return a + b\n")

    fake_response = MagicMock()
    fake_response.ok = False
    fake_response.status_code = 422
    fake_response.json.return_value = {
        "error": {"code": "SERVER_REVALUATION_FAILED", "message": "nope"},
        "test_run": {
            "status": "fail",
            "raw_results": [
                {"testCaseIndex": 0, "correct": False},
                {"testCaseIndex": 1, "correct": False},
            ],
        },
    }

    with patch("bootcode.cli.protocol.submit_batch", return_value=fake_response):
        result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    # A genuine wrong-answer rejection is its own distinct branch (docs/
    # 00-design.md Sec 4.1) -- the per-index table above already shows what
    # failed, so the server's own (arbitrary) message text is deliberately
    # NOT echoed here, unlike the generic-error fallback branch.
    assert "submission rejected (0/2 correct)" in result.output
    assert "nope" not in result.output


def test_submit_without_a_pulled_stage_fails_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))

    result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "bootcode pull" in result.output


def test_submit_reports_a_friendly_message_when_the_stage_is_locked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    _write_add_stage_with_submit(tmp_path, "def add(a, b):\n    return a + b\n")

    fake_response = MagicMock()
    fake_response.ok = False
    fake_response.status_code = 403
    fake_response.json.return_value = {
        "error": {"code": "STAGE_LOCKED", "message": "prerequisite stages must be completed first"},
    }

    with patch("bootcode.cli.protocol.submit_batch", return_value=fake_response):
        result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "stage is locked" in result.output


def test_submit_prints_the_stage_page_link_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    _write_add_stage_with_submit(tmp_path, "def add(a, b):\n    return a + b\n")

    fake_response = MagicMock()
    fake_response.ok = True
    fake_response.json.return_value = {
        "submission_id": "sub-1",
        "test_run": {"status": "pass", "raw_results": [{"testCaseIndex": 0, "correct": True}]},
    }

    with patch("bootcode.cli.protocol.submit_batch", return_value=fake_response):
        result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code == 0
    assert "Submitted." in result.output
    assert "/courses/modernai-hw/stages/hw0-add" in result.output


def test_submit_debug_writes_a_local_request_response_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    _write_add_stage_with_submit(tmp_path, "def add(a, b):\n    return a + b\n")

    fake_response = MagicMock()
    fake_response.ok = True
    fake_response.status_code = 201
    fake_response.text = '{"submission_id": "sub-1"}'
    fake_response.json.return_value = {
        "submission_id": "sub-1",
        "test_run": {"status": "pass", "raw_results": [{"testCaseIndex": 0, "correct": True}]},
    }

    with patch("bootcode.cli.protocol.submit_batch", return_value=fake_response):
        result = CliRunner().invoke(cli, ["submit", "--debug"])

    assert result.exit_code == 0
    debug_files = list(tmp_path.glob("bootcode-submit-debug-modernai-hw-hw0-add-*.txt"))
    assert len(debug_files) == 1
    contents = debug_files[0].read_text()
    assert "=== Request JSON ===" in contents
    assert "=== Response ===" in contents
    assert "sub-1" in contents


def test_submit_reports_a_clean_error_when_the_students_code_crashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTCODE_CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "add.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "add_tests.py").write_text(
        "import bootcode\n\n"
        "def test_add(add):\n    assert add(2, 3) == 5\n\n"
        "def submit_add(add):\n    raise IndexError('list index out of range')\n"
    )
    Stage(course_slug="modernai-hw", stage_slug="hw0-add", entry="add.py", tests_file="add_tests.py").save(cwd=tmp_path)

    with patch("bootcode.cli.protocol.submit_batch") as mock_submit_batch:
        result = CliRunner().invoke(cli, ["submit"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "submit_add() raised IndexError: list index out of range" in result.output
    # the crash happened before any network call was made
    mock_submit_batch.assert_not_called()
