"""What each gstack skill needs at run time, read from a Hermes render.

    python inventory.py <gstack-checkout> <render-dir> <install-root> <out-dir>

The render is `scripts/gen-skill-docs.ts --host hermes --install-root
<install-root>`, so every script a skill runs appears as <install-root>/<path>.
This follows those paths into the checkout, then follows each script to the
other gstack scripts it calls, and reports per skill: the interpreters the
closure needs, the network and outside tools it touches, and its size.

Reads files only; runs nothing from the checkout.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

CHECKOUT, RENDER, ROOT, OUT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].rstrip("/"), Path(sys.argv[4])

ROOT_REF = re.compile(re.escape(ROOT) + r"/([A-Za-z0-9_.\-/]+)")
BIN_NAME = re.compile(r"\bgstack-[a-z0-9-]+(?:\.sh|\.ts|\.py)?\b")
LIB_IMPORT = re.compile(r"""from\s+['"]((?:\.\./)+lib/[^'"]+)['"]""")

# Signals, not proofs: each match is a line a reviewer should read.
NETWORK = {
    "url": re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|example\.)"),
    "curl/wget": re.compile(r"\b(?:curl|wget)\s"),
    "fetch()": re.compile(r"\bfetch\("),
    "git remote": re.compile(r"\bgit\s+(?:push|fetch|pull|clone|ls-remote)\b"),
    "gh": re.compile(r"\bgh\s+(?:api|pr|release|run|issue|repo|auth)\b"),
    "package install": re.compile(r"\b(?:npm|bun|pip3?|uv|brew)\s+(?:install|add|i)\b|\b(?:bunx|npx)\s"),
    "web tools": re.compile(r"\bWeb(?:Search|Fetch)\b"),
}
TOOLS = {
    "browser": re.compile(r"\bplaywright\b|\bchromium\b|browse/dist/browse|\$B\s", re.I),
    "codex": re.compile(r"\bcodex\s+(?:exec|login|review)\b"),
    "gemini": re.compile(r"\bgemini\s+-"),
    "gbrain": re.compile(r"\bgbrain\s+[a-z]"),
    "docker": re.compile(r"\bdocker\s+(?:run|build|compose)\b"),
    "xcode": re.compile(r"\bxcrun\b|\bxcodebuild\b|\bsimctl\b"),
    "supabase": re.compile(r"supabase", re.I),
    "ngrok": re.compile(r"\bngrok\b", re.I),
    "anthropic api": re.compile(r"@anthropic-ai/sdk|api\.anthropic\.com"),
    "telemetry": re.compile(r"gstack-telemetry-log|gstack-update-check"),
}

BIN = CHECKOUT / "bin"
BIN_FILES = {p.name for p in BIN.iterdir() if p.is_file()}


def code_lines(text: str) -> str:
    """Drop whole-line comments, where gstack keeps its long prose."""
    return "\n".join(ln for ln in text.splitlines() if not re.match(r"\s*(?:#|//|\*|/\*)", ln))


def interpreter(path: Path) -> str:
    first = path.read_text(errors="replace").split("\n", 1)[0]
    if "bun" in first:
        return "bun"
    if "python" in first:
        return "python"
    if first.startswith("#!") or "shell=bash" in first or path.suffix == ".sh":
        return "bash"
    if path.suffix == ".ts":
        return "bun"
    return "binary" if b"\0" in path.read_bytes()[:1024] else "data"


def signals(text: str) -> tuple[list[str], list[str]]:
    return ([k for k, rx in NETWORK.items() if rx.search(text)],
            [k for k, rx in TOOLS.items() if rx.search(text)])


script_cache: dict[str, dict] = {}


def script(rel: str) -> dict:
    """One runtime file: its interpreter, signals, and the gstack scripts it calls."""
    if rel in script_cache:
        return script_cache[rel]
    path = CHECKOUT / rel
    info = {"interpreter": "missing", "network": [], "tools": [], "calls": [], "lib": []}
    script_cache[rel] = info
    if path.is_dir():
        info["interpreter"] = "directory"
    elif path.is_file():
        info["interpreter"] = interpreter(path)
        if info["interpreter"] in ("bun", "bash", "python"):
            code = code_lines(path.read_text(errors="replace"))
            info["network"], info["tools"] = signals(code)
            info["calls"] = sorted({f"bin/{m}" for m in BIN_NAME.findall(code) if m in BIN_FILES} - {rel})
            info["lib"] = sorted(set(LIB_IMPORT.findall(code)))
    return info


def closure(start: set[str]) -> list[str]:
    seen, todo = set(), list(start)
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        todo.extend(script(rel)["calls"])
    return sorted(seen)


# Every skill starts and ends through these two; report them once, apart.
PREAMBLE = closure({"bin/gstack-skill-start", "bin/gstack-skill-end"})

skills = []
for skill_md in sorted(RENDER.glob("*/SKILL.md")):
    d = skill_md.parent
    texts = [p.read_text(errors="replace") for p in sorted(d.rglob("*")) if p.is_file()]
    text = "\n".join(texts)
    head = texts and skill_md.read_text(errors="replace")
    name = re.search(r"^name:\s*(.+)$", head, re.M)
    refs = {m.rstrip(".,:;)`'\"") for m in ROOT_REF.findall(text)}
    files = closure(refs)
    extra = [f for f in files if f not in PREAMBLE]
    interp = Counter(script(f)["interpreter"] for f in extra)
    net_text, tools_text = signals(text)
    net_code = sorted({s for f in extra for s in script(f)["network"]})
    tools_code = sorted({s for f in extra for s in script(f)["tools"]})
    skills.append({
        "dir": d.name,
        "name": name.group(1).strip() if name else d.name,
        "bytes": sum(len(t.encode()) for t in texts),
        "direct": sorted(refs),
        "uses_preamble": bool(set(files) & {"bin/gstack-skill-start"}),
        "beyond_preamble": extra,
        "interpreters": dict(interp),
        "needs_bun": interp.get("bun", 0) > 0,
        "missing": [f for f in files if script(f)["interpreter"] == "missing"],
        "network_in_text": net_text,
        "network_in_scripts": net_code,
        "tools": sorted(set(tools_text) | set(tools_code)),
    })

all_files = sorted(set(PREAMBLE) | {f for s in skills for f in s["beyond_preamble"]})
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "inventory.json").write_text(json.dumps({
    "install_root": ROOT,
    "preamble": PREAMBLE,
    "skills": skills,
    "runtime": {f: script(f) for f in all_files},
}, indent=1) + "\n")

lines = [
    f"# gstack Hermes render: {len(skills)} skills, {sum(s['bytes'] for s in skills) // 1024} KiB of skill text",
    "",
    f"Runtime files reached: {len(all_files)} "
    f"({', '.join(f'{k} {v}' for k, v in Counter(script(f)['interpreter'] for f in all_files).most_common())}).",
    f"Shared preamble (`gstack-skill-start`/`-end` and what they call): {len(PREAMBLE)} files, "
    f"{', '.join(f'{k} {v}' for k, v in Counter(script(f)['interpreter'] for f in PREAMBLE).most_common())}; "
    f"used by {sum(s['uses_preamble'] for s in skills)} skills.",
    f"Beyond the preamble: {sum(s['needs_bun'] for s in skills)} skills need bun; "
    f"{sum(not s['network_in_scripts'] and not s['tools'] for s in skills)} have no script network signal and no outside tool.",
    "",
    "Columns after Preamble count only files beyond the shared preamble.",
    "",
    "| Skill | KiB | Preamble | Scripts | bun | Network (scripts) | Network (text) | Tools | Missing |",
    "|---|---:|:-:|---:|:-:|---|---|---|---|",
]
for s in skills:
    lines.append(f"| {s['name']} | {s['bytes'] // 1024} | {'yes' if s['uses_preamble'] else ''} | "
                 f"{len(s['beyond_preamble'])} | {'yes' if s['needs_bun'] else ''} | "
                 f"{', '.join(s['network_in_scripts'])} | {', '.join(s['network_in_text'])} | "
                 f"{', '.join(s['tools'])} | {', '.join(s['missing'])} |")
lines += ["", "## Shared preamble", ""]
for f in PREAMBLE:
    i = script(f)
    lines.append(f"- `{f}` ({i['interpreter']}): network {', '.join(i['network']) or 'none'}; "
                 f"tools {', '.join(i['tools']) or 'none'}")
(OUT / "inventory.md").write_text("\n".join(lines) + "\n")
print(f"[inventory] {len(skills)} skills, {len(all_files)} runtime files -> {OUT}")
