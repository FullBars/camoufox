"""Browser.newPageInWindow keeps cookie partitions on one tab strip.

The browser itself is not built here. These checks pin the protocol and the
release workflow that publishes the zip, both of which are source.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "additions" / "juggler" / "TargetRegistry.js"
PROTOCOL = ROOT / "additions" / "juggler" / "protocol" / "Protocol.js"
HANDLER = ROOT / "additions" / "juggler" / "protocol" / "BrowserHandler.js"
WORKFLOW = ROOT / ".github" / "workflows" / "browser-release.yml"


def _body(source: str, signature: str) -> str:
    start = source.find(signature)
    assert start != -1, signature
    # The signature may itself contain a destructuring `{`, which is not the body.
    brace = source.find("{", start + len(signature))
    depth = 0
    for index, char in enumerate(source[brace:], brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"unclosed {signature}")


def _workflow():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML 1.1 treats the bare key `on` as a boolean.
    trigger = data.get("on", data.get(True))
    return data, trigger


def _run_block(text: str) -> str:
    lines = text.splitlines()
    width = min(len(line) - len(line.lstrip(" ")) for line in lines if line.strip())
    return "\n".join(line[width:] if line.startswith(" " * width) else line for line in lines) + "\n"


def test_new_page_still_opens_a_window():
    source = REGISTRY.read_text(encoding="utf-8")
    body = _body(source, "async _newPageInternal({browserContextId})")
    assert "Services.ww.openWindow" in body
    assert "addTrustedTab" not in body
    assert "browserContext.userContextId" in body
    wrapper = _body(source, "async newPage({browserContextId})")
    assert "globalNewPageChain" in wrapper
    assert "_newPageInternal" in wrapper
    assert "_newPageInWindowInternal" not in wrapper


def test_new_page_in_window_adds_a_tab_in_the_context():
    source = REGISTRY.read_text(encoding="utf-8")
    body = _body(source, "async _newPageInWindowInternal({browserContextId, targetId})")
    assert "addTrustedTab" in body
    assert "openWindow" not in body
    assert "userContextId" in body
    assert "relatedToCurrent: false" in body
    assert "Unknown browserContextId" in body
    assert "Unknown targetId" in body
    assert "New tab opened outside the requested window" in body
    assert "New tab is not in the requested browser context" in body
    wrapper = _body(source, "async newPageInWindow({browserContextId, targetId})")
    assert "globalNewPageChain" in wrapper
    # The same chain as newPage, so the two cannot interleave.
    assert wrapper.count("globalNewPageChain") == 2


def test_cookie_isolation_stays_on_user_context_id():
    source = REGISTRY.read_text(encoding="utf-8")
    listener = _body(source, "const onTabOpenListener = (appWindow, window, event) =>")
    assert "tab.userContextId" in listener
    assert "_userContextIdToBrowserContext.get(userContextId)" in listener
    assert "removeCookiesWithOriginAttributes" in source
    assert "userContextId: this.userContextId" in source


def test_protocol_shape():
    source = PROTOCOL.read_text(encoding="utf-8")
    new_page = _body(source, "'newPage':")
    assert "browserContextId: t.Optional(t.String)" in new_page
    assert "targetId: t.String" in new_page
    assert "targetId: t.Optional" not in new_page
    # newPage's params are only the context. The anchor target is not part of it.
    assert new_page.count("targetId") == 1

    added = _body(source, "'newPageInWindow':")
    assert "targetId: t.String" in added
    assert "targetId: t.Optional" not in added
    assert "browserContextId: t.Optional(t.String)" in added

    handler = HANDLER.read_text(encoding="utf-8")
    new_page_handler = _body(handler, "async ['Browser.newPage']({browserContextId})")
    assert "newPage({browserContextId})" in new_page_handler
    assert "newPageInWindow" not in new_page_handler
    added_handler = _body(handler, "async ['Browser.newPageInWindow']({browserContextId, targetId})")
    assert "newPageInWindow({browserContextId, targetId})" in added_handler
    assert "return {targetId: newTargetId}" in added_handler


def test_protocol_note_and_readme():
    note = (ROOT / "additions" / "juggler" / "protocol" / "PROTOCOL.md").read_text(encoding="utf-8")
    assert "Browser.newPage" in note
    assert "Browser.newPageInWindow" in note
    assert "userContextId" in note
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Team Browser tab containers" in readme
    assert "Browser.newPageInWindow" in readme
    assert "browser-release.yml" in readme
    assert "ubuntu-24.04" in readme


def test_package_zip_name_is_unchanged():
    package = (ROOT / "scripts" / "package.py").read_text(encoding="utf-8")
    assert "camoufox-{args.version}-{args.release}-{args.os[:3]}.{args.arch}.zip" in package


def test_browser_release_is_tag_or_dispatch_only():
    data, trigger = _workflow()
    assert set(trigger) == {"workflow_dispatch", "push"}
    assert trigger["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+-*"]
    assert "branches" not in trigger["push"]
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["platforms"]["default"] == "linux"
    assert inputs["platforms"]["options"] == ["linux", "all"]
    assert inputs["runner"]["default"] == "ubuntu-24.04"
    assert "self-hosted" in inputs["runner"]["description"]
    assert inputs["ref"]["required"] is False
    assert "beta" in inputs["ref"]["description"]

    plan_ref = _checkout_ref(data["jobs"]["plan"])
    assert "inputs.ref" in plan_ref
    assert "github.sha" in plan_ref
    compiled = "${{ needs.plan.outputs.sha }}"
    assert _checkout_ref(data["jobs"]["build"]) == compiled
    assert _checkout_ref(data["jobs"]["publish"]) == compiled

    build = data["jobs"]["build"]
    assert build["runs-on"] == "${{ needs.plan.outputs.runner }}"
    assert build["timeout-minutes"] == 330
    assert "ci.run_prepare" in _job_text(build)
    assert "multibuild.py" in _job_text(build)
    assert "ci.release set-build" in _job_text(build)
    # Package removal and the swap file are for disposable GitHub-hosted images.
    gated = [
        step for step in build["steps"]
        if step.get("if") == "startsWith(needs.plan.outputs.runner, 'ubuntu-')"
    ]
    assert len(gated) == 3

    publish = data["jobs"]["publish"]
    assert publish["runs-on"] == "ubuntu-24.04"
    assert publish["permissions"]["contents"] == "write"
    assert "camoufox-*.zip" in _job_text(publish)
    assert "--prerelease" in _job_text(publish)
    assert "--latest=false" in _job_text(publish)
    assert 'SOURCE_SHA' in _job_text(publish)
    assert "--target \"$SOURCE_SHA\"" in _job_text(publish)


def test_release_scripts_parse_and_the_plan_picks_linux():
    data, _trigger = _workflow()
    plan_script = _run_block(data["jobs"]["plan"]["steps"][1]["run"])
    publish_script = _run_block(data["jobs"]["publish"]["steps"][-1]["run"])
    subprocess.run(["bash", "-n", "-c", plan_script], check=True)
    subprocess.run(["bash", "-n", "-c", publish_script], check=True)

    out = _plan(plan_script, REF_TYPE="branch", REF_NAME="v156.0.1-beta.36")
    assert out["runner"] == "ubuntu-24.04"
    assert out["sha"] == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    # A branch that happens to be named like a tag does not republish that tag.
    assert out["tag"] == _next_browser_tag()
    assert out["matrix"] == '{"include":[{"target":"linux","arch":"x86_64"}]}'

    out = _plan(plan_script, REF_TYPE="tag", REF_NAME="v156.0.1-beta.37")
    assert out["tag"] == "v156.0.1-beta.37"

    out = _plan(plan_script, REF_TYPE="branch", REF_NAME="main", INPUT_PLATFORMS="all", INPUT_RUNNER="self-hosted")
    assert out["runner"] == "self-hosted"
    assert "windows" in out["matrix"] and "macos" in out["matrix"]
    assert out["tag"] == _next_browser_tag()

    out = _plan(plan_script, REF_TYPE="branch", REF_NAME="main", INPUT_TAG="v156.0.1-beta.40")
    assert out["tag"] == "v156.0.1-beta.40"

    # A library tag is not a reason to compile. The workflow's tag filter is
    # what enforces that; the plan still has to name something if dispatched.
    assert "v[0-9]+.[0-9]+.[0-9]+-*" in WORKFLOW.read_text(encoding="utf-8")


def _next_browser_tag() -> str:
    from ci.release import next_browser_release
    from ci._util import REPO_ROOT, read_upstream_sh, run

    up = read_upstream_sh()
    tags = run(["git", "tag", "-l", "v*"], cwd=REPO_ROOT, check=True).stdout.split()
    return f"v{up['version']}-{next_browser_release(up['release'], tags)}"


def _plan(script: str, **env: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "github-output.txt"
        output.write_text("", encoding="utf-8")
        full = dict(os.environ)
        full.update({
            "GITHUB_OUTPUT": str(output),
            "INPUT_RUNNER": "",
            "INPUT_PLATFORMS": "",
            "INPUT_TAG": "",
            "VAR_RUNNER": "",
            "REF_TYPE": "branch",
            "REF_NAME": "main",
        })
        full.update(env)
        subprocess.run(["bash", "-c", script], check=True, cwd=ROOT, env=full)
        parsed = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            key, value = line.split("=", 1)
            parsed[key] = value
        return parsed


def _checkout_ref(job: dict) -> str:
    for step in job["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            return step["with"]["ref"]
    raise AssertionError("no checkout")


def _job_text(job: dict) -> str:
    parts = []
    for step in job["steps"]:
        if "run" in step:
            parts.append(step["run"])
    return "\n".join(parts)
