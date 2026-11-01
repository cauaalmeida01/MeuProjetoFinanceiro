"""Servidor local do painel: abre o painel no navegador e liga os botões aos scripts.

Uso:  python3 scripts/servidor.py          (abre http://127.0.0.1:8765)
      python3 scripts/servidor.py --porta 9000 --sem-navegador

Só aceita conexões do próprio computador. Com ele rodando, o painel ganha:
- "Adicionar ação" e "Remover" no Radar B3 (scripts/radar_b3.py);
- "Analisar" em cada ação, que roda a skill /analisar-acao pelo Claude Code em segundo plano;
- a lista de relatórios de dados/relatorios/, para ler no próprio painel;
- "Sincronizar agora" (scripts/sincronizar_pluggy.py).
Pelo Live Server (ou outra página em 127.0.0.1/localhost) os botões também aparecem, desde que este
servidor esteja rodando: o painel o procura na porta 8765. Aberto como arquivo, fica sem os botões.
"""
import argparse
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_painel  # noqa: E402
import radar_b3  # noqa: E402
import sincronizar_pluggy  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PAINEL = RAIZ / "painel" / "index.html"
RELATORIOS = RAIZ / "dados" / "relatorios"
# páginas do próprio computador (este servidor, o Live Server do VS Code etc.) podem usar a API
ORIGEM_LOCAL = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")
NOME_RELATORIO = re.compile(r"^ANALISE-[A-Z]{4}\d{1,2}-\d{4}-\d{2}-\d{2}\.md$")
# o que o Claude pode fazer sozinho durante a análise: rodar o radar, buscar na web e salvar o relatório
FERRAMENTAS = ["Bash(python3 scripts/radar_b3.py:*)", "WebSearch", "WebFetch"]

trava = threading.Lock()  # radar, sincronização e geração do painel mexem nos mesmos arquivos
tarefas = {}  # "analise:PETR4" / "sincronizar" → {estado, inicio, fim, mensagem}


def rodar(funcao, *args):
    """Roda um script em Python capturando o que ele imprime."""
    saida = io.StringIO()
    with trava, contextlib.redirect_stdout(saida):
        funcao(*args)
    return saida.getvalue().strip()


def em_segundo_plano(chave, alvo):
    if tarefas.get(chave, {}).get("estado") == "rodando":
        return False
    tarefas[chave] = {"estado": "rodando", "inicio": datetime.now().isoformat(timespec="seconds")}

    def corpo():
        try:
            msg = alvo()
            tarefas[chave].update(estado="pronto", mensagem=msg)
        except Exception as e:  # o painel mostra o erro em vez de travar
            tarefas[chave].update(estado="erro", mensagem=str(e)[-500:])
        tarefas[chave]["fim"] = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=corpo, daemon=True).start()
    return True


def analisar(ticker):
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("Claude Code não encontrado no PATH")
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    antes = set(RELATORIOS.glob(f"ANALISE-{ticker}-*.md"))
    r = subprocess.run([claude, "-p", f"/analisar-acao {ticker}", "--permission-mode", "acceptEdits",
                        "--allowedTools", *FERRAMENTAS], cwd=RAIZ, capture_output=True, text=True, timeout=1800)
    (RELATORIOS / f".log-{ticker}.txt").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    novos = sorted(set(RELATORIOS.glob(f"ANALISE-{ticker}-*.md")) - antes) or \
        sorted(RELATORIOS.glob(f"ANALISE-{ticker}-*.md"), key=lambda p: p.stat().st_mtime)[-1:]
    if r.returncode != 0 or not novos:
        raise RuntimeError(f"a análise não gerou relatório (veja dados/relatorios/.log-{ticker}.txt)")
    return novos[-1].name


def relatorios():
    if not RELATORIOS.exists():
        return []
    itens = []
    for p in RELATORIOS.glob("ANALISE-*.md"):
        if NOME_RELATORIO.match(p.name):
            _, ticker, data = p.stem.split("-", 2)
            itens.append({"nome": p.name, "ticker": ticker, "data": data})
    return sorted(itens, key=lambda i: (i["data"], i["ticker"]), reverse=True)


