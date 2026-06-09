#!/usr/bin/env bash
# Install repository git hooks.
#
# Installs wrappers in `.git/hooks/` that resolve hook sources from the current
# worktree at runtime. This makes the hooks work from linked worktrees and
# keeps installation idempotent.
set -uo pipefail

case "${OSTYPE:-unknown}" in
  msys*|cygwin*|win32*)
    echo "[install-git-hooks] WARNING: Windows not supported; install hooks manually." >&2
    exit 0
    ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "[install-git-hooks] WARNING: not inside a git repository; skipping." >&2
  exit 0
fi
cd "$REPO_ROOT"

install_hook() {
  local name="$1"
  local source_relpath="$2"
  local hook_source="$REPO_ROOT/$source_relpath"
  local hook_target
  hook_target="$(git rev-parse --git-path "hooks/$name")"

  set +e
  if [ ! -f "$hook_source" ]; then
    echo "[install-git-hooks] WARNING: $name source missing at $hook_source; skipping." >&2
    set -e
    return 0
  fi
  chmod +x "$hook_source" 2>/dev/null
  mkdir -p "$(dirname "$hook_target")" 2>/dev/null

  if [ -e "$hook_target" ] && [ ! -L "$hook_target" ]; then
    local backup="${hook_target}.pre-dev-rules-backup.$(date +%s)"
    if mv "$hook_target" "$backup"; then
      echo "[install-git-hooks] backed up existing $name to $backup"
    else
      echo "[install-git-hooks] WARNING: could not back up $hook_target; skipping." >&2
      set -e
      return 0
    fi
  fi
  if [ -L "$hook_target" ]; then
    rm -f "$hook_target"
  fi

  local tmp_target="${hook_target}.tmp.$$"
  cat >"$tmp_target" <<EOF
#!/usr/bin/env bash
set -euo pipefail
repo_root="\$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "\$repo_root" ]; then
  echo "[dev-rules-$name] WARNING: not inside a git worktree; skipping." >&2
  exit 0
fi
hook_source="\$repo_root/$source_relpath"
if [ ! -x "\$hook_source" ]; then
  echo "[dev-rules-$name] WARNING: hook source not executable at \$hook_source; skipping." >&2
  exit 0
fi
exec "\$hook_source" "\$@"
EOF
  chmod +x "$tmp_target" 2>/dev/null
  if mv "$tmp_target" "$hook_target"; then
    echo "[install-git-hooks] installed: $hook_target -> current-worktree:$source_relpath"
  else
    rm -f "$tmp_target"
    echo "[install-git-hooks] WARNING: failed to install $hook_target." >&2
  fi
  set -e
}

install_hook "pre-commit" "scripts/git-hooks/pre-commit.py"
install_hook "commit-msg" "scripts/git-hooks/commit-msg.py"
install_hook "pre-push" "scripts/git-hooks/pre-push.py"

exit 0
