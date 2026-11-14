"""horo-gstack: put the vendored gstack skills and runtime into a Hermes home.

    horo-gstack install   [--hermes-home DIR] [--chrome PATH] [--force]
    horo-gstack uninstall [--hermes-home DIR]
    horo-gstack status    [--hermes-home DIR]

gstack's skills run its scripts by absolute path, so they cannot load from
site-packages the way a plugin's text-only skills do. install copies the
runtime to <hermes-home>/gstack/runtime, copies each skill to
<hermes-home>/skills/<name> with the render's install root rewritten to that
runtime, and records what it wrote in <hermes-home>/gstack/install.json so
uninstall removes exactly that. gstack's own state (~/.gstack) is left alone,
except that install turns telemetry, update checks and auto-upgrade off.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from horo_gstack._version import __version__

VENDOR = Path(__file__).parent / "_vendor"
BUN_TESTED = "1.4.2"
CHROME_CANDIDATES = ["/opt/google/chrome/chrome", "/usr/bin/google-chrome-stable", "/usr/bin/google-chrome",
                     "/usr/bin/chromium-browser", "/usr/bin/chromium"]
# Privacy defaults for an offline install; gstack-config keeps them in ~/.gstack.
GSTACK_CONFIG = {"telemetry": "off", "update_check": "false", "auto_upgrade": "false"}


def hermes_home(arg):
    return Path(arg or os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()


def upstream():
    return json.loads((VENDOR / "UPSTREAM.json").read_text())


def manifest_path(home):
    return home / "gstack" / "install.json"


def find_bun():
    bun = shutil.which("bun")
    if not bun:
        return None, None
    r = subprocess.run([bun, "--version"], capture_output=True, text=True)
    return bun, (r.stdout.strip() if r.returncode == 0 else None)


def find_chrome(arg):
    for c in [arg, os.environ.get("GSTACK_CHROMIUM_PATH"), *CHROME_CANDIDATES]:
        if c and os.access(c, os.X_OK) and Path(c).is_file():
            return str(Path(c).resolve())
    return None


def make_executable(root):
    """Restore the exec bit on scripts and binaries; a wheel does not always keep it."""
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            with p.open("rb") as f:
                head = f.read(4)
            if head[:2] == b"#!" or head == b"\x7fELF":
                p.chmod(p.stat().st_mode | 0o111)


def remove(home, manifest):
    for name in manifest["skills"]:
        shutil.rmtree(home / "skills" / name, ignore_errors=True)
    shutil.rmtree(manifest["runtime"], ignore_errors=True)
    manifest_path(home).unlink(missing_ok=True)


def install(args):
    home = hermes_home(args.hermes_home)
    up = upstream()
    runtime = home / "gstack" / "runtime"
    mpath = manifest_path(home)
    if mpath.exists():
        remove(home, json.loads(mpath.read_text()))  # reinstall or upgrade
    clashes = [n for n in up["skills"] if (home / "skills" / n).exists()]
    if (clashes or runtime.exists()) and not args.force:
        sys.exit(f"horo-gstack: not installed by horo-gstack, left alone: "
                 f"{', '.join(clashes) or runtime}. Rerun with --force to replace.")

    shutil.rmtree(runtime, ignore_errors=True)
    shutil.copytree(VENDOR / "runtime", runtime)
    make_executable(runtime)
    for name in up["skills"]:
        dest = home / "skills" / name
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(VENDOR / "skills" / name, dest)
        for p in dest.rglob("*"):
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if up["install_root"] in text:
                    p.write_text(text.replace(up["install_root"], str(runtime)), encoding="utf-8")

    chrome = find_chrome(args.chrome)
    if chrome:
        (runtime / "browse" / ".chrome-path").write_text(chrome + "\n")

    config = {}
    for key, value in GSTACK_CONFIG.items():
        r = subprocess.run([str(runtime / "bin" / "gstack-config"), "set", key, value],
                           capture_output=True, text=True)
        config[key] = value if r.returncode == 0 else f"not set: {(r.stderr or r.stdout).strip()[-200:]}"

    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps({"version": __version__, "gstack_commit": up["commit"], "runtime": str(runtime),
                                 "skills": up["skills"], "chrome": chrome}, indent=2) + "\n")

    bun, bun_version = find_bun()
    print(f"horo-gstack {__version__} (gstack {up['version']} @ {up['commit'][:12]})")
    print(f"  skills:  {len(up['skills'])} in {home / 'skills'}")
    print(f"  runtime: {runtime}")
    print(f"  config:  {', '.join(f'{k}={v}' for k, v in config.items())}")
    print(f"  chrome:  {chrome or 'not found; browse skills need --chrome PATH or GSTACK_CHROMIUM_PATH'}")
    if not bun:
        print(f"  bun:     not on PATH. Most skills run bun scripts: npm install -g bun@{BUN_TESTED}")
    elif bun_version != BUN_TESTED:
        print(f"  bun:     {bun} is {bun_version}; gstack is tested with {BUN_TESTED}")
    else:
        print(f"  bun:     {bun} ({bun_version})")


def uninstall(args):
    home = hermes_home(args.hermes_home)
    mpath = manifest_path(home)
    if not mpath.exists():
        sys.exit(f"horo-gstack: nothing installed in {home}")
    m = json.loads(mpath.read_text())
    remove(home, m)
    print(f"horo-gstack: removed {len(m['skills'])} skills and {m['runtime']}")


def status(args):
    home = hermes_home(args.hermes_home)
    mpath = manifest_path(home)
    bun, bun_version = find_bun()
    print(f"package:   horo-gstack {__version__}")
    if mpath.exists():
        m = json.loads(mpath.read_text())
        print(f"installed: {m['version']} in {home}, {len(m['skills'])} skills, chrome {m['chrome']}")
        if m["version"] != __version__:
            print("           differs from the package; run `horo-gstack install` again")
    else:
        print(f"installed: no ({home})")
    print(f"bun:       {bun or 'not on PATH'}{f' ({bun_version})' if bun else ''}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="horo-gstack", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("install", install), ("uninstall", uninstall), ("status", status)]:
        s = sub.add_parser(name)
        s.add_argument("--hermes-home", help="default: $HERMES_HOME, else ~/.hermes")
        if name == "install":
            s.add_argument("--chrome", help="Chrome or Chromium binary for browse (default: search)")
            s.add_argument("--force", action="store_true", help="replace skills or a runtime not installed by horo-gstack")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
