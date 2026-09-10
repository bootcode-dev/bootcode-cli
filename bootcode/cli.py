"""``bootcode`` command-line entry point.

Click renders each command's docstring verbatim as that command's ``--help``
text, so the command docstrings below are written for students: no
reStructuredText markup (Click does not parse it) and no internal protocol
detail. Notes that only make sense to someone working on this repo belong
here in the module docstring, or in inline comments next to the code they
describe.

Implementation notes
--------------------

``login`` is three server calls, not two. ``POST .../login-codes`` only ever
returns ``{code}`` -- there is no ``verification_url`` field, it is built
locally from ``Config.frontend_url``; ``GET .../login-codes/{code}`` only
ever returns ``{status}``, never a token; and the ``cli_token`` is minted
exactly once by ``POST .../login-codes/{code}/exchange``, which also records
the local hostname as the device name shown in the web UI's
"CLI 登录设备" list. A final ``whoami`` call confirms the new token works and
supplies the handle to print. (An earlier version of this module assumed a
two-call flow and read a ``verification_url``/token out of the wrong
responses -- both assumptions were wrong.)

All commands are verified end-to-end against a real running bootcode-app.
"""

from __future__ import annotations

import base64
import json
import linecache
import time
import webbrowser
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import click
import requests

from bootcode import protocol
from bootcode._module_loader import load_module
from bootcode.config import Config
from bootcode.harness import resolve_and_call
from bootcode.workspace import Stage

try:
    import socket

    _DEVICE_NAME = socket.gethostname()
except Exception:  # pragma: no cover -- hostname lookup failing is not fatal
    _DEVICE_NAME = None

_LOGIN_POLL_INTERVAL_S = 2
_LOGIN_TIMEOUT_S = 300

try:
    _VERSION = _pkg_version("bootcode-cli")
except PackageNotFoundError:  # pragma: no cover -- only when run from an uninstalled checkout
    _VERSION = "0.0.0-dev"


@click.group()
@click.version_option(_VERSION, prog_name="bootcode")
def cli() -> None:
    """Pull course stages, run their tests locally, and submit your results.

    A typical session: log in once with bootcode login, then for each stage
    run bootcode pull to fetch its files, bootcode run to check your work
    offline, and bootcode submit to send it in for grading.
    """


@cli.command()
def login() -> None:
    """Log in through your browser.

    Prints a one-time code, opens the login page, and waits for you to
    confirm. Once confirmed, the credentials are saved on this machine and
    this command finishes by itself.
    """
    config = Config.load()
    response = requests.post(f"{config.api_url}/api/cli/login-codes", timeout=30)
    response.raise_for_status()
    code = response.json()["code"]
    verification_url = f"{config.frontend_url}/cli/login?code={code}"
    click.echo(f"Open {verification_url} and enter this code: {code}")
    webbrowser.open(verification_url)

    deadline = time.monotonic() + _LOGIN_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(_LOGIN_POLL_INTERVAL_S)
        poll = requests.get(f"{config.api_url}/api/cli/login-codes/{code}", timeout=30)
        if not poll.ok:
            # Only a 429 (server-side rate limiting) is transient -- mirrors
            # the archived Go CLI's waitForLoginConfirmation, which only
            # special-cases APIError.RateLimited() and treats anything else
            # as fatal. A previous version of this loop treated EVERY
            # non-2xx response as "keep waiting", which silently burned the
            # full 5-minute timeout on a genuine server error instead of
            # surfacing it.
            if poll.status_code == 429:
                continue
            try:
                message = (poll.json().get("error") or {}).get("message")
            except ValueError:
                message = None
            raise click.ClickException(message or f"checking login status: server returned {poll.status_code}")
        status = poll.json().get("status")
        if status == "confirmed":
            exchange = requests.post(
                f"{config.api_url}/api/cli/login-codes/{code}/exchange",
                json={"name": _DEVICE_NAME} if _DEVICE_NAME else {},
                timeout=30,
            )
            exchange.raise_for_status()
            config.cli_token = exchange.json()["token"]
            config.save()
            whoami = requests.get(
                f"{config.api_url}/api/cli/whoami",
                headers={"Authorization": f"Bearer {config.cli_token}"},
                timeout=30,
            )
            whoami.raise_for_status()
            click.echo(f"Logged in as {whoami.json().get('handle', '(unknown)')}")
            return
        if status in ("consumed", "expired"):
            raise click.ClickException(f"login code {status} -- run `bootcode login` again")
    raise click.ClickException("login timed out after 5 minutes")


