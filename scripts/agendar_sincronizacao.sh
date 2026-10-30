#!/bin/zsh
# Liga (ou desliga) a sincronização diária com a Pluggy no macOS.
#
#   scripts/agendar_sincronizacao.sh           liga: roda todo dia às 13h
#   scripts/agendar_sincronizacao.sh remover   desliga
#
# O log de cada execução fica em dados/sincronizacao.log.

set -e
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ROTULO="com.meupainelfinanceiro.sincronizar"
PLIST="$HOME/Library/LaunchAgents/$ROTULO.plist"

launchctl bootout "gui/$(id -u)/$ROTULO" 2>/dev/null || true

if [[ "$1" == "remover" ]]; then
  rm -f "$PLIST"
  echo "Sincronização diária desligada."
  exit 0
fi

PYTHON="$(command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ROTULO</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$RAIZ/scripts/sincronizar_pluggy.py</string>
  </array>
  <key>WorkingDirectory</key><string>$RAIZ</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$RAIZ/dados/sincronizacao.log</string>
  <key>StandardErrorPath</key><string>$RAIZ/dados/sincronizacao.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Sincronização diária ligada (13h). Para rodar agora: launchctl kickstart gui/$(id -u)/$ROTULO"
