#!/bin/bash

# Exit the script if any command fails
set -e

echo "🚀 Starting deployment process..."

# 0. Navigate to the 'site' directory
# This fixes the "ENOENT: no such file or directory" error
echo "📂 Entering site directory..."
cd site

# 1. Build the project
# This compiles your code into the 'site/dist' folder
echo "📦 Building the site..."
npm run build

# 2. Deploy to GitHub Pages
# Uses the 'gh-pages' tool to push the 'dist' folder to the 'gh-pages' branch
# 'npx' downloads and runs the tool temporarily if you don't have it installed
echo "📤 Publishing to GitHub..."
npx gh-pages -d dist

echo "✅ Site published successfully!"