@cli.command()
def status() -> None:
    """Show which account you are currently logged in as."""
    config = Config.load()
    if not config.cli_token:
        raise click.ClickException("not logged in -- run `bootcode login`")
    response = requests.get(
        f"{config.api_url}/api/cli/whoami",
        headers={"Authorization": f"Bearer {config.cli_token}"},
        timeout=30,
    )
    if response.status_code == 401:
        raise click.ClickException("token revoked or invalid -- run `bootcode login` again")
    response.raise_for_status()
    click.echo(f"Logged in as {response.json().get('handle', '(unknown)')}")


@cli.command()
@click.argument("key")
@click.argument("value")
def configure(key: str, value: str) -> None:
    """Change a local setting.

    Usage: bootcode configure <key> <value>, where <key> is one of api_url,
    frontend_url or cli_token. For example:

        bootcode configure api_url http://localhost:3000
    """
    config = Config.load()
    if not hasattr(config, key):
        raise click.ClickException(f"unknown config key: {key!r}")
    setattr(config, key, value)
    config.save()
    click.echo(f"{key} = {value}")


@cli.command()
def logout() -> None:
    """Log out on this machine.

    Removes the credential stored on this computer. To revoke a device
    entirely, remove it from the CLI devices page on the website.
    """
    config = Config.load()
    config.cli_token = ""
    config.save()
    click.echo("Logged out. To revoke this device entirely, remove it from the CLI devices page on the website.")


@cli.command()
@click.argument("course_stage")
def pull(course_stage: str) -> None:
    """Download a stage's files into this directory.

    Writes the stage's starter code and its test file here, so you can edit
    the starter code and run the tests locally before submitting.
    """
    course_slug, _, stage_slug = course_stage.partition("/")
    if not stage_slug:
        raise click.ClickException("expected <course-slug>/<stage-slug>")

    config = Config.load()
    response = requests.get(
        f"{config.api_url}/api/cli/courses/{course_slug}/stages/{stage_slug}",
        headers={"Authorization": f"Bearer {config.cli_token}"},
        timeout=30,
    )
    if not response.ok:
        # Mirrors the archived Go CLI's pull.go: a locked stage gets a
        # friendly message instead of a raw HTTPError traceback.
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        if error.get("code") == "STAGE_LOCKED":
            raise click.ClickException(f"{course_stage} is locked -- complete its prerequisite stage(s) first")
        raise click.ClickException(error.get("message") or f"server returned {response.status_code}")
    data = response.json()
    if data.get("type") != "cli-hidden":
        raise click.ClickException(f"{course_stage} is not a cli-hidden stage")
    tests_file = data.get("tests_file")
    if not tests_file:
        # Should be unreachable for a correctly authored stage (validate.ts
        # requires a non-empty test file for cli-hidden) -- guards against
        # indexing None below, which would otherwise be a raw TypeError
        # instead of an actionable message.
        raise click.ClickException(f"{course_stage} has no test file -- this looks like a content authoring bug")

    target_dir = Path.cwd()
    kept = _write_pulled_files(target_dir, [*data["starter_files"], tests_file])

    new_phase = data.get("phase")
    try:
        previous_phase = Stage.load(cwd=target_dir).phase
    except FileNotFoundError:
        previous_phase = None
    if previous_phase and new_phase and previous_phase != new_phase:
        click.secho(
            f"Note: this stage is from a new chapter ({new_phase}, previous was {previous_phase}) -- "
            "consider pulling into a fresh directory, e.g. `mkdir ../<new-chapter> && cd ../<new-chapter>`.",
            fg="yellow",
        )

    Stage(
        course_slug=course_slug,
        stage_slug=stage_slug,
        entry=data["entry"],
        tests_file=tests_file["path"],
        phase=new_phase,
    ).save(cwd=target_dir)
    click.echo(f"Pulled {course_stage} into the current directory.")
    if kept:
        click.echo(f"Kept existing local file(s) (not marked overwrite in files.yml): {', '.join(kept)}")


