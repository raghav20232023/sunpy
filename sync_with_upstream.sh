#!/bin/bash

# This script assumes you're in a cloned sunpy repository

# Exit immediately if any command fails
set -e

# Add upstream remote if it doesn't exist
if ! git remote | grep -q upstream; then
  echo "Adding upstream remote..."
  git remote add upstream https://github.com/sunpy/sunpy.git
else
  echo "Upstream remote already exists."
fi

# Fetch latest changes from upstream
echo "Fetching upstream..."
git fetch upstream --tags

# Switch to main branch
echo "Checking out main branch..."
git checkout main

# Merge changes from upstream/main
echo "Merging upstream/main into your local main..."
git merge upstream/main

# Push the updated main branch to your GitHub fork
echo "Pushing changes to your fork (origin)..."
git push origin main

echo "✅ Sync complete!"
