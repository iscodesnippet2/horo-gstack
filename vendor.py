"""Assemble src/horo_gstack/_vendor from one gstack commit and its Hermes render.

    python vendor.py <gstack-checkout> <render-skills-dir> [post]

<gstack-checkout> has had `bun install --frozen-lockfile --ignore-scripts` on
linux-x64; <render-skills-dir> is `gen-skill-docs.ts --host hermes
--install-root /opt/horo-gstack` output (its .hermes/skills). The version is
gstack's own; `post` (1, 2, ...) adds .postN when only this packaging changed.

The wheel carries three things:
  skills/        the render, minus EXCLUDED; still pointing at /opt/horo-gstack,
                 which `horo-gstack install` rewrites to the real runtime path
  runtime/       the checkout gstack's scripts run from, without tests, docs or
                 build-only material
  runtime/node_modules
                 only what browse needs (Playwright, sharp and its linux-x64
                 libvips, diff, socks), resolved from package.json files
Two compiled binaries upstream builds at setup become bun wrappers, so nothing
here is built for a platform except sharp's prebuilt native parts.

Every check fails closed: an excluded skill that no longer exists, a license
that changed, or npm licenses that differ from pyproject.toml's stop the build.
"""

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "src" / "horo_gstack" / "_vendor"
INSTALL_ROOT = "/opt/horo-gstack"

# Render directory names left out, each for a reason an offline CentOS install
# with pip, npm and Google Chrome cannot work around.
EXCLUDED = {
    "gstack-open-gstack-browser": "headed Chromium with gstack's extension; Google Chrome blocks --load-extension",
    "gstack-pair-agent": "lets a remote agent drive the browser through an ngrok tunnel",
    "gstack-setup-gbrain": "installs gbrain with curl and can use Supabase",
    "gstack-sync-gbrain": "keeps gbrain in sync; needs setup-gbrain",
    "gstack-ubicloud": "runs work on Ubicloud VMs",
    "gstack-upgrade": "upgrades by cloning github.com/garrytan/gstack; upgrade with pip instead",
    "gstack-codex": "wraps the OpenAI Codex CLI",
    "gstack-claude-code": "wraps the Claude Code CLI",
    "gstack-benchmark-models": "compares Claude, GPT and Gemini CLIs",
    "gstack-plan-tune": "calls the Anthropic API",
    "gstack-make-pdf": "needs make-pdf's compiled binary and a browser PDF pipeline not tested here",
    "gstack-cso": "needs gstack-cso-launcher, a separate native build",
    "gstack-ios-clean": "needs Xcode",
    "gstack-ios-design-review": "iOS only; target machines run CentOS",
    "gstack-ios-fix": "needs Xcode",
    "gstack-ios-qa": "needs Xcode",
    "gstack-ios-sync": "needs Xcode",
}

# Checkout paths the runtime does not need.
RUNTIME_SKIP = {".git", ".github", "node_modules", "test", "docs", "changelog.d", "contrib",
                "CHANGELOG.md", "TODOS.md", ".hermes", ".claude", ".agents"}

# browse's server and its screenshot guard import these; everything they
# depend on comes with them.
NPM_ROOTS = ["playwright", "diff", "socks", "sharp"]

# pyproject.toml's license expression must name exactly MIT plus the npm
# packages' licenses: a new or dropped one stops the build until it is updated.
LICENSE_RE = re.compile(r'^license = "([^"]+)"', re.M)

BROWSE_WRAPPER = """#!/usr/bin/env bash
# horo-gstack: browse run from source with bun instead of upstream's compiled
# client. Uses the browser `horo-gstack install` found, unless
# GSTACK_CHROMIUM_PATH is set.
here=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
if [ -z "${GSTACK_CHROMIUM_PATH:-}" ] && [ -s "$here/../.chrome-path" ]; then
  GSTACK_CHROMIUM_PATH=$(cat "$here/../.chrome-path"); export GSTACK_CHROMIUM_PATH
fi
exec bun --no-env-file --config=/dev/null "$here/../src/cli.ts" "$@"
"""

DISCOVER_WRAPPER = """#!/usr/bin/env bash
# horo-gstack: gstack-global-discover run from source with bun instead of
# upstream's compiled binary.
here=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
exec bun --no-env-file --config=/dev/null "$here/gstack-global-discover.ts" "$@"
"""


