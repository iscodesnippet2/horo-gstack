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
                 only what browse needs (Playwright, diff, socks), resolved
                 from package.json files
  runtime/lib/diagram-render/THIRD-PARTY-NOTICES.md
                 the license of every npm package inside gstack's prebuilt
                 diagram-render bundle, which upstream lists only in part; it
                 needs `bun install --frozen-lockfile --ignore-scripts` in
                 <gstack-checkout>/lib/diagram-render
Two compiled binaries upstream builds at setup become bun wrappers, and browse's
screenshot size guard no longer downscales with sharp (a native linux-x64
libvips, LGPL), so nothing here is built for a platform.

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

# browse's server imports these; everything they depend on comes with them.
NPM_ROOTS = ["playwright", "diff", "socks"]

# pyproject.toml's license expression must name exactly MIT plus the npm
# packages' licenses: a new or dropped one stops the build until it is updated.
LICENSE_RE = re.compile(r'^license = "([^"]+)"', re.M)

LICENSE_FILE_RE = re.compile(r"^(licen[cs]e|copying|notice|thirdpartynotices)", re.I)

# Packages in the diagram-render bundle whose npm tarball has no license file,
# with the copyright line from their repository's LICENSE (all MIT).
MIT_WITHOUT_FILE = {
    "@excalidraw/excalidraw": "Copyright (c) 2020 Excalidraw (https://github.com/excalidraw/excalidraw)",
    "@radix-ui/": "Copyright (c) 2022 WorkOS (https://github.com/radix-ui/primitives)",
    "react-remove-scroll-bar": "Copyright (c) Anton Korzunov (https://github.com/theKashey/react-remove-scroll-bar)",
}
# Packages whose package.json has no SPDX license field, read from their license file.
LICENSE_FROM_FILE = {"khroma": "MIT", "fuzzy": "MIT"}

MIT_TEXT = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

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

# browse/src/screenshot-size-guard.ts downscales full-page screenshots longer
# than 2000px with sharp. This keeps its exports but returns the screenshot as
# taken, reading the size from the PNG header only to report it.
GUARD_EXPORTS = ["guardScreenshotBuffer", "guardScreenshotPath", "SCREENSHOT_MAX_DIMENSION_PX"]
SIZE_GUARD = """/**
 * horo-gstack: upstream downscales screenshots longer than 2000px with sharp.
 * horo-gstack ships without sharp, so screenshots go out as taken; the size is
 * read from the PNG header for the diagnostic shape only.
 */

import { readFileSync } from "fs";

const MAX_DIMENSION_PX = 2000;

export interface SizeGuardResult {
  resized: boolean;
  width: number;
  height: number;
  originalWidth: number;
  originalHeight: number;
}

function pngSize(buf: Buffer): { width: number; height: number } {
  const isPng = buf.length >= 24 && buf.readUInt32BE(0) === 0x89504e47 && buf.toString("ascii", 12, 16) === "IHDR";
  return isPng ? { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) } : { width: 0, height: 0 };
}

export async function guardScreenshotBuffer(input: Buffer): Promise<{ buffer: Buffer; result: SizeGuardResult }> {
  const { width, height } = pngSize(input);
  return { buffer: input, result: { resized: false, width, height, originalWidth: width, originalHeight: height } };
}

export async function guardScreenshotPath(filePath: string): Promise<SizeGuardResult> {
  return (await guardScreenshotBuffer(readFileSync(filePath))).result;
}

export const SCREENSHOT_MAX_DIMENSION_PX = MAX_DIMENSION_PX;
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


def license_terms(expr: str) -> set[str]:
    """An SPDX expression as the AND-ed terms pyproject.toml lists: `(MIT AND
    Zlib)` is two terms, `(MPL-2.0 OR Apache-2.0)` stays one."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(expr):
        depth += {"(": 1, ")": -1}.get(c, 0)
        if depth == 0 and expr.startswith(" AND ", i):
            parts.append(expr[start:i])
            start = i + 5
    parts.append(expr[start:])
    terms = set()
    for t in (t.strip() for t in parts):
        if " OR " in t:
            terms.add(t if t.startswith("(") else f"({t})")
        elif t.startswith("("):
            terms |= license_terms(t[1:-1])
        else:
            terms.add(t)
    return terms