def _write_pulled_files(target_dir: Path, files: list[dict]) -> list[str]:
    """Writes each pulled file unless it already exists locally and the
    content author hasn't opted it into files.yml's ``overwrite: true``
    (default false -- protects a student's in-progress edits on re-pull).
    ``binary: true`` files have their ``content`` base64-decoded and written
    as raw bytes instead of text -- everything else keeps the existing UTF-8
    text write path unchanged.
    ``path`` may contain subdirectories (e.g. ``data/foo.png``) -- the parent
    directory is created as needed. Returns the paths that were left
    untouched."""
    kept = []
    for file in files:
        path = target_dir / file["path"]
        if path.exists() and not file.get("overwrite", False):
            kept.append(file["path"])
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if file.get("binary", False):
            path.write_bytes(base64.b64decode(file["content"]))
        else:
            path.write_text(file["content"])
    return kept


def _innermost_source_line(exc: BaseException) -> str | None:
    """Return ``"<file>:<line>: <source>"`` for the deepest traceback frame."""
    tb = exc.__traceback__
    if tb is None:
        return None
    while tb.tb_next is not None:
        tb = tb.tb_next
    filename = tb.tb_frame.f_code.co_filename
    source = linecache.getline(filename, tb.tb_lineno).strip()
    if not source:
        return None
    return f"{Path(filename).name}:{tb.tb_lineno}: {source}"


def _failing_assertion_detail(exc: AssertionError) -> str:
    """Describe a failed ``test_<problem>`` assertion for the student.

    Stage tests generally use a bare ``assert <expr>``, whose AssertionError
    stringifies to "". A bare exception object is always truthy, so an
    earlier ``exc or "assertion failed"`` fallback never fired and the
    student just saw a bare "FAIL: ". Fall back to the failing source line
    instead -- more useful anyway, since it shows exactly which expectation
    was not met (the test file is already in the student's own directory, so
    nothing hidden is revealed).
    """
    message = str(exc)
    if message:
        return message
    return _innermost_source_line(exc) or "assertion failed"


@cli.command()
def run() -> None:
    """Run this stage's tests locally.

    No network, nothing is submitted -- use this to check your work before
    running bootcode submit.
    """
    try:
        stage = Stage.load()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    solution = load_module(stage.entry)
    tests = load_module(stage.tests_file)
    test_fn = getattr(tests, f"test_{stage.problem}")
    try:
        resolve_and_call(test_fn, solution)
    except AssertionError as exc:
        click.secho(f"FAIL: {_failing_assertion_detail(exc)}", fg="red")
        raise SystemExit(1) from exc
    except Exception as exc:
        # Not every unimplemented/broken solution fails with AssertionError
        # or AttributeError -- e.g. a torch-based test touching a stub's
        # `None` return value can raise RuntimeError/TypeError/IndexError
        # depending on which op hits it first (see hw1's tests, hw0's pure
        # Python stubs never exercised this). Same rationale as submit()'s
        # broad except below: any exception while running the student's own
        # test is an everyday "solution isn't done yet" outcome, not a
        # bootcode-cli bug -- report it cleanly instead of a raw traceback.
        click.secho(f"FAIL: {exc.__class__.__name__}: {exc}", fg="red")
        if "NoneType" in str(exc):
            # The single most common cause across every stage: the solution
            # function still has its placeholder `pass` body, so it
            # implicitly returns None and whatever touches that value first
            # (often a torch/numpy internal) raises an unrelated-looking
            # error. Surface the likely real cause instead of leaving the
            # student to decode someone else's TypeError.
            click.secho(
                "提示：你的函数目前没有返回值（可能还是占位的 pass），"
                "请检查是否漏写了 return。",
                fg="yellow",
            )
        raise SystemExit(1) from exc
    click.secho("PASS", fg="green")


