#!/bin/sh
# Убрать служебный .omc/ из репозитория и выложить релиз v0.1.0.
set -e
cd /home/tty-shai/tanto-browser

git rm -r --cached --ignore-unmatch .omc
git add -A
git commit -m "chore: drop .omc session file, add adguard-russian filter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push

git tag v0.1.0
git push origin v0.1.0

echo "=== done ==="
git log --oneline -3