class Painel(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, status, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.cors()
        self.end_headers()
        self.wfile.write(dados)

    def cors(self):
        origem = self.headers.get("Origin")
        if origem and ORIGEM_LOCAL.match(origem):
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")

    def local(self):
        """Pedido feito pelo próprio computador: Host local e, se vier de uma página, página local."""
        origem = self.headers.get("Origin")
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost") and \
            (origem is None or bool(ORIGEM_LOCAL.match(origem)))

    def do_OPTIONS(self):
        if not self.local():
            return self.responder(403, {"erro": "origem não permitida"})
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        caminho, _, consulta = self.path.partition("?")
        if caminho in ("/", "/index.html"):
            pagina = PAINEL.read_text(encoding="utf-8").replace("</head>", "<script>window.SERVIDOR_LOCAL=true</script>\n</head>", 1)
            return self.responder(200, pagina.encode(), "text/html; charset=utf-8")
        if caminho.startswith("/api/") and not self.local():
            return self.responder(403, {"erro": "origem não permitida"})
        if caminho == "/api/status":
            return self.responder(200, {"ok": True, "tarefas": tarefas, "relatorios": relatorios()})
        if caminho == "/api/relatorio":
            nome = dict(p.split("=", 1) for p in consulta.split("&") if "=" in p).get("nome", "")
            if not NOME_RELATORIO.match(nome) or not (RELATORIOS / nome).exists():
                return self.responder(404, {"erro": "relatório não encontrado"})
            return self.responder(200, {"nome": nome, "texto": (RELATORIOS / nome).read_text(encoding="utf-8")})
        self.responder(404, {"erro": "não encontrado"})

    def do_POST(self):
        # só aceita pedidos de páginas do próprio computador (protege contra sites e DNS de terceiros)
        if not self.local():
            return self.responder(403, {"erro": "origem não permitida"})
        try:
            corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.responder(400, {"erro": "pedido inválido"})
        ticker = str(corpo.get("ticker", "")).strip().upper()
        if self.path in ("/api/radar/adicionar", "/api/radar/remover", "/api/analisar") and not radar_b3.TICKER.match(ticker):
            return self.responder(400, {"erro": "Use o código da B3, como PETR4 ou WEGE3."})

        if self.path == "/api/radar/adicionar":
            try:
                radar_b3.historico(ticker + ".SA")
            except Exception:
                return self.responder(404, {"erro": f"Não encontrei cotações de {ticker} na B3."})
            msg = rodar(lambda: (radar_b3.main(["--adicionar", ticker]), radar_b3.main([]), gerar_painel.main()))
            return self.responder(200, {"ok": True, "mensagem": next((l for l in msg.splitlines() if l.startswith("Radar B3")), "")})
        if self.path == "/api/radar/remover":
            rodar(lambda: (radar_b3.main(["--remover", ticker]), radar_b3.main([]), gerar_painel.main()))
            return self.responder(200, {"ok": True})
        if self.path == "/api/analisar":
            iniciou = em_segundo_plano(f"analise:{ticker}", lambda: analisar(ticker))
            return self.responder(202 if iniciou else 409, {"ok": iniciou, "erro": None if iniciou else "Essa análise já está rodando."})
        if self.path == "/api/sincronizar":
            iniciou = em_segundo_plano("sincronizar", lambda: rodar(sincronizar_pluggy.main).splitlines()[-1])
            return self.responder(202 if iniciou else 409, {"ok": iniciou})
        self.responder(404, {"erro": "não encontrado"})


def main():
    ap = argparse.ArgumentParser(description="Servidor local do painel")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()
    rodar(gerar_painel.main)
    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Painel)
    url = f"http://127.0.0.1:{a.porta}"
    print(f"Painel em {url}  (Ctrl+C para parar)")
    if not a.sem_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")


if __name__ == "__main__":
    main()
