#!/usr/bin/env bash
set -euo pipefail

repo="${1:-kajalbiju/LogLlama}"
branch="${2:-main}"

gh api \
  -X PUT \
  "repos/${repo}/branches/${branch}/protection" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=sdk-tests' \
  -F 'enforce_admins=true' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null' \
  -F 'required_linear_history=true' \
  -F 'allow_force_pushes=false' \
  -F 'allow_deletions=false' \
  -F 'block_creations=false' \
  -F 'required_conversation_resolution=true' \
  -F 'lock_branch=false' \
  -F 'allow_fork_syncing=true'
