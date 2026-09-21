#!/usr/bin/env bash
# Bootstrap a fresh git worktree with the gitignored files it needs.
#
# Run this from inside a newly created worktree (never from the main
# checkout). It copies files that are gitignored — and therefore absent
# from a fresh worktree — from the main checkout, without ever
# overwriting a file that already exists.
#
# It does NOT touch the Docker stack: there is exactly one stack, owned
# by the main checkout (see the reminder printed below).
set -euo pipefail

resolve() {
  (cd "$1" && pwd -P)
}

git_dir="$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" || {
  echo "error: not inside a git repository" >&2
  exit 1
}
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
git_dir="$(resolve "$git_dir")"
common_dir="$(resolve "$common_dir")"

if [ "$git_dir" = "$common_dir" ]; then
  echo "error: this is the main checkout, not a worktree — bootstrap-worktree.sh is only for worktrees." >&2
  exit 1
fi

main_root="$(dirname "$common_dir")"
worktree_root="$(resolve "$(git rev-parse --show-toplevel)")"

if [ "$main_root" = "$worktree_root" ] || [ ! -d "$main_root/.git" ]; then
  echo "error: could not locate the main checkout (resolved '$main_root')" >&2
  exit 1
fi

echo "Main checkout: $main_root"
echo "This worktree: $worktree_root"
echo

copy_if_present() {
  local rel_path="$1" note_if_missing="${2:-}"
  local src="$main_root/$rel_path" dest="$worktree_root/$rel_path"

  if [ -e "$dest" ]; then
    echo "skip: $rel_path (already present, never overwritten)"
  elif [ ! -e "$src" ]; then
    echo "skip: $rel_path (not in main checkout${note_if_missing:+ — $note_if_missing})"
  else
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    echo "copied: $rel_path"
  fi
}

copy_if_present "mobile/.env"
copy_if_present "mobile/google-services.json" "download from Firebase Console; iOS builds don't need it"

cat <<'EOF'

.watchmanconfig is tracked in git — nothing to copy for it.

Reminder — one Docker stack, owned by the main checkout:
  docker-compose.yml pins a fixed project name, a shared pgdata volume, and
  fixed ports (8000/5432/6379/4566). Running compose (or scripts/dev.sh)
  from a worktree would silently hijack the main checkout's containers
  instead of creating an isolated stack. Worktrees are for editing and
  running checks (ruff/pyright/pytest); run the stack from the main
  checkout only.

Not copied: infra/cdk/.env — CDK checks are being retired. If you stage an
infra/cdk/ change before that lands, `cdk synth` will fail with "Missing
required env var DOMAIN_NAME"; copy it from the main checkout manually.

The pre-commit hook's checks cache (.git/hooks-cache/) is per-worktree, so
your first commit here will cold-run every check.
EOF
