#!/usr/bin/env bash
# Runs with no network, as a pip/npm-mirror-only machine would: installs bun
# from an npm cache and horo-next from a wheelhouse, puts the Hermes render in
# HERMES_HOME, then runs every skill's gstack preamble with bun and without.
#
#   bash offline/test.sh <stage> <out>
#
# <stage> holds npm-cache/, wheelhouse/ and render/ from the prepare job; the
# gstack runtime is already at /opt/horo-gstack, the render's install root.
set -u
STAGE=$(cd "$1" && pwd) OUT=$2 ROOT=/opt/horo-gstack
T=$(mktemp -d)
export HOME=$T/home HERMES_HOME=$T/hermes XDG_STATE_HOME=$T/state HERMES_GATEWAY_LOCK_DIR=$T/lock \
  GSTACK_HOME=$T/gstack-state NO_COLOR=1 npm_config_update_notifier=false
mkdir -p "$HOME" "$HERMES_HOME/skills" "$OUT/start"
OUT=$(cd "$OUT" && pwd) R=$OUT/report.md
: > "$R"
BASE_PATH=$PATH

note() { echo "$*" | tee -a "$R"; }
step() {
  local label=$1; shift
  if "$@" > "$T/log" 2>&1; then note "- ok: $label"
  else note "- FAIL: $label (exit $?)"; tail -8 "$T/log" | sed 's/^/      /' | tee -a "$R"; fi
}

note "# Offline run"
note ""
note "## Install"
step "network is unreachable" sh -c '! curl -sS --max-time 5 https://registry.npmjs.org/ > /dev/null 2>&1'

step "npm install -g bun@1.4.2 from the cache, --offline" \
  npm install -g --prefix "$T/npm" bun@1.4.2 --offline --cache "$STAGE/npm-cache" --no-audit --no-fund
step "bun --version (postinstall linked the binary)" "$T/npm/bin/bun" --version
note "      bun: $("$T/npm/bin/bun" --version 2>&1 | head -1)"

step "npm install -g bun@1.4.2 --offline --ignore-scripts" \
  npm install -g --prefix "$T/npm-noscripts" bun@1.4.2 --offline --ignore-scripts --cache "$STAGE/npm-cache" --no-audit --no-fund
step "with --ignore-scripts, bun on PATH still runs" "$T/npm-noscripts/bin/bun" --version
step "with --ignore-scripts, the platform package's binary runs" \
  "$T/npm-noscripts/lib/node_modules/bun/node_modules/@oven/bun-linux-x64/bin/bun" --version

step "venv" python3 -m venv "$T/venv"
step "pip install horo-next==0.21.5 --no-index" \
  "$T/venv/bin/pip" install -q --no-index --find-links "$STAGE/wheelhouse" horo-next==0.21.5
cp -a "$STAGE/render/.hermes/skills/." "$HERMES_HOME/skills/"
note "- skills copied into HERMES_HOME: $(ls "$HERMES_HOME/skills" | wc -l)"
step "hermes skills list shows gstack-review" sh -c "'$T/venv/bin/hermes' skills list | grep -q gstack-review"
step "skill_view('gstack-review') loads" "$T/venv/bin/python" -I -c \
  "import json,sys; from tools.skills_tool import skill_view; sys.exit(0 if json.loads(skill_view('gstack-review')).get('success') else 1)"

# A throwaway repository for the preambles to look at.
W=$T/work; mkdir -p "$W" && cd "$W" && git init -q -b main && echo hi > README.md && git add . \
  && git -c user.name=t -c user.email=t@t commit -qm init

run_starts() {  # <label> <PATH>
  local label=$1 path=$2 skill cmd t0 rc secs proto netfail nobun
  note ""
  note "## Preamble start, $label"
  note ""
  note "| Skill | Exit | Seconds | SKILL_START_PROTO | Network errors | bun missing | Lines |"
  note "|---|---:|---:|---|:-:|:-:|---:|"
  for md in "$HERMES_HOME"/skills/*/SKILL.md; do
    skill=$(basename "$(dirname "$md")")
    cmd=$(grep -m1 "^\"$ROOT/bin/gstack-skill-start\" " "$md") || continue
    t0=$(date +%s.%N)
    PATH=$path timeout 120 bash -c "$cmd" > "$OUT/start/$skill.$label.txt" 2>&1
    rc=$?
    secs=$(echo "$(date +%s.%N) - $t0" | bc | xargs printf '%.1f')
    proto=$(grep -m1 -o 'SKILL_START_PROTO: *[^ ]*' "$OUT/start/$skill.$label.txt" | sed 's/.*: *//')
    netfail=$(grep -qiE 'could not resolve|ENOTFOUND|network is unreachable|ConnectionRefused|getaddrinfo|curl: \(' \
      "$OUT/start/$skill.$label.txt" && echo yes)
    nobun=$(grep -qE 'bun: (command )?not found|env: .?bun.?: No such file' "$OUT/start/$skill.$label.txt" && echo yes)
    note "| $skill | $rc | $secs | ${proto:-none} | $netfail | $nobun | $(wc -l < "$OUT/start/$skill.$label.txt") |"
  done
}

run_starts with-bun "$T/npm/bin:$BASE_PATH"
run_starts without-bun "$BASE_PATH"

note ""
note "## Preamble end"
for label_path in "with-bun:$T/npm/bin:$BASE_PATH" "without-bun:$BASE_PATH"; do
  label=${label_path%%:*}
  PATH=${label_path#*:} timeout 120 "$ROOT/bin/gstack-skill-end" --skill review --outcome success \
    --session-id offline-test --tel-start "$(date +%s)" --used-browse no --error-message "" --failed-step "" \
    > "$OUT/start/_end.$label.txt" 2>&1
  note "- $label: exit $?, $(wc -l < "$OUT/start/_end.$label.txt") lines"
done

note ""
note "## State written"
note "- GSTACK_HOME files: $(find "$GSTACK_HOME" -type f 2>/dev/null | wc -l)"
find "$GSTACK_HOME" -type f 2>/dev/null | sed "s|$GSTACK_HOME/|      |" | head -40 | tee -a "$R"
note "- /home/runner/.gstack exists afterwards: $([ -e /home/runner/.gstack ] && echo yes || echo no)"
