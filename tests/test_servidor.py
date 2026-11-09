"""Servidor local: segurança das rotas e funcionamento dos botões do painel."""
import http.client
import json
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

import servidor as s

RELATORIO = "ANALISE-BBAS3-2026-10-31.md"


@pytest.fixture
def api():
    s.PAINEL.write_text("<html><head></head><body>painel</body></html>", encoding="utf-8")
    s.RELATORIOS.mkdir()
    (s.RELATORIOS / RELATORIO).write_text("# Análise", encoding="utf-8")
    s.tarefas.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), s.Painel)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    porta = srv.server_address[1]

    def chamar(metodo, caminho, corpo=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
        dados = corpo.encode() if isinstance(corpo, str) else json.dumps(corpo) if corpo is not None else None
        c.request(metodo, caminho, dados, {"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        texto = r.read().decode()
        c.close()
        return r.status, texto, r.headers

    yield chamar
    srv.shutdown()
    srv.server_close()


def esperar(condicao):
    for _ in range(200):
        if condicao():
            return True
        time.sleep(0.01)
    return False


def test_pagina_recebe_marca_de_servidor_local(api):
    status, texto, _ = api("GET", "/")
    assert status == 200
    assert "window.SERVIDOR_LOCAL=true" in texto


def test_status_lista_relatorios(api):
    status, texto, _ = api("GET", "/api/status")
    assert status == 200
    assert json.loads(texto)["relatorios"] == [{"nome": RELATORIO, "ticker": "BBAS3", "data": "2026-10-31"}]


@pytest.mark.parametrize("metodo,caminho,corpo", [
    ("GET", "/api/status", None),
    ("GET", f"/api/relatorio?nome={RELATORIO}", None),
    ("POST", "/api/analisar", {"ticker": "PETR4"}),
    ("POST", "/api/sincronizar", {}),
    ("POST", "/api/radar/adicionar", {"ticker": "PETR4"}),
])
@pytest.mark.parametrize("cabecalho", [{"Origin": "https://site-qualquer.com"}, {"Origin": "http://127.0.0.1.evil.com"},
                                       {"Host": "malicioso.com:8765"}, {"Origin": "null"}])
def test_pedidos_de_fora_sao_recusados(api, metodo, caminho, corpo, cabecalho):
    status, _, _ = api(metodo, caminho, corpo, cabecalho)
    assert status == 403
    assert s.tarefas == {}


def test_pagina_local_recebe_permissao_cors(api):
    _, _, h = api("GET", "/api/status", headers={"Origin": "http://127.0.0.1:5500"})
    assert h["Access-Control-Allow-Origin"] == "http://127.0.0.1:5500"


def test_sem_permissao_cors_para_quem_nao_pediu(api):
    _, _, h = api("GET", "/api/status")
    assert h["Access-Control-Allow-Origin"] is None


def test_preflight_local(api):
    status, _, h = api("OPTIONS", "/api/analisar", headers={"Origin": "http://localhost:5500"})
    assert status == 204
    assert "POST" in h["Access-Control-Allow-Methods"]


def test_preflight_de_fora(api):
    status, _, h = api("OPTIONS", "/api/analisar", headers={"Origin": "https://site-qualquer.com"})
    assert status == 403
    assert h["Access-Control-Allow-Origin"] is None


def test_abre_relatorio(api):
    status, texto, _ = api("GET", f"/api/relatorio?nome={RELATORIO}")
    assert status == 200
    assert json.loads(texto)["texto"] == "# Análise"


@pytest.mark.parametrize("nome", ["../../.env", "..%2F..%2F.env", ".log-BBAS3.txt", "ANALISE-BBAS3-2026-10-31.md/../../.env", "ANALISE-XXXX1-2026-01-01.md"])
def test_nao_abre_outros_arquivos(api, nome):
    (s.RELATORIOS / ".log-BBAS3.txt").write_text("log", encoding="utf-8")
    status, _, _ = api("GET", f"/api/relatorio?nome={nome}")
    assert status == 404


@pytest.mark.parametrize("rota", ["/api/radar/adicionar", "/api/radar/remover", "/api/analisar"])
@pytest.mark.parametrize("ticker", ["abc", "PETR4;rm -rf", "", "../X"])
def test_ticker_invalido_e_recusado(api, rota, ticker):
    status, texto, _ = api("POST", rota, {"ticker": ticker})
    assert status == 400
    assert "código da B3" in json.loads(texto)["erro"]


def test_corpo_invalido(api):
    status, texto, _ = api("POST", "/api/analisar", "{isto não é json")
    assert status == 400
    assert "inválido" in json.loads(texto)["erro"]


def test_rota_desconhecida(api):
    assert api("GET", "/nada")[0] == 404
    assert api("POST", "/api/nada", {})[0] == 404


def test_adicionar_acao_inexistente(api, monkeypatch):
    def falso(simbolo):
        raise ValueError("sem dados")

    monkeypatch.setattr(s.radar_b3, "historico", falso)
    status, texto, _ = api("POST", "/api/radar/adicionar", {"ticker": "ZZZZ3"})
    assert status == 404
    assert "ZZZZ3" in json.loads(texto)["erro"]


def test_adicionar_acao_atualiza_radar_e_painel(api, monkeypatch):
    ordem = []
    monkeypatch.setattr(s.radar_b3, "historico", lambda x: ordem.append(x))
    monkeypatch.setattr(s.radar_b3, "main", lambda a: ordem.append(a))
    monkeypatch.setattr(s.gerar_painel, "main", lambda: ordem.append("painel"))
    status, _, _ = api("POST", "/api/radar/adicionar", {"ticker": "wege3"})
    assert status == 200
    assert ordem == ["WEGE3.SA", ["--adicionar", "WEGE3"], [], "painel"]


def test_remover_acao(api, monkeypatch):
    ordem = []
    monkeypatch.setattr(s.radar_b3, "main", lambda a: ordem.append(a))
    monkeypatch.setattr(s.gerar_painel, "main", lambda: ordem.append("painel"))
    assert api("POST", "/api/radar/remover", {"ticker": "WEGE3"})[0] == 200
    assert ordem == [["--remover", "WEGE3"], [], "painel"]


def test_analise_roda_em_segundo_plano(api, monkeypatch):
    monkeypatch.setattr(s, "analisar", lambda t: f"ANALISE-{t}-2026-01-01.md")
    assert api("POST", "/api/analisar", {"ticker": "PETR4"})[0] == 202
    assert esperar(lambda: s.tarefas["analise:PETR4"]["estado"] == "pronto")
    assert s.tarefas["analise:PETR4"]["mensagem"] == "ANALISE-PETR4-2026-01-01.md"


def test_mesma_analise_nao_roda_duas_vezes(api, monkeypatch):
    libera = threading.Event()
    monkeypatch.setattr(s, "analisar", lambda t: libera.wait(5) and "x")
    assert api("POST", "/api/analisar", {"ticker": "PETR4"})[0] == 202
    assert api("POST", "/api/analisar", {"ticker": "PETR4"})[0] == 409
    libera.set()
    assert esperar(lambda: s.tarefas["analise:PETR4"]["estado"] == "pronto")


def test_erro_na_analise_aparece_para_o_usuario(api, monkeypatch):
    def falha(t):
        raise RuntimeError("não gerou relatório")

    monkeypatch.setattr(s, "analisar", falha)
    api("POST", "/api/analisar", {"ticker": "PETR4"})
    assert esperar(lambda: s.tarefas["analise:PETR4"]["estado"] == "erro")
    assert "não gerou" in s.tarefas["analise:PETR4"]["mensagem"]


def concluido(codigo=0, saida="ok"):
    return subprocess.CompletedProcess([], codigo, saida, "")


def test_analise_limita_o_que_o_claude_pode_fazer(monkeypatch):
    s.RELATORIOS.mkdir()
    chamadas = []

    def falso(args, **kw):
        chamadas.append((args, kw))
        (s.RELATORIOS / "ANALISE-PETR4-2026-11-08.md").write_text("x", encoding="utf-8")
        return concluido()

    monkeypatch.setattr(s.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(s.subprocess, "run", falso)
    assert s.analisar("PETR4") == "ANALISE-PETR4-2026-11-08.md"
    args, kw = chamadas[0]
    assert args[args.index("--allowedTools") + 1:] == ["Bash(python3 scripts/radar_b3.py:*)", "WebSearch", "WebFetch"]
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in args
    assert not kw.get("shell")


def test_analise_que_falha_avisa(monkeypatch):
    monkeypatch.setattr(s.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(s.subprocess, "run", lambda a, **k: concluido(1))
    with pytest.raises(RuntimeError, match="não gerou"):
        s.analisar("PETR4")


def test_sem_claude_instalado(monkeypatch):
    monkeypatch.setattr(s.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeError, match="não encontrado"):
        s.analisar("PETR4")


def test_lista_de_relatorios_mais_recentes_primeiro():
    s.RELATORIOS.mkdir()
    for nome in ("ANALISE-PETR4-2026-01-01.md", "ANALISE-BBAS3-2026-03-01.md", "rascunho.md"):
        (s.RELATORIOS / nome).write_text("x", encoding="utf-8")
    assert [r["ticker"] for r in s.relatorios()] == ["BBAS3", "PETR4"]


@pytest.fixture
def tx_salvas(api):
    linhas = [["2026-01-01", "Loja Y", "Outros", "saida", 10, "Compra", "Inter", ""], ["2026-01-01", "Mercado", "Mercado", "saida", 5, "Compra", "Inter", ""]]
    s.gerar_painel.SAIDA_JSON.write_text(json.dumps(linhas), encoding="utf-8")
    return api


def test_confirmar_categoria_grava_regra_e_refaz_o_painel(tx_salvas, monkeypatch):
    gerados = []
    monkeypatch.setattr(s.gerar_painel, "main", lambda: gerados.append(1))
    s.gerar_painel.REGRAS_PESSOAIS.write_text(json.dumps({"voce_mesmo": ["ana"], "destinos": {"x": "Lazer"}}), encoding="utf-8")
    assert tx_salvas("POST", "/api/categoria", {"descricao": "Loja Y", "categoria": "Mercado"})[0] == 200
    regras = json.loads(s.gerar_painel.REGRAS_PESSOAIS.read_text(encoding="utf-8"))
    assert regras == {"voce_mesmo": ["ana"], "destinos": {"x": "Lazer", "loja y": "Mercado"}}
    assert gerados == [1]
    assert s.base_dados.regras_conhecidas()[("destino", "loja y")]["origem"] == "revisao"


@pytest.mark.parametrize("corpo", [
    {"descricao": "Loja Y", "categoria": "Inventada"},
    {"descricao": "Loja Y", "categoria": "Outros"},
    {"descricao": "Mercado", "categoria": "Mercado"},  # não está em "Outros"
    {"descricao": "Nao Existe", "categoria": "Mercado"},
    {},
])
def test_categoria_invalida_nao_altera_as_regras(tx_salvas, corpo):
    assert tx_salvas("POST", "/api/categoria", corpo)[0] == 400
    assert not s.gerar_painel.REGRAS_PESSOAIS.exists()


def test_categoria_de_fora_e_recusada(tx_salvas):
    corpo = {"descricao": "Loja Y", "categoria": "Mercado"}
    assert tx_salvas("POST", "/api/categoria", corpo, {"Origin": "https://site-qualquer.com"})[0] == 403
    assert not s.gerar_painel.REGRAS_PESSOAIS.exists()
