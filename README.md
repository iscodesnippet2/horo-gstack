# horo-gstack

Prototype. Working out whether [gstack](https://github.com/garrytan/gstack)
can ship as a pip package for offline Hermes installs, the way
[horo-pstack](https://github.com/iscodesnippet2/horo-pstack) ships pstack.
Unofficial; not affiliated with gstack or its author. gstack is MIT-licensed
by Garry Tan.

Unlike pstack, gstack skills are not text only: each one runs gstack's own
bash and bun scripts, and some reach the network or outside tools. The
**inventory** workflow renders one gstack commit for Hermes (gstack's own
`--host hermes`) and reports, per skill, what it needs at run time. That
report decides what horo-gstack can ship.

| Path | What it does |
|---|---|
| `.github/workflows/inventory.yml` | Renders a gstack commit for Hermes on Actions and uploads the render and the report |
| `inventory.py` | Reads the render and the checkout and writes `inventory.md` / `inventory.json`; runs nothing from gstack |
