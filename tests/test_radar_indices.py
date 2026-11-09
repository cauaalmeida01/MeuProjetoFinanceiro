"""Radar B3 (cotações, risco, fundamentos) e índices do Banco Central."""
import json
import urllib.request
from datetime import date

import pytest

import indices_bcb
import radar_b3 as r


@pytest.mark.parametrize("texto,esperado", [
    ("6,52", 6.52), ("8,0%", 8.0), ("-38,21", -38.21), ("94.386.800.000", 94386800000.0), ("-", None), ("", None),
])
def test_numero_em_formato_brasileiro(texto, esperado):
    assert r.numero(texto) == esperado


@pytest.mark.parametrize("ticker,valido", [("PETR4", True), ("SANB11", True), ("petr4", False), ("PETR", False), ("../X", False), ("PETR4;rm", False)])
def test_formato_do_ticker(ticker, valido):
    assert bool(r.TICKER.match(ticker)) is valido


def serie(precos):
    return [(f"d{i}", p) for i, p in enumerate(precos)]


def test_retorno_de_12_meses_e_maior_queda():
    m = r.metricas(serie([100, 120, 60, 90]))
    assert m["ret_12m"] == pytest.approx(-10)
    assert m["maior_queda"] == pytest.approx(-50)  # do topo de 120 até 60


def test_ativo_que_so_sobe_nao_tem_queda():
    assert r.metricas(serie([10, 11, 12, 13]))["maior_queda"] == 0


def test_preco_constante_tem_volatilidade_zero():
    assert r.metricas(serie([10, 10, 10]))["volatilidade"] == 0


def test_retorno_sem_historico_suficiente_e_nulo():
    m = r.metricas(serie([10, 11, 12]))
    assert m["ret_1m"] is None
    assert m["ret_3m"] is None


def test_retorno_de_um_mes_usa_21_pregoes():
    m = r.metricas(serie([50] * 10 + [100] + [200] * 21))
    assert m["ret_1m"] == pytest.approx(100)


def pagina(campos):
    celulas = "".join(f'<td class="label w2"><span class="help">?</span><span class="txt">{k}</span></td>'
                      f'<td class="data w2"><span class="txt">{v}</span></td>' for k, v in campos.items())
    return f"<table><tr>{celulas}</tr></table>".encode("latin-1")


CAMPOS_BANCO = {"Papel": "BBAS3", "Setor": "Intermediários Financeiros", "Subsetor": "Bancos", "P/L": "6,52", "P/VP": "0,52", "ROE": "8,0%",
                "Marg. Líquida": "0,0%", "Dív Líq / Patrim": "-", "Valor de mercado": "94.386.800.000", "Cres. Rec (5a)": "-9,6%"}


def fundamentus_falso(monkeypatch, resposta, campos):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: resposta(pagina(campos)))


def brapi_falsa(monkeypatch, retorno=None):
    monkeypatch.setattr(r, "get_json", lambda url: retorno or {"error": True, "message": "Token de autenticação não fornecido"})


def test_le_a_pagina_do_fundamentus(monkeypatch, resposta):
    fundamentus_falso(monkeypatch, resposta, CAMPOS_BANCO)
    assert r.fundamentus("BBAS3")["P/VP"] == "0,52"


def test_pagina_de_outro_papel_e_descartada(monkeypatch, resposta):
    fundamentus_falso(monkeypatch, resposta, CAMPOS_BANCO)
    assert r.fundamentus("PETR4") is None


def test_rotulo_repetido_fica_com_o_primeiro(monkeypatch, resposta):
    html = pagina({"Papel": "X1", "Lucro": "1"}) + pagina({"Lucro": "2"})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: resposta(html))
    assert r.fundamentus("X1")["Lucro"] == "1"


def test_banco_nao_tem_margem_nem_divida(monkeypatch, resposta):
    fundamentus_falso(monkeypatch, resposta, CAMPOS_BANCO)
    brapi_falsa(monkeypatch)
    f, erro = r.fundamentos("BBAS3", None)
    assert erro is None
    assert f["banco"] is True
    assert f["margem_liquida"] is None
    assert f["divida_liq_pl"] is None
    assert (f["pl"], f["pvp"], f["roe"]) == (6.52, 0.52, 8.0)


def test_empresa_comum_tem_margem_e_divida(monkeypatch, resposta):
    campos = {"Papel": "PETR4", "Setor": "Petróleo", "Subsetor": "Refino", "P/L": "5,09", "Marg. Líquida": "24,4%", "Dív Líq / Patrim": "0,65"}
    fundamentus_falso(monkeypatch, resposta, campos)
    brapi_falsa(monkeypatch)
    f, _ = r.fundamentos("PETR4", None)
    assert (f["banco"], f["margem_liquida"], f["divida_liq_pl"]) == (False, 24.4, 0.65)


def test_descricao_vem_da_brapi_com_token(monkeypatch, resposta):
    urls = []
    fundamentus_falso(monkeypatch, resposta, CAMPOS_BANCO)

    def falso(url):
        urls.append(url)
        return {"results": [{"summaryProfile": {"longBusinessSummary": "Um banco."}}]}

    monkeypatch.setattr(r, "get_json", falso)
    f, _ = r.fundamentos("BBAS3", "meu-token")
    assert f["resumo"] == "Um banco."
    assert "token=meu-token" in urls[0]
    assert "defaultKeyStatistics" not in urls[0]  # módulo fora do plano grátis


