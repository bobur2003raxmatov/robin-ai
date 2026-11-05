#!/bin/bash
# ROBIN bootstrap on PythonAnywhere (run as a scheduled task). Output → ~/robin_seed/boot.log
set -x
export PIP_NO_CACHE_DIR=1
cd "$HOME"
SEED="$HOME/robin_seed"
echo "=== START $(date -u)"
df -h "$HOME" 2>/dev/null | tail -1
du -sh "$HOME" 2>/dev/null

if [ ! -d "$HOME/robin/.git" ]; then
  git clone -b main "${ROBIN_REPO:-$SEED/robin.bundle}" "$HOME/robin" || { echo "=== FAIL clone"; exit 1; }
fi
cd "$HOME/robin"
git remote set-url origin https://github.com/bobur2003raxmatov/robin-ai.git
git config pull.ff only
git config credential.helper store
git log -1 --oneline

[ -f .env ] || cp "$SEED/.env" .env
mkdir -p database
[ -f database/robin.db ] || cp "$SEED/robin.db" database/robin.db

# reuse PythonAnywhere's preinstalled pandas/numpy/Pillow/... (512 MB disk on the free plan)
if [ ! -f .venv/.system_site ]; then
  rm -rf .venv
  python3.13 -m venv --system-site-packages .venv || { echo "=== FAIL venv"; exit 1; }
  touch .venv/.system_site
fi
.venv/bin/python -c "import pandas, numpy; print('system pandas', pandas.__version__, 'numpy', numpy.__version__)"
.venv/bin/pip install -q -r requirements-server.txt || { echo "=== FAIL pip"; exit 1; }
.venv/bin/python -c "import backend.main; print('IMPORT OK')" || { echo "=== FAIL import"; exit 1; }
du -sh "$HOME/robin/.venv" "$HOME" 2>/dev/null
echo "=== DONE $(date -u)"
