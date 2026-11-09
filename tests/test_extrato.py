"""Junção do extrato e geração do painel de ponta a ponta."""
import json

import pytest

import gerar_painel as gp
import importar_extrato as ie


def l(data, valor="-10", desc="Loja", banco=None):
    linha = {"data": data, "titulo": "Compra no débito", "descricao": desc, "valor": valor, "tipo": "COMPRA_DEBITO"}
    return linha | ({"banco": banco} if banco else {})


def test_primeira_importacao():
    ie.juntar([l("2026-01-02"), l("2026-01-01")])
    assert [x["data"] for x in ie.ler(ie.HISTORICO)] == ["2026-01-01", "2026-01-02"]


def test_reimportar_o_mesmo_periodo_nao_duplica():
    novo = [l("2026-01-01"), l("2026-01-02")]
    ie.juntar(novo)
    ie.juntar(novo)
    assert len(ie.ler(ie.HISTORICO)) == 2


def test_historico_antigo_e_preservado():
    ie.juntar([l("2021-05-25", desc="Antiga"), l("2026-01-01", desc="Velha")])
    ie.juntar([l("2026-01-01", desc="Nova")], "2026-01-01")
    assert [x["descricao"] for x in ie.ler(ie.HISTORICO)] == ["Antiga", "Nova"]


def test_linhas_antes_do_inicio_sao_ignoradas():
    """O primeiro dia da janela da Pluggy pode vir pela metade: fica o que já estava no histórico."""
    ie.juntar([l("2025-11-01", desc="Completa"), l("2025-11-02", desc="Velha")])
    ie.juntar([l("2025-11-01", desc="Metade"), l("2025-11-02", desc="Nova")], "2025-11-02")
    assert [x["descricao"] for x in ie.ler(ie.HISTORICO)] == ["Completa", "Nova"]


def test_coluna_banco_e_preenchida_e_historico_antigo_fica_vazio():
    ie.HISTORICO.write_text("data|titulo|descricao|valor|tipo\n2021-01-01|T|Antiga|-1|X\n", encoding="utf-8")
    ie.juntar([l("2026-01-01", banco="31872495")])
    linhas = ie.ler(ie.HISTORICO)
    assert [x["banco"] for x in linhas] == ["", "31872495"]


def test_guarda_copia_de_seguranca():
    ie.juntar([l("2026-01-01")])
    ie.juntar([l("2026-01-02")])
    assert ie.HISTORICO.with_suffix(".psv.bak").exists()


def test_campos_extras_nao_vao_para_o_arquivo():
    ie.juntar([l("2026-01-01") | {"_quando": "objeto"}])
    assert "_quando" not in ie.HISTORICO.read_text(encoding="utf-8")


@pytest.fixture
def painel():
    gp.EXTRATO.write_text("\n".join([
        "data|titulo|descricao|valor|tipo|banco",
        "2026-08-01|Pix recebido|Banco Inter Sa|150|PIX|00416968",
        "2026-08-02|Compra no débito|Ifood *Sabor|-40|COMPRA_DEBITO|",
        "2026-08-03|Pix enviado|Ana Exemplo|-200|PIX|33264668",
        "2026-08-04|Pix enviado|Ana Exemplo|-100|PIX|31872495",
        "2026-08-05|Pix recebido|Ana Exemplo|400|PIX|31872495",
        "2026-08-06|Aplicação|CDB POS DI LIQ|-300|APLICACAO|",
    ]) + "\n", encoding="utf-8")
    gp.REGRAS_PESSOAIS.write_text(json.dumps({
        "voce_mesmo": ["ana exemplo"],
        "contas_proprias": {"31872495": {"nome": "C6", "recebido": "Comissão"}},
        "neutros": [{"categoria": "Repasses", "descricao": "banco inter sa", "titulo": "Pix recebido"}],
        "ajustes": [{"data": "2026-08-02", "descricao": "Parte minha", "valor": 67.5, "categoria": "Comissão", "tipo": "entrada"}],
    }), encoding="utf-8")
    gp.XP.write_text(json.dumps({"abertura": "2026-01-01", "patrimonio": 200, "saldo_conta": 0, "posicoes": [], "mensal": [],
                                 "lancamentos_recentes": [], "envios_inter_para_xp": [["2026-08-03", 200]],
                                 "retornos_xp_para_inter": [], "fotos_mensais": {"2026-08": ["2026-08-31", 200]}}), encoding="utf-8")
    gp.main()
    return {t[1] + t[5]: t for t in json.loads(gp.SAIDA_JSON.read_text(encoding="utf-8"))}, gp.SAIDA_HTML.read_text(encoding="utf-8")


def test_painel_classifica_cada_lancamento(painel):
    tx, _ = painel
    assert tx["Banco Inter SaPix recebido"][2:4] == ["Repasses", "transf"]
    assert tx["Ifood *SaborCompra no débito"][2:4] == ["Alimentação", "saida"]
    assert tx["CDB POS DI LIQAplicação"][7] == "CDB Pós-DI Liquidez Diária"


def test_painel_separa_xp_de_c6(painel):
    tx, _ = painel
    assert tx["Ana ExemploPix recebido"][2:4] == ["Comissão", "entrada"]
    enviados = {t[4]: (t[2], t[3]) for t in json.loads(gp.SAIDA_JSON.read_text(encoding="utf-8")) if t[5] == "Pix enviado"}
    assert enviados == {200: ("Investimentos", "aporte"), 100: ("Entre suas contas", "transf")}


def test_ajuste_manual_entra_em_ordem_de_data(painel):
    tx, _ = painel
    assert tx["Parte minhaAjuste manual"][2:5] == ["Comissão", "entrada", 67.5]
    datas = [t[0] for t in json.loads(gp.SAIDA_JSON.read_text(encoding="utf-8"))]
    assert datas == sorted(datas)


def test_painel_nao_deixa_marcadores_de_dados(painel):
    _, html = painel
    for marcador in ("/*__DADOS__*/", "/*__XP__*/", "/*__INTERINV__*/", "/*__SYNC__*/", "/*__INDICES__*/", "/*__RADAR__*/"):
        assert marcador not in html


def test_dados_de_conciliacao_nao_vao_para_a_pagina(painel):
    _, html = painel
    assert "envios_inter_para_xp" not in html.split("const XP=")[1].split(";\n")[0]
    assert "fotos_mensais" not in html