def test_sem_nenhuma_fonte_informa_o_erro(monkeypatch, resposta):
    fundamentus_falso(monkeypatch, resposta, {"Papel": "OUTRO"})
    brapi_falsa(monkeypatch)
    f, erro = r.fundamentos("BBAS3", None)
    assert f is None
    assert "Token" in erro


def test_carteira_le_acoes_da_xp():
    r.XP.write_text(json.dumps({
        "posicoes": [{"classe": "Ações", "ativo": "PETR4", "valor": 150, "aplicado": 90, "info": "3 ações · PM R$ 30,00"},
                     {"classe": "Tesouro Direto", "ativo": "LFT", "valor": 200, "aplicado": 150, "info": ""}],
        "lancamentos_recentes": [{"tipo": "provento", "descricao": "DIVIDENDOS PETR4", "valor": 1.5},
                                 {"tipo": "provento", "descricao": "JUROS S/ CAPITAL PETR4", "valor": 0.5},
                                 {"tipo": "provento", "descricao": "DIVIDENDOS ITUB4", "valor": 9},
                                 {"tipo": "compra", "descricao": "Compra PETR4", "valor": -90}]}), encoding="utf-8")
    assert r.carteira() == {"PETR4": {"quantidade": 3, "aplicado": 90, "valor": 150, "proventos": 2.0}}


def test_carteira_sem_arquivo():
    assert r.carteira() == {}


def test_adicionar_e_remover_da_lista(capsys):
    r.main(["--adicionar", "wege3", "VALE3"])
    assert r.ler_lista()["acompanhar"] == ["VALE3", "WEGE3"]
    r.main(["--remover", "VALE3"])
    assert r.ler_lista()["acompanhar"] == ["WEGE3"]


def test_ticker_invalido_nao_entra_na_lista():
    with pytest.raises(SystemExit, match="inválido"):
        r.main(["--adicionar", "abc"])
    assert r.ler_lista()["acompanhar"] == []


def falso_analisar(falhas=()):
    def f(t, token, minhas):
        if t in falhas:
            raise ValueError("sem dados")
        return {"ticker": t, "fundamentos": {}, "carteira": minhas.get(t)}
    return f


def test_acao_com_problema_nao_derruba_o_radar(monkeypatch, capsys):
    monkeypatch.setattr(r, "analisar", falso_analisar({"RUIM3"}))
    monkeypatch.setattr(r, "historico", lambda s: ({}, serie([100, 110, 120]), []))
    r.main(["--adicionar", "RUIM3", "BOAS3"])
    r.main([])
    dados = json.loads(r.SAIDA.read_text(encoding="utf-8"))
    assert [a["ticker"] for a in dados["acoes"]] == ["BOAS3"]
    assert "RUIM3 (sem dados)" in capsys.readouterr().out


def test_analisar_calcula_yield_e_proventos_de_12_meses(monkeypatch):
    s = [("2025-11-01", 10.0), ("2026-05-01", 12.0), ("2026-10-30", 20.0)]
    divs = [("2025-01-01", 5.0), ("2026-01-10", 1.0), ("2026-06-10", 1.0)]
    monkeypatch.setattr(r, "historico", lambda x: ({"regularMarketPrice": 20.0, "longName": "Empresa"}, s, divs))
    monkeypatch.setattr(r, "fundamentos", lambda t, tk: (None, "erro"))
    a = r.analisar("ABCD3", None, {})
    assert a["proventos_12m"] == 2  # o provento de antes da janela não conta
    assert a["dy_12m"] == 10


def test_baixa_serie_e_converte_datas(monkeypatch, resposta):
    corpo = json.dumps([{"data": "29/10/2026", "valor": "0.050788"}]).encode()
    urls = []

    def falso(req, timeout=None):
        urls.append(req.full_url)
        return resposta(corpo)

    monkeypatch.setattr(urllib.request, "urlopen", falso)
    assert indices_bcb.baixar(12, date(2026, 10, 1), date(2026, 10, 31)) == [("2026-10-29", 0.050788)]
    assert "bcdata.sgs.12" in urls[0] and "dataInicial=01/10/2026" in urls[0]


def test_atualizar_guarda_cdi_por_dia_e_ipca_por_mes(monkeypatch):
    monkeypatch.setattr(indices_bcb, "baixar", lambda s, de, ate: [("2026-09-01", 0.82)] if s == 433 else [("2026-10-29", 0.05)])
    ind = indices_bcb.atualizar()
    assert ind["cdi"] == {"2026-10-29": 0.05}
    assert ind["ipca"] == {"2026-09": 0.82}
    assert json.loads(indices_bcb.INDICES.read_text(encoding="utf-8"))["ipca"] == {"2026-09": 0.82}


def test_atualizar_so_busca_o_que_falta_e_preserva_o_resto(monkeypatch):
    indices_bcb.INDICES.write_text(json.dumps({"cdi": {"2021-01-04": 0.01, "2026-10-29": 0.05}, "ipca": {"2026-09": 0.82}}), encoding="utf-8")
    pedidos = {}

    def falso(s, de, ate):
        pedidos[s] = de
        return [("2026-10-30", 0.06)] if s == 12 else []

    monkeypatch.setattr(indices_bcb, "baixar", falso)
    ind = indices_bcb.atualizar()
    assert pedidos[12] == date(2026, 9, 19)  # 40 dias antes do último dado, para pegar correções
    assert ind["cdi"] == {"2021-01-04": 0.01, "2026-10-29": 0.05, "2026-10-30": 0.06}
