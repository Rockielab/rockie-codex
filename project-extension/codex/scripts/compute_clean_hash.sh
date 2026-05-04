#!/usr/bin/env bash
# Compute the sentinel hash for the current staged fileset.
# Shared between /clean (writes) and pre-commit-gate (reads).
# Hash input: `git ls-files -s` output for staged files only (blob hash + path).
# If the staged set or any blob changes, the hash changes, sentinel invalidates.
set +e
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not a git repo" >&2; exit 1; }

STAGED=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$STAGED" ]; then
  # No staged files; hash over dirty set so /clean --scope dirty still gets a stable key.
  STAGED=$(git diff --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)
fi

# For each file, emit `mode blobhash path`. Files not in index get sha256 of content.
INPUT=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if [ -f "$f" ]; then
    BLOB=$(git hash-object -- "$f" 2>/dev/null)
    INPUT+="100644 $BLOB $f"$'\n'
  fi
done <<< "$STAGED"

if [ -z "$INPUT" ]; then
  echo "no-changes"
  exit 0
fi

echo -n "$INPUT" | shasum -a 256 | awk '{print $1}'
