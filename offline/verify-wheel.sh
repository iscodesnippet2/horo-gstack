#!/usr/bin/env bash
# Runs inside a CentOS-family container with no network, as the target machine
# would: bun from an npm cache, horo-next and the horo-gstack wheel from a
# wheelhouse into a Python 3.12 venv, then `horo-gstack install` and checks
# that the skills load, every preamble runs, browse drives the installed
# Google Chrome, and uninstall removes what install wrote.
#
#   bash offline/verify-wheel.sh <stage> <out>
#
# <stage> holds the horo-gstack wheel, wheelhouse/ and npm-cache/.
set -u
STAGE=$1 OUT=$2
T=$(mktemp -d)
export HOME=$T/home HERMES_HOME=$T/hermes XDG_STATE_HOME=$T/state HERMES_GATEWAY_LOCK_DIR=$T/lock \
  NO_COLOR=1 npm_config_update_notifier=false
unset GSTACK_CHROMIUM_PATH
mkdir -p "$HOME" "$HERMES_HOME" "$OUT/start"
R=$OUT/report.md
: > "$R"

note() { echo "$*" | tee -a "$R"; }
step() {
  local label=$1; shift
  if timeout 180 "$@" > "$T/log" 2>&1; then note "- ok: $label"
  else note "- FAIL: $label (exit $?)"; tail -12 "$T/log" | sed 's/^/      /' | tee -a "$R"; fi
}

note "## Machine"
note "- $(cat /etc/redhat-release), $(ldd --version | head -1), $(python3.12 --version)"
note "- $(google-chrome --version 2>&1), node $(node --version), npm $(npm --version)"
note "- wheel: $(cd "$STAGE" && ls horo_gstack-*.whl) ($(du -h "$STAGE"/horo_gstack-*.whl | cut -f1))"
note ""
note "## Install"
step "network is unreachable" sh -c '! curl -sS --max-time 5 https://pypi.org/ > /dev/null 2>&1'
cp -a "$STAGE/npm-cache" "$T/npm-cache"  # npm writes to its cache even offline
step "npm install -g bun@1.4.2 --offline" \
  npm install -g --prefix "$T/npm" bun@1.4.2 --offline --cache "$T/npm-cache" --no-audit --no-fund
export PATH=$T/npm/bin:$T/venv/bin:$PATH
step "python3.12 venv" python3.12 -m venv "$T/venv"
step "pip install --no-index horo-next==0.21.5 and horo-gstack" \
  pip install -q --no-index --find-links "$STAGE/wheelhouse" horo-next==0.21.5 "$STAGE"/horo_gstack-*.whl
step "horo-gstack install" horo-gstack install
sed 's/^/      /' "$T/log" | tee -a "$R"

M=$HERMES_HOME/gstack/install.json
RUNTIME=$HERMES_HOME/gstack/runtime
UP=$T/upstream.json
"$T/venv/bin/python" -I -c 'import horo_gstack.cli as c, json; print(json.dumps(c.upstream()))' > "$UP"
want=$("$T/venv/bin/python" -I -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["skills"]))' "$UP")
have=$(ls -d "$HERMES_HOME"/skills/gstack*/ 2>/dev/null | wc -l)
step "every shipped skill installed ($have of $want)" test "$have" -eq "$want"
step "no excluded skill installed" "$T/venv/bin/python" -I -c \
  'import json,os,sys; sys.exit(any(os.path.exists(os.path.join(sys.argv[2], n)) for n in json.load(open(sys.argv[1]))["excluded"]))' \
  "$UP" "$HERMES_HOME/skills"
step "no skill still points at /opt/horo-gstack" sh -c "! grep -rl /opt/horo-gstack '$HERMES_HOME/skills'"
step "hermes skills list shows gstack-review" sh -c "hermes skills list | grep -q gstack-review"
step "skill_view('gstack-qa') loads" "$T/venv/bin/python" -I -c \
  "import json,sys; from tools.skills_tool import skill_view; sys.exit(0 if json.loads(skill_view('gstack-qa')).get('success') else 1)"
step "telemetry is off" sh -c "[ \"\$('$RUNTIME/bin/gstack-config' get telemetry)\" = off ]"
step "update_check is off" sh -c "[ \"\$('$RUNTIME/bin/gstack-config' get update_check)\" = false ]"
step "install found Google Chrome" grep -q /opt/google/chrome/chrome "$RUNTIME/browse/.chrome-path"

# A throwaway repository for the preambles and browse to work in.
W=$T/work; mkdir -p "$W" && cd "$W" && git init -q -b main && echo hi > README.md && git add . \
  && git -c user.name=t -c user.email=t@t commit -qm init

note ""
note "## Preamble start, every skill"
fails=0 n=0
for md in "$HERMES_HOME"/skills/*/SKILL.md; do
  skill=$(basename "$(dirname "$md")")
  cmd=$(grep -m1 "^\"$RUNTIME/bin/gstack-skill-start\" " "$md") || continue
  n=$((n + 1))
  timeout 120 bash -c "$cmd" > "$OUT/start/$skill.txt" 2>&1 || { fails=$((fails + 1)); note "- FAIL: $skill start (exit $?)"; }
done
note "- $n skills have a preamble; $fails failed"
step "skill end" "$RUNTIME/bin/gstack-skill-end" --skill review --outcome success --session-id verify \
  --tel-start "$(date +%s)" --used-browse no --error-message "" --failed-step ""

note ""
note "## browse, with the browser install found"
mkdir -p "$T/site"
echo '<!doctype html><title>t</title><h1>HORO-MARKER-42</h1><a href="/n.html">n</a>' > "$T/site/index.html"
(cd "$T/site" && exec python3.12 -m http.server 8765 --bind 127.0.0.1 > /dev/null 2>&1) &
sleep 1
B=$RUNTIME/browse/dist/browse
step "goto" "$B" goto http://127.0.0.1:8765/
step "text" sh -c "'$B' text | grep -q HORO-MARKER-42"
step "screenshot" "$B" screenshot "$W/shot.png"
cp "$W/shot.png" "$OUT/" 2>/dev/null
step "the browser is Google Chrome" sh -c "ps -eo args | grep -v grep | grep -q '^/opt/google/chrome/chrome'"
step "stop" "$B" stop
step "gstack-global-discover runs (retro)" "$RUNTIME/bin/gstack-global-discover" --help

note ""
note "## Status and uninstall"
step "horo-gstack status" horo-gstack status
sed 's/^/      /' "$T/log" | tee -a "$R"
step "horo-gstack uninstall" horo-gstack uninstall
step "uninstall removed the skills, the runtime and the manifest" \
  sh -c "! ls -d '$HERMES_HOME'/skills/gstack* 2>/dev/null && [ ! -e '$RUNTIME' ] && [ ! -e '$M' ]"

! grep -q '^- FAIL' "$R"