def fail(msg):
    sys.exit(f"[vendor] FAIL {msg}")


def write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def npm_closure(modules: Path) -> list[dict]:
    """The packages NPM_ROOTS need, from their package.json files, skipping
    platform packages bun did not install (other OS/CPU) and musl builds."""
    seen: dict[str, dict] = {}
    todo = list(NPM_ROOTS)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        pj = modules / name / "package.json"
        if not pj.is_file():
            if name in NPM_ROOTS:
                fail(f"node_modules/{name} missing; run bun install first")
            continue  # an optional dependency for another platform
        meta = json.loads(pj.read_text())
        lic = meta.get("license") or ""
        seen[name] = {"name": name, "version": meta["version"], "license": lic}
        deps = {**meta.get("dependencies", {}), **meta.get("optionalDependencies", {})}
        todo += [d for d in deps if "musl" not in d]
    return sorted(seen.values(), key=lambda p: p["name"])


def main(checkout: Path, render: Path, post=None):
    if not (checkout / "LICENSE").read_text().startswith("MIT License"):
        fail("gstack is no longer MIT-licensed; review before shipping")
    if not (checkout / "NOTICE.md").is_file():
        fail("gstack's NOTICE.md is gone; review its third-party notices before shipping")
    commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    upstream_version = (checkout / "VERSION").read_text().strip()

    available = {p.parent.name for p in render.glob("*/SKILL.md")}
    if missing := set(EXCLUDED) - available:
        fail(f"excluded skills no longer rendered: {sorted(missing)}")

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(render, OUT / "skills",
                    ignore=lambda d, names: [n for n in names if Path(d) == render and n in EXCLUDED])
    shipped = sorted(p.parent.name for p in (OUT / "skills").glob("*/SKILL.md"))
    if not any(INSTALL_ROOT in p.read_text(errors="replace") for p in (OUT / "skills").rglob("SKILL.md")):
        fail(f"the render does not point at {INSTALL_ROOT}; render with --install-root {INSTALL_ROOT}")

    runtime = OUT / "runtime"
    shutil.copytree(checkout, runtime, symlinks=False,
                    ignore=lambda d, names: [n for n in names
                                             if (Path(d) == checkout and n in RUNTIME_SKIP)
                                             or n.endswith(".bun-build")])
    write_exec(runtime / "browse" / "dist" / "browse", BROWSE_WRAPPER)
    if (runtime / "bin" / "gstack-global-discover.ts").is_file():
        write_exec(runtime / "bin" / "gstack-global-discover", DISCOVER_WRAPPER)

    packages = npm_closure(checkout / "node_modules")
    declared = set(LICENSE_RE.search((HERE / "pyproject.toml").read_text()).group(1).split(" AND "))
    shipped_licenses = {"MIT"} | {p["license"] for p in packages}
    if declared != shipped_licenses:
        fail(f"pyproject.toml license {sorted(declared)} != shipped {sorted(shipped_licenses)}; "
             f"review {[p['name'] for p in packages if p['license'] not in declared]}")
    for p in packages:
        shutil.copytree(checkout / "node_modules" / p["name"], runtime / "node_modules" / p["name"],
                        symlinks=False, ignore=shutil.ignore_patterns(".bin"))

    version = upstream_version + (f".post{post}" if post else "")
    (OUT / "UPSTREAM.json").write_text(json.dumps({
        "repository": "https://github.com/garrytan/gstack",
        "commit": commit,
        "version": upstream_version,
        "license": "MIT",
        "install_root": INSTALL_ROOT,
        "skills": shipped,
        "excluded": EXCLUDED,
        "npm": packages,
    }, indent=2) + "\n")
    (HERE / "src" / "horo_gstack" / "_version.py").write_text(f'__version__ = "{version}"\n')
    print(f"[vendor] ok   horo-gstack {version} from gstack {upstream_version} @ {commit[:12]}: "
          f"{len(shipped)} skills, {len(EXCLUDED)} excluded, {len(packages)} npm packages "
          f"({', '.join(sorted({p['license'] for p in packages}))})")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and not sys.argv[3].isdigit()):
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3] if len(sys.argv) == 4 else None)
