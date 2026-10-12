#!/usr/bin/env bash
# Publish staged data without moving main.
#
# Vercel clones every main push before it can skip a data-only build. A cache
# commit is large enough that GitHub answers 403, and Vercel then emails a
# failed production deploy. The site reads these JSON files from the live-data
# branch, which does not create a deployment.
set -euo pipefail

BRANCH="live-data"
MESSAGE="${1:-}"

overlay_published_data() {
  git fetch origin "$BRANCH" || true
  if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
    git checkout "origin/$BRANCH" -- data web/public/api
  fi
}

publish_to_current_branch() {
  # live-data is created only after the reader deploy is live. Until then,
  # production still reads main, so the data has to land there too.
  local branch attempt
  branch="${GITHUB_REF_NAME:-}"
  if [ -z "$branch" ] || [ "$branch" = "live-data" ]; then
    branch="$(git rev-parse --abbrev-ref HEAD)"
  fi
  if [ "$branch" = "HEAD" ]; then
    echo "Detached HEAD; cannot publish." >&2
    exit 1
  fi
  if git diff --cached --quiet; then
    echo "No changes to publish."
    exit 0
  fi
  git commit -m "$MESSAGE"
  for attempt in 1 2 3; do
    git fetch origin "$branch"
    git rebase -X theirs --autostash "origin/$branch"
    if git push origin "HEAD:$branch"; then
      echo "Published to $branch until $BRANCH exists."
      exit 0
    fi
    echo "Push rejected; retrying on $branch (attempt $attempt/3)."
    sleep $((attempt * 5))
  done
  echo "Failed to publish to $branch." >&2
  exit 1
}

publish_index() {
  if [ -z "$MESSAGE" ]; then
    echo "Commit message required." >&2
    exit 1
  fi
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git fetch origin "$BRANCH" || true
  if ! git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
    publish_to_current_branch
  fi
  local parent tree parent_tree commit attempt
  parent="$(git rev-parse "origin/$BRANCH")"
  tree="$(git write-tree)"
  parent_tree="$(git rev-parse "$parent^{tree}")"
  if [ "$tree" = "$parent_tree" ]; then
    echo "No live-data changes."
    exit 0
  fi
  for attempt in 1 2 3; do
    commit="$(git commit-tree "$tree" -p "$parent" -m "$MESSAGE")"
    if git push origin "$commit:refs/heads/$BRANCH"; then
      echo "Published $commit to $BRANCH."
      exit 0
    fi
    echo "Push rejected; retrying on the latest $BRANCH (attempt $attempt/3)."
    sleep $((attempt * 5))
    git fetch origin "$BRANCH"
    parent="$(git rev-parse "origin/$BRANCH")"
  done
  echo "Failed to publish to $BRANCH." >&2
  exit 1
}

case "${1:-}" in
  --overlay)
    overlay_published_data
    ;;
  "")
    echo "Usage: publish_live_data.sh --overlay | publish_live_data.sh \"commit message\"" >&2
    exit 1
    ;;
  *)
    publish_index
    ;;
esac
