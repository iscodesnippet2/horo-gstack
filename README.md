# horo-gstack

[gstack](https://github.com/garrytan/gstack) skills and the runtime they run,
packaged so they install on an offline Hermes machine from a pip mirror and an
npm mirror. Unofficial; not affiliated with gstack or its author. gstack is
MIT-licensed by Garry Tan; its license, NOTICE.md and third-party licenses ship
in the wheel, with the license of every npm package browse needs and of every
package inside gstack's prebuilt diagram bundle
(`lib/diagram-render/THIRD-PARTY-NOTICES.md`).

Tested on CentOS / RHEL 8 and 9 (x86-64). The wheel has no native code; bun
and Google Chrome come from the machine.

## Install

```bash
npm install -g bun@1.4.2
pip install horo-gstack
horo-gstack install
```

1. **bun** from the npm mirror; the mirror must also carry
   `@oven/bun-linux-x64` (or `-baseline` on CPUs without AVX2), which holds the
   binary. Most skills run bun scripts.
2. **pip install** in the venv that has horo-next (Python 3.11 to 3.13).
3. **`horo-gstack install`** copies the runtime to `$HERMES_HOME/gstack/runtime`
   and the skills to `$HERMES_HOME/skills/gstack-*`, pointing them at that
   runtime. It finds Google Chrome for browse (`--chrome PATH` to choose), and
   turns gstack's telemetry, update check and auto-upgrade off. Run it again
   after `pip install -U horo-gstack`.

Then `hermes chat -s gstack-review`, or ask the agent to load a `gstack-*` skill.

`horo-gstack status` shows what is installed; `horo-gstack uninstall` removes
what install wrote (gstack's own state in `~/.gstack` stays).

### What to expect

- Skills are long and run many tool calls: a `gstack-review` took about 30
  minutes and 125 tool calls on MiniMax-M3.1-Flash.
- `gstack-review` and `gstack-qa` fix what they find in your working tree.
  `gstack-office-hours` searches the web when Hermes has web tools.
- browse screenshots go to the model as taken. Upstream shrinks full-page
  screenshots longer than 2000px with sharp, which horo-gstack leaves out (its
  libvips is native and LGPL); a model with a smaller image limit may reject a
  long page's full screenshot, so use `screenshot --viewport` for those.
- browse drives the installed Google Chrome headless. It needs Chrome's
  sandbox (unprivileged user namespaces), or `GSTACK_CHROMIUM_NO_SANDBOX=1`
  for trusted pages only.

## What is left out

Skills that need a service, a tool or a build an offline CentOS machine does
not have: gbrain, ngrok pairing, Ubicloud, self-upgrade from GitHub, the
Codex / Claude Code / multi-model CLIs, the Anthropic API, iOS (Xcode), the
headed browser with gstack's extension, make-pdf and cso. `vendor.py` lists
each reason, and every wheel records its list in
`horo_gstack/_vendor/UPSTREAM.json`.

## How this repository is laid out

gstack content is never committed here. A release is a pure function of
(gstack commit, this repository).

| Path | What it does |
|---|---|
| `vendor.py` | Copies gstack's Hermes render (minus the excluded skills), its runtime, and the npm packages browse needs into the package. Replaces two compiled binaries with bun wrappers. Fails if a license or the excluded list no longer matches |
| `src/horo_gstack/cli.py` | `horo-gstack install / uninstall / status` |
| `sbom.py` | CycloneDX SBOM naming the gstack commit and every npm package, embedded in the wheel |
| `offline/verify-wheel.sh` | Installs the wheel with no network on Rocky 8 and CentOS Stream 9 with Google Chrome, runs every preamble and browse, then uninstalls |
| `.github/workflows/release.yml` | Commit → render → vendor → wheel → verify → TestPyPI → PyPI |
| `inventory.py`, `.github/workflows/inventory.yml` | Reports what each rendered skill needs at run time |
| `.github/workflows/offline.yml`, `browse-centos.yml` | The feasibility tests behind this packaging |

## Releasing

Run the **release** workflow with a full gstack commit SHA. Leave `post` blank
for a new gstack version; set it to 1, 2, ... when only this repository
changed. With `publish` off it builds and verifies only.

Not yet covered by CI: CentOS 8's own 4.18 kernel (containers use the
runner's), and a full skill run with a model while offline.
