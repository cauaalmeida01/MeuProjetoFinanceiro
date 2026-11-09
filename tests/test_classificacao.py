"""Regras que decidem se cada lançamento é gasto, receita, investimento ou movimentação neutra."""
from collections import Counter

import pytest

from gerar_painel import acumulado, classificar, motivo, neutro, parece_pessoa, por_regra, produto

CATS = [("Alimentação", ["ifood"]), ("Transporte", ["uber"])]
EU = ["ana exemplo"]
C6 = "31872495"


def conc(envio=(), retorno=()):
    return {"envio": Counter(envio), "retorno": Counter(retorno)}


def c(titulo, desc, valor, data="2026-01-10", destinos=(), origens=(), concil=None, **kw):
    return classificar(data, titulo, desc, valor, CATS, list(destinos), list(origens), EU, concil or conc(), **kw)[:2]


@pytest.mark.parametrize("titulo", ["Aplicação", "Aplicação em fundos"])
def test_aplicacao_e_aporte(titulo):
    assert c(titulo, "CDB POS DI LIQ", -100) == ("aporte", "Inter")


@pytest.mark.parametrize("titulo", ["Resgate", "Resgate de fundo", "Vencimento Renda Fixa"])
def test_resgate(titulo):
    assert c(titulo, "CDB POS DI LIQ", 100) == ("resgate", "Inter")


def test_pix_para_si_conciliado_com_a_xp_e_aporte():
    assert c("Pix enviado", "Ana Exemplo", -200, concil=conc([("2026-01-10", 200)])) == ("aporte", "XP")


def test_retorno_da_xp_conciliado_e_resgate():
    assert c("Pix recebido", "Ana Exemplo", 50, concil=conc(retorno=[("2026-01-10", 50)])) == ("resgate", "XP")


def test_pix_para_si_sem_conciliacao_nao_e_gasto():
    assert c("Pix enviado", "Ana Exemplo", -200) == ("transf", "Entre suas contas")


def test_conciliacao_consome_cada_envio_uma_vez_so():
    """Dois Pix iguais no mesmo dia, um só chegou na XP: o segundo não pode virar aporte."""
    concil = conc([("2026-01-10", 1200)])
    assert c("Pix enviado", "Ana Exemplo", -1200, concil=concil) == ("aporte", "XP")
    assert c("Pix enviado", "Ana Exemplo", -1200, concil=concil) == ("transf", "Entre suas contas")


def test_pix_de_conta_propria_configurada_vira_receita():
    proprias = {C6: {"nome": "C6", "recebido": "Comissão"}}
    assert c("Pix recebido", "Ana Exemplo", 400, banco=C6, proprias=proprias) == ("entrada", "Comissão")


def test_conta_propria_sem_categoria_continua_transferencia():
    proprias = {"10573521": {"nome": "Mercado Pago"}}
    assert c("Pix recebido", "Ana Exemplo", 55, banco="10573521", proprias=proprias) == ("transf", "Entre suas contas")


def test_envio_para_conta_propria_nao_vira_receita():
    proprias = {C6: {"nome": "C6", "recebido": "Comissão"}}
    assert c("Pix enviado", "Ana Exemplo", -400, banco=C6, proprias=proprias) == ("transf", "Entre suas contas")


def test_conciliacao_com_xp_tem_prioridade_sobre_conta_propria():
    proprias = {C6: {"nome": "C6", "recebido": "Comissão"}}
    resultado = c("Pix recebido", "Ana Exemplo", 50, banco=C6, proprias=proprias, concil=conc(retorno=[("2026-01-10", 50)]))
    assert resultado == ("resgate", "XP")


def test_movimentacao_neutra_nao_conta_como_receita():
    regras = [{"categoria": "Repasses", "descricao": "banco inter sa", "titulo": "Pix recebido"}]
    assert c("Pix recebido", "Banco Inter Sa", 150, neutros=regras) == ("transf", "Repasses")


@pytest.mark.parametrize("data,esperado", [("2026-07-31", None), ("2026-08-01", "R"), ("2026-08-31", "R"), ("2026-09-01", None)])
def test_regra_neutra_respeita_o_periodo(data, esperado):
    regras = [{"categoria": "R", "descricao": "x", "desde": "2026-08-01", "ate": "2026-08-31"}]
    assert (neutro(data, "Pix", "X", "", regras) or {}).get("categoria") == esperado


def test_regra_neutra_filtra_por_banco():
    regras = [{"categoria": "R", "descricao": "x", "banco": C6}]
    assert neutro("2026-01-01", "Pix", "X", C6, regras)["categoria"] == "R"
    assert neutro("2026-01-01", "Pix", "X", "00416968", regras) is None


@pytest.mark.parametrize("titulo,valor,tipo", [("Estorno", 30, "entrada"), ("Pix enviado devolvido", 30, "entrada"),
                                               ("Pix recebido devolvido", -30, "saida")])
def test_devolucoes(titulo, valor, tipo):
    assert c(titulo, "Loja Qualquer", valor) == (tipo, "Estornos e devoluções")


def test_entrada_com_origem_conhecida():
    assert c("Pix recebido", "Pai Da Ana", 1000, origens=[("pai da ana", "Família")]) == ("entrada", "Família")


