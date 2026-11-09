"""Sugestões de categoria: o modelo local e o que aparece em "Revisar Outros"."""
import pytest
import sugerir_categorias as sc

import gerar_painel as gp

EX = [("Lanchonete Boa Hora", "Alimentação"), ("Restaurante Sabor", "Alimentação"), ("Pizzaria Forno", "Alimentação"),
      ("Posto Combustivel Sul", "Transporte"), ("Auto Posto Norte", "Transporte"), ("Farmacia Saude", "Saúde")]


def t(desc, cat, valor=10.0, tipo="saida", titulo="Compra no débito"):
    return ["2026-01-01", desc, cat, tipo, valor, titulo, "Inter", ""]


def test_tokens_tiram_ruido_e_acento():
    assert sc.tokens("Açaí do João Ltda Salvador Bra 123") == ["acai", "joao"]


@pytest.mark.parametrize("desc,esperado", [
    ("Loja Aurora Salvador Bra", "Loja Aurora"),
    ("Lanche Aurora E Refeic 2salvador Bra", "Lanche Aurora E Refeic"),
    ("Acai Da Praca Feira De Santbra", "Acai Da Praca"),
    ("Comercial Exemplo Ltda Belo Horizontbra", "Comercial Exemplo Ltda"),
    ("Exemplo Premoldados Vera Cruz Bra", "Exemplo Premoldados"),
    ("Papelaria Cruz Das Alma Bra", "Papelaria"),
    ("Mp *lojaexemplo Osasco Bra", "Mp *lojaexemplo"),
    ("Ifd*ifood.com Agncia D Osasco B", "Ifd*ifood.com Agncia D"),
    ("Alfa Pagamentos S.a.", "Alfa Pagamentos S.a."),
    ("Joana Moura Lima", "Joana Moura Lima"),
    ("Pagali", "Pagali"),
    ("Salvador Bra", "Salvador"),
])
def test_tira_a_cidade_do_fim_da_compra(desc, esperado):
    assert sc.sem_localidade(desc) == esperado


def test_cidade_nao_vira_pista_de_categoria():
    """Regressão: duas lojas do iFood em Osasco faziam qualquer compra de Osasco parecer comida."""
    modelo = sc.treinar([("Ifood Club Osasco Bra", "Alimentação"), ("Ifood Agencia Osasco Bra", "Alimentação"), ("Roupas Finas Salvador Bra", "Compras")])
    assert sc.prever(modelo, "Mp *lojaexemplo Osasco Bra") == (None, 0.0)


def test_apostas_entra_no_treino():
    assert sc.exemplos_de([t("Casa De Jogos", "Apostas")], gp.parece_pessoa) == [("Casa De Jogos", "Apostas")]


def test_prefixo_liga_variacoes_da_palavra():
    assert "lanc" in sc.atributos("Lanchonete")


def test_preve_pela_palavra():
    cat, conf = sc.prever(sc.treinar(EX), "Lanchonete Do Bairro")
    assert cat == "Alimentação"
    assert 0.5 < conf <= 1


def test_nome_desconhecido_nao_tem_palpite():
    assert sc.prever(sc.treinar(EX), "Okto Xyz") == (None, 0.0)


def test_exemplos_nao_usam_pix_para_pessoa():
    """Pix para amigos marcados como Lazer ensinariam nomes próprios ao modelo."""
    tx = [t("Joana Moura Lima", "Lazer e eventos", titulo="Pix enviado"), t("Cinema Centro", "Lazer e eventos")]
    assert sc.exemplos_de(tx, gp.parece_pessoa) == [("Cinema Centro", "Lazer e eventos")]


def test_exemplos_ignoram_outros_e_entradas():
    tx = [t("Loja", "Outros"), t("Salario", "Mercado", tipo="entrada"), t("Mercado X", "Mercado"), t("Mercado X", "Mercado")]
    assert sc.exemplos_de(tx, gp.parece_pessoa) == [("Mercado X", "Mercado")]


def test_validacao_separa_treino_e_teste():
    """Com um exemplo só de cada palavra, nada no teste aparece no treino: acurácia precisa ser zero."""
    ex = [("Alfa", "A"), ("Beta", "B"), ("Gama", "C"), ("Delta", "D"), ("Epsilon", "E")]
    assert sc.avaliar(ex, dobras=5)["acuracia"] == 0


def test_avaliacao_calcula_precisao_e_cobertura():
    r = sc.avaliar(EX * 5, dobras=5, limiar=0.0)
    assert r["exemplos"] == 30
    assert r["precisao"] == pytest.approx(1.0)


def test_revisar_agrupa_e_ordena_por_valor():
    tx = [t("Loja A", "Outros", 10), t("Loja A", "Outros", 15), t("Loja B", "Outros", 100), t("Mercado", "Mercado")]
    itens = sc.revisar(tx, gp.parece_pessoa)
    assert [(i["desc"], i["n"], i["total"]) for i in itens] == [("Loja B", 1, 100), ("Loja A", 2, 25)]


def test_revisar_sem_confianca_vem_em_branco(monkeypatch):
    monkeypatch.setattr(sc, "prever", lambda m, d: ("Mercado", 0.5))
    assert sc.revisar([t("Loja", "Outros")], gp.parece_pessoa)[0]["sugestao"] is None


def test_revisar_com_confianca_sugere(monkeypatch):
    monkeypatch.setattr(sc, "prever", lambda m, d: ("Mercado", 0.91))
    item = sc.revisar([t("Loja", "Outros")], gp.parece_pessoa)[0]
    assert (item["sugestao"], item["confianca"]) == ("Mercado", 0.91)


def test_revisar_respeita_o_limite():
    tx = [t(f"Loja {i}", "Outros") for i in range(50)]
    assert len(sc.revisar(tx, gp.parece_pessoa, limite=30)) == 30


def test_revisar_traz_as_datas_mais_recentes_primeiro():
    tx = [t("Loja", "Outros"), t("Loja", "Outros")]
    tx[0][0], tx[1][0] = "2026-01-05", "2026-03-09"
    assert sc.revisar(tx, gp.parece_pessoa)[0]["datas"] == ["2026-03-09", "2026-01-05"]


def test_revisar_nao_repete_data_de_compras_no_mesmo_dia():
    assert sc.revisar([t("Loja", "Outros"), t("Loja", "Outros")], gp.parece_pessoa)[0]["datas"] == ["2026-01-01"]


def test_revisar_inclui_sugestao_confiavel_abaixo_do_limite(monkeypatch):
    tx = [t(f"Loja {i}", "Outros", 100 - i) for i in range(3)]
    monkeypatch.setattr(sc, "prever", lambda m, d: ("Mercado", 0.9) if d == "Loja 2" else (None, 0.0))
    assert [i["desc"] for i in sc.revisar(tx, gp.parece_pessoa, limite=1)] == ["Loja 0", "Loja 2"]