def diagram_notices(checkout: Path, runtime: Path) -> list[dict]:
    """Write THIRD-PARTY-NOTICES.md for the packages bundled into
    lib/diagram-render/dist/diagram-render.html and return them."""
    root = checkout / "lib" / "diagram-render"
    info = json.loads((root / "dist" / "BUILD_INFO.json").read_text())
    pinned = json.loads((root / "package.json").read_text())["dependencies"]
    if info["deps"] != pinned:
        fail(f"diagram-render's dist was built from {info['deps']}, package.json pins {pinned}")
    for name, version in pinned.items():
        pj = root / "node_modules" / name / "package.json"
        if not pj.is_file() or json.loads(pj.read_text())["version"] != version:
            fail(f"lib/diagram-render/node_modules/{name} is not {version}; "
                 "run bun install --frozen-lockfile --ignore-scripts there")
    dirs = json.loads(subprocess.run(
        ["bun", "--no-env-file", "run", str(HERE / "tools" / "bundle-sources.ts")],
        cwd=root, capture_output=True, text=True, check=True).stdout)

    packages, sections = [], []
    for d in dirs:
        meta = json.loads((root / d / "package.json").read_text())
        name, version = meta["name"], meta["version"]
        lic = meta.get("license") if isinstance(meta.get("license"), str) else LICENSE_FROM_FILE.get(name)
        if not lic:
            fail(f"diagram-render bundles {name}@{version} with no license field; review it")
        texts = [(f.name, f.read_text(errors="replace").strip())
                 for f in sorted((root / d).iterdir()) if f.is_file() and LICENSE_FILE_RE.match(f.name)]
        if not texts:
            holder = next((v for k, v in MIT_WITHOUT_FILE.items() if name == k or name.startswith(k)), None)
            if lic != "MIT" or not holder:
                fail(f"diagram-render bundles {name}@{version} ({lic}) and its package has no license file")
            texts = [("LICENSE (from the repository; the npm package has none)", f"MIT License\n\n{holder}\n\n{MIT_TEXT}".strip())]
        if any(p["name"] == name and p["version"] == version for p in packages):
            continue
        packages.append({"name": name, "version": version, "license": lic})
        sections.append(f"## {name} {version} ({lic})\n\n" + "\n\n".join(
            f"{fname}:\n\n```\n{text}\n```" for fname, text in texts))

    rows = "\n".join(f"| {p['name']} | {p['version']} | {p['license']} |" for p in packages)
    (runtime / "lib" / "diagram-render" / "THIRD-PARTY-NOTICES.md").write_text(f"""# Third-party notices: diagram-render bundle

Written by horo-gstack's vendor.py. `dist/diagram-render.html` is gstack's
prebuilt single-file page; rebuilding it from the same entry with a source map
names the npm packages below as the ones whose code it contains. Each one's
license text follows the table. The bundle refers to excalidraw's fonts by path
but does not embed them, so no font is distributed here.

| Package | Version | License |
|---|---|---|
{rows}

{chr(10).join(sections)}
""")
    return packages


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
                                             or n == "node_modules"
                                             or n.endswith(".bun-build")])
    write_exec(runtime / "browse" / "dist" / "browse", BROWSE_WRAPPER)
    guard = runtime / "browse" / "src" / "screenshot-size-guard.ts"
    if missing := [e for e in GUARD_EXPORTS if e not in guard.read_text()]:
        fail(f"screenshot-size-guard.ts no longer exports {missing}; review the replacement")
    guard.write_text(SIZE_GUARD)
    if users := [str(p.relative_to(runtime)) for p in (runtime / "browse" / "src").rglob("*.ts")
                 if re.search(r"""(from|import\()\s*['"]sharp['"]""", p.read_text())]:
        fail(f"{users} import sharp, which horo-gstack does not ship")
    if (runtime / "bin" / "gstack-global-discover.ts").is_file():
        write_exec(runtime / "bin" / "gstack-global-discover", DISCOVER_WRAPPER)

    packages = npm_closure(checkout / "node_modules")
    diagram = diagram_notices(checkout, runtime)
    declared = license_terms(LICENSE_RE.search((HERE / "pyproject.toml").read_text()).group(1))
    shipped_licenses = {"MIT"}.union(*(license_terms(p["license"]) for p in packages + diagram))
    if declared != shipped_licenses:
        fail(f"pyproject.toml license {sorted(declared)} != shipped {sorted(shipped_licenses)}; "
             f"review {[p['name'] for p in packages + diagram if not license_terms(p['license']) <= declared]}")
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
        "diagram_render": diagram,
    }, indent=2) + "\n")
    (HERE / "src" / "horo_gstack" / "_version.py").write_text(f'__version__ = "{version}"\n')
    print(f"[vendor] ok   horo-gstack {version} from gstack {upstream_version} @ {commit[:12]}: "
          f"{len(shipped)} skills, {len(EXCLUDED)} excluded, {len(packages)} npm packages for browse, "
          f"{len(diagram)} in the diagram bundle ({', '.join(sorted(shipped_licenses))})")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and not sys.argv[3].isdigit()):
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3] if len(sys.argv) == 4 else None)