def test_entrada_desconhecida():
    assert c("Pix recebido", "Fulano De Tal", 10) == ("entrada", "Pix recebido")


def test_pessoa_conhecida_vence_a_regra_de_estabelecimento():
    assert c("Pix enviado", "Uber Da Silva", -20, destinos=[("uber da silva", "Lazer")]) == ("saida", "Lazer")


def test_regra_de_estabelecimento():
    assert c("Compra no débito", "IFOOD *Restaurante", -40) == ("saida", "Alimentação")


def test_boleto_sem_regra():
    assert c("Pagamento efetuado", "Conta Desconhecida", -90) == ("saida", "Contas e boletos")


def test_pix_para_pessoa_fisica():
    assert c("Pix enviado", "Joana Moura Lima", -30) == ("saida", "Pix para pessoas")


def test_pix_para_empresa_sem_regra_vai_para_outros():
    assert c("Pix enviado", "Comercio Exemplo Ltda", -30) == ("saida", "Outros")


def test_compra_sem_regra_vai_para_outros():
    assert c("Compra no débito", "Joana Moura Lima", -30) == ("saida", "Outros")


@pytest.mark.parametrize("desc,esperado", [
    ("Joana Moura Lima", True),
    ("Aurora", False),
    ("Beta Brasil Tecnologia Ltda", False),
    ("Alfa Pagamentos S.a.", False),
])
def test_parece_pessoa(desc, esperado):
    assert parece_pessoa(desc) is esperado


def test_primeira_regra_vence():
    cats = [("A", ["bar"]), ("B", ["barbearia"])]
    assert por_regra("Barbearia Corte", cats) == ("A", "bar")


def test_por_regra_sem_correspondencia():
    assert por_regra("Nada", CATS) is None


@pytest.mark.parametrize("tipo,cat,desc,esperado", [
    ("aporte", "XP", "Ana", "XP"),
    ("aporte", "Inter", "CDB POS DI LIQ", "CDB Pós-DI Liquidez Diária"),
    ("resgate", "Inter", "LCI IPCA 2029", "LCI IPCA+"),
    ("aporte", "Inter", "Produto Novo", "Produto Novo"),
    ("saida", "Outros", "CDB POS DI LIQ", ""),
])
def test_produto(tipo, cat, desc, esperado):
    assert produto(tipo, cat, desc) == esperado


def test_acumulado_e_composto():
    assert acumulado([10, 10]) == pytest.approx(21)
    assert acumulado([]) == 0


@pytest.mark.parametrize("titulo,desc,valor,kw,regra", [
    ("Aplicação", "CDB", -100, {}, ("operacao", "Aplicação")),
    ("Compra no débito", "IFOOD *X", -40, {}, ("estabelecimento", "ifood")),
    ("Compra no débito", "Loja", -40, {"destinos": [("loja", "Lazer")]}, ("destino", "loja")),
    ("Pix recebido", "Pai", 10, {"origens": [("pai", "Família")]}, ("origem", "pai")),
    ("Pix recebido", "Fulano", 10, {}, ("padrao", "pix recebido")),
    ("Pix enviado", "Ana Exemplo", -10, {}, ("padrao", "proprio nome")),
    ("Pix enviado", "Joana Moura Lima", -10, {}, ("padrao", "pix para pessoa")),
    ("Compra no débito", "Loja", -10, {}, ("padrao", "sem regra")),
    ("Pagamento efetuado", "Conta", -10, {}, ("operacao", "Pagamento efetuado")),
])
def test_resultado_informa_a_regra_que_decidiu(titulo, desc, valor, kw, regra):
    args = {"destinos": [], "origens": [], **kw}
    assert classificar("2026-01-10", titulo, desc, valor, CATS, args["destinos"], args["origens"], EU, conc()).regra == regra


def test_regra_de_conciliacao_e_de_conta_propria():
    r = classificar("2026-01-10", "Pix enviado", "Ana Exemplo", -200, CATS, [], [], EU, conc([("2026-01-10", 200)]))
    assert r.regra == ("conciliacao", "corretora")
    r = classificar("2026-01-10", "Pix recebido", "Ana Exemplo", 400, CATS, [], [], EU, conc(), banco=C6, proprias={C6: {"recebido": "Comissão"}})
    assert r.regra == ("conta_propria", C6)


def test_regra_neutra_e_informada():
    regras = [{"categoria": "R", "descricao": "Banco X"}]
    assert classificar("2026-01-10", "Pix recebido", "Banco X", 5, CATS, [], [], EU, conc(), neutros=regras).regra == ("neutra", "banco x")


@pytest.mark.parametrize("regra,texto", [
    (("estabelecimento", "ifood"), 'Regra de estabelecimento: contém "ifood"'),
    (("padrao", "sem regra"), "Nenhuma regra reconheceu"),
    (("conciliacao", "corretora"), "Conciliado com o extrato da corretora"),
])
def test_motivo_em_portugues(regra, texto):
    assert motivo(regra) == texto


def test_motivo_de_regra_confirmada_mostra_a_data():
    conhecidas = {("destino", "loja"): {"origem": "revisao", "criada_em": "2026-11-08T21:00:00-03:00"}}
    assert motivo(("destino", "loja"), conhecidas) == "Você confirmou esta categoria em 08/11/2026"
