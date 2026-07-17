#!/usr/bin/env bash
# Vercel Ignored Build Step: exit 0 = skip build, exit 1 = proceed.
# Cache refresh commits only touch public/api (and repo paths outside web/).
# Rebuilding the Vite app every refresh is unnecessary and has wiped login
# when a build ran without VITE_SUPABASE_*.
set -euo pipefail

if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then
  echo "No parent commit; building."
  exit 1
fi

if git diff --quiet HEAD^ HEAD -- . ':!public/api' ':!public/api/**'; then
  echo "Only public/api (or no web app) changes; skipping Vite rebuild."
  exit 0
fi

echo "Web app source changed; building."
exit 1
