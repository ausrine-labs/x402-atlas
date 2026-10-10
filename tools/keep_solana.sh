#!/bin/sh
# keep_solana.sh — add the new Solana files to the data branch and push, retrying when another job pushed first.
# Run in a checkout of the data branch. Nothing new is not an error.
set -eu
if [ -d flows/sol-windows ]; then git add flows/sol-windows; fi
for f in flows/flows-sol-*.json; do if [ -f "$f" ]; then git add "$f"; fi; done
if git diff --cached --quiet; then echo "nothing new"; exit 0; fi
git commit -qm "solana: $(git diff --cached --name-only | xargs -n1 basename | tr '\n' ' ')(run ${GITHUB_RUN_ID:-local})"
for i in 1 2 3 4 5; do
  git push -q origin HEAD:data && exit 0
  sleep $((i * 5))
  git pull -q --rebase origin data
done
echo "::error::the Solana files could not be pushed to the data branch"
exit 1
