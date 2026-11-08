#!/bin/zsh
# Deixa o painel sempre ligado no Mac, sem precisar do VS Code nem do terminal.
#
#   scripts/ligar_painel.sh            liga: o servidor sobe sozinho ao entrar no Mac
#   scripts/ligar_painel.sh remover    desliga e apaga o atalho
#
# O painel fica em http://127.0.0.1:8765, só acessível deste Mac.
# Cria também o app "Painel Financeiro" em ~/Applications, para pôr no Dock.
# O log do servidor fica em dados/servidor.log.

set -e
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ROTULO="com.meupainelfinanceiro.painel"
PLIST="$HOME/Library/LaunchAgents/$ROTULO.plist"
APP="$HOME/Applications/Painel Financeiro.app"
URL="http://127.0.0.1:8765"

launchctl bootout "gui/$(id -u)/$ROTULO" 2>/dev/null || true

if [[ "$1" == "remover" ]]; then
  rm -f "$PLIST"
  rm -rf "$APP"
  echo "Painel desligado e atalho removido."
  exit 0
fi

PYTHON="$(command -v python3)"
# o launchd começa com um PATH mínimo; o "Analisar" precisa achar o claude (~/.local/bin)
CAMINHO="$HOME/.local/bin:$(dirname "$PYTHON"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Applications"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$ROTULO</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>$RAIZ/scripts/servidor.py</string>
    <string>--sem-navegador</string>
  </array>
  <key>WorkingDirectory</key><string>$RAIZ</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$CAMINHO</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$RAIZ/dados/servidor.log</string>
  <key>StandardErrorPath</key><string>$RAIZ/dados/servidor.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# atalho que só abre o painel no navegador padrão
rm -rf "$APP"
osacompile -o "$APP" -e "open location \"$URL\"" >/dev/null

for i in {1..20}; do
  curl -s -o /dev/null "$URL/api/status" && break
  sleep 0.5
done
if curl -s -o /dev/null "$URL/api/status"; then
  echo "Painel ligado em $URL"
  echo "Atalho criado: $APP (arraste para o Dock)"
  open "$URL"
else
  echo "O servidor não respondeu. Veja dados/servidor.log"
  exit 1
fi