def _write_submit_debug_file(
    api_url: str, course_slug: str, stage_slug: str, values: list, response: requests.Response
) -> Path:
    """Write a --debug snapshot of the submission request/response, mirroring
    the old Go CLI's writeSubmitDebugFile (same filename convention and
    section headers, so existing muscle-memory/tooling around that file
    keeps working)."""
    timestamp = int(time.time())
    filename = f"bootcode-submit-debug-{course_slug}-{stage_slug}-{timestamp}.txt"
    endpoint = f"{api_url}/api/cli/courses/{course_slug}/stages/{stage_slug}/submit"
    contents = (
        "bootcode submit debug\n"
        f"Timestamp: {timestamp} (unix epoch seconds)\n"
        f"Stage: {course_slug}/{stage_slug}\n"
        f"Endpoint: {endpoint}\n\n"
        f"=== Request JSON ===\n{json.dumps({'values': values}, indent=2)}\n\n"
        f"=== Response ===\nStatus Code: {response.status_code}\n{response.text}\n"
    )
    path = Path.cwd() / filename
    path.write_text(contents)
    return path


@cli.command()
@click.option(
    "--debug",
    "debug_",
    is_flag=True,
    help="Write the raw submission request/response to a local debug file.",
)
def submit(debug_: bool) -> None:
    """Submit your work for grading.

    Runs the stage's grading function on your machine, then sends the
    collected values to the server in a single request. Failing costs
    nothing -- fix your code and submit again.
    """
    config = Config.load()
    try:
        stage = Stage.load()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    solution = load_module(stage.entry)
    tests = load_module(stage.tests_file)
    submit_fn = getattr(tests, f"submit_{stage.problem}")

    values: list = []
    protocol.bind_collector(values.append)
    try:
        resolve_and_call(submit_fn, solution)
    except Exception as exc:
        # A broken implementation crashing mid-submit (e.g. indexing an
        # empty list it produced) is just as everyday as a wrong-answer
        # rejection below -- same rationale, same fix: a clean one-line
        # message instead of the student's own exception traceback.
        raise click.ClickException(f"submit_{stage.problem}() raised {exc.__class__.__name__}: {exc}") from exc
    finally:
        protocol.unbind()

    response = protocol.submit_batch(config.api_url, config.cli_token, stage.course_slug, stage.stage_slug, values)
    try:
        body = response.json()
    except ValueError:
        body = {}

    if debug_:
        path = _write_submit_debug_file(config.api_url, stage.course_slug, stage.stage_slug, values, response)
        click.echo(f"Submission debug output written to {path}")

    raw_results = (body.get("test_run") or {}).get("raw_results") or []
    num_correct = 0
    for result in raw_results:
        correct = result["correct"]
        num_correct += correct
        click.secho(
            f"  [{result['testCaseIndex']}] {'correct' if correct else 'incorrect'}",
            fg="green" if correct else "red",
        )

    if not response.ok:
        # Three distinct everyday outcomes, not one generic bucket (mirrors
        # the old Go CLI's SubmitRejectedError/STAGE_LOCKED split in
        # cmd/submit.go): a locked stage, a genuine wrong-answer rejection
        # (the per-index table above already shows what failed), or anything
        # else (auth/network/server error).
        error = body.get("error") or {}
        if error.get("code") == "STAGE_LOCKED":
            raise click.ClickException("stage is locked -- complete the prerequisite stage(s) first")
        if raw_results:
            raise click.ClickException(f"submission rejected ({num_correct}/{len(raw_results)} correct)")
        message = error.get("message") or f"server returned {response.status_code}"
        raise click.ClickException(message)

    click.echo("Submitted.")
    click.echo(f"{config.frontend_url}/courses/{stage.course_slug}/stages/{stage.stage_slug}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
