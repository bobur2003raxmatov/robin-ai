#!/bin/bash
# PythonAnywhere: sayt buyrug'i →  /bin/bash /home/<user>/robin/deploy/pa_start.sh ${DOMAIN_SOCKET}
# PythonAnywhere website command: first start runs the bootstrap, then serves ROBIN on the domain socket.
SOCK="$1"
# free accounts reach the internet only through the PythonAnywhere proxy
export http_proxy=http://proxy.server:3128 https_proxy=http://proxy.server:3128 HTTP_PROXY=http://proxy.server:3128 HTTPS_PROXY=http://proxy.server:3128 no_proxy=localhost,127.0.0.1
LOG="$HOME/robin_seed/boot.log"
if [ ! -f "$HOME/robin/.boot_ok" ]; then
  bash "$HOME/robin/deploy/pa_bootstrap.sh" >> "$LOG" 2>&1 && touch "$HOME/robin/.boot_ok"
fi
cd "$HOME/robin" || exit 1
echo "=== uvicorn start $(date -u) sock=$SOCK" >> "$LOG"
exec "$HOME/robin/.venv/bin/uvicorn" --app-dir "$HOME/robin" --uds "$SOCK" backend.main:app
