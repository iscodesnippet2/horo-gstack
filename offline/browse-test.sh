#!/usr/bin/env bash
# Runs inside a CentOS-family container with no network: installs bun from an
# npm cache, then drives the installed Google Chrome through gstack's browse
# against a page served on loopback, once per browse client.
#
#   bash offline/browse-test.sh <stage> <out>
#
# <stage> holds runtime/ (gstack with its node_modules) and npm-cache/.
set -u
STAGE=$1 OUT=$2
T=$(mktemp -d)
export HOME=$T/home GSTACK_HOME=$T/gstack-state NO_COLOR=1 npm_config_update_notifier=false
mkdir -p "$HOME" "$OUT/shots"
R=$OUT/report.md
: > "$R"

note() { echo "$*" | tee -a "$R"; }
step() {
  local label=$1; shift
  if timeout 180 "$@" > "$T/log" 2>&1; then note "- ok: $label"
  else note "- FAIL: $label (exit $?)"; tail -12 "$T/log" | sed 's/^/      /' | tee -a "$R"; fi
}

note "## Machine"
note "- $(cat /etc/redhat-release), kernel $(uname -r), $(ldd --version | head -1)"
note "- $(google-chrome --version 2>&1), node $(node --version), npm $(npm --version)"
note ""
note "## Install"
step "network is unreachable" sh -c '! curl -sS --max-time 5 https://registry.npmjs.org/ > /dev/null 2>&1'
# npm writes to its cache even when offline, and /stage is read-only.
cp -a "$STAGE/npm-cache" "$T/npm-cache"
step "npm install -g bun@1.4.2 from the cache, --offline" \
  npm install -g --prefix "$T/npm" bun@1.4.2 --offline --cache "$T/npm-cache" --no-audit --no-fund
export PATH=$T/npm/bin:$PATH
note "- bun: $(bun --version 2>&1 | head -1)"
cp -a "$STAGE/runtime" "$T/gstack"
note "- Playwright's own browsers present: $([ -d "$HOME/.cache/ms-playwright" ] && echo yes || echo no)"

# A page with a marker in its text, a console message and a link.
mkdir -p "$T/site"
cat > "$T/site/index.html" <<'EOF'
<!doctype html><title>horo browse test</title>
<h1>HORO-MARKER-42</h1><a href="/next.html">next page</a>
<script>console.log("horo console hello")</script>
EOF
echo '<!doctype html><title>next</title><p>second page</p>' > "$T/site/next.html"
python3 -m http.server 8765 --bind 127.0.0.1 --directory "$T/site" > /dev/null 2>&1 &
sleep 1

export GSTACK_CHROMIUM_PATH=/opt/google/chrome/chrome
W=$T/work; mkdir -p "$W" && cd "$W"
for client in browse browse-wrapper; do
  B=$T/gstack/browse/dist/$client
  note ""
  note "## Client: $client (GSTACK_CHROMIUM_PATH=$GSTACK_CHROMIUM_PATH)"
  step "goto the loopback page" "$B" goto http://127.0.0.1:8765/
  step "text has the marker" sh -c "'$B' text | grep -q HORO-MARKER-42"
  step "console has the page's log" sh -c "'$B' console | grep -q 'horo console hello'"
  step "links lists the link" sh -c "'$B' links | grep -q next.html"
  step "screenshot" "$B" screenshot "$W/$client.png"
  cp "$W/$client.png" "$OUT/shots/" 2>/dev/null
  step "the browser is Google Chrome" sh -c "ps -eo args | grep -v grep | grep -q '^/opt/google/chrome/chrome'"
  step "stop" "$B" stop
  sleep 1
done

note ""
note "## Sandbox"
note "- user namespaces: $(cat /proc/sys/user/max_user_namespaces 2>/dev/null)"
grep -rhoiE 'no-sandbox|sandbox[^"]{0,80}' "$T" --include='*.log' 2>/dev/null | sort -u | head -5 | sed 's/^/      /' | tee -a "$R"

# Daemon logs and state, for anything that failed above.
find "$W" "$HOME" "$GSTACK_HOME" -name '*.log' -o -name '*.json' 2>/dev/null | head -40 \
  | while read -r f; do mkdir -p "$OUT/state$(dirname "$f")" && cp "$f" "$OUT/state$f"; done

! grep -q '^- FAIL' "$R"
