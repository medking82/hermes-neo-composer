#!/bin/sh
# Install or update Neo Suggest as a systemd --user service from GitHub.
#   sh deploy/install.sh            (run as the service user, e.g. marck on GA401)
# Idempotent: fast-forwards the checkout, keeps ~/.config/neo-suggest/env, restarts, then smoke-tests.
set -eu
REPO=${NEO_REPO:-https://github.com/medking82/hermes-neo-composer.git}
BRANCH=${NEO_BRANCH:-v0.5-durable}
DIR=$HOME/services/neo-suggest
CFG=$HOME/.config/neo-suggest
UNIT_DIR=$HOME/.config/systemd/user

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" merge -q --ff-only "origin/$BRANCH"
  # sh may have read an older copy of this script; continue with the pulled one.
  if [ -z "${NEO_REEXEC:-}" ]; then NEO_REEXEC=1 NEO_BRANCH="$BRANCH" exec sh "$DIR/deploy/install.sh"; fi
else
  git clone -q --branch "$BRANCH" "$REPO" "$DIR"
fi

mkdir -p "$CFG" "$UNIT_DIR"
if [ ! -f "$CFG/env" ]; then
  cat > "$CFG/env" <<'EOF'
# Neo Suggest settings (see service/neo_suggest.py). Loopback only; reach it via SSH tunnel.
NEO_BIND=127.0.0.1:3460
NEO_UPSTREAM=http://127.0.0.1:3425/v1
NEO_MODELS=group/hestia
EOF
  chmod 600 "$CFG/env"
fi

install -m 644 "$DIR/deploy/neo-suggest.service" "$UNIT_DIR/neo-suggest.service"
install -m 644 "$DIR/deploy/neo-suggest-compat.service" "$UNIT_DIR/neo-suggest-compat.service"
install -m 644 "$DIR/deploy/neo-suggest-compat.timer" "$UNIT_DIR/neo-suggest-compat.timer"
systemd-analyze --user verify "$UNIT_DIR/neo-suggest.service" "$UNIT_DIR/neo-suggest-compat.service" "$UNIT_DIR/neo-suggest-compat.timer"
systemctl --user daemon-reload
systemctl --user enable --now -q neo-suggest-compat.timer
systemctl --user enable -q neo-suggest.service
systemctl --user restart neo-suggest.service

i=0
until curl -fsS -m 2 http://127.0.0.1:3460/healthz >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -ge 20 ] && { journalctl --user -u neo-suggest -n 30 --no-pager; exit 1; }
  sleep 0.5
done
echo "installed $(git -C "$DIR" rev-parse --short HEAD)"
python3 -I "$DIR/compat/smoke.py" --service http://127.0.0.1:3460 ${NEO_SMOKE_LIVE:+--live}

# Optional host adapter (strict steer + images). Opt-in: NEO_HERMES_ROOT=/path/to/hermes-agent.
# Structure-checked (never version-gated); refuses ambiguous trees; backs up to $ROOT/.neo-backups.
# Undo: python3 host-adapter/neo_host_adapter.py rollback --root "$NEO_HERMES_ROOT"
if [ -n "${NEO_HERMES_ROOT:-}" ]; then
  python3 "$DIR/host-adapter/neo_host_adapter.py" install --root "$NEO_HERMES_ROOT" --frontend "${NEO_HOST_FRONTEND:-auto}"     || echo "host adapter refused: plugin keeps working, strict steer stays disabled" >&2
fi
