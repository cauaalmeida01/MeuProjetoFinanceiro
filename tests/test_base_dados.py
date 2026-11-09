"""Banco de dados: migração, identidade estável, integridade e histórico de classificações."""
import sqlite3

import base_dados as db
import pytest

import gerar_painel as gp
import importar_extrato as ie


def linha(data="2026-01-01", valor="-10", desc="Loja", titulo="Compra", **kw):
    return {"data": data, "titulo": titulo, "descricao": desc, "valor": valor, "tipo": "X", **kw}


REGRA = ("estabelecimento", "ifood")


def consulta(sql, *args):
    with db.conexao() as con:
        return [tuple(l) for l in con.execute(sql, args)]


def ids():
    return [t["id"] for t in db.ler_transacoes()]


@pytest.mark.parametrize("valor,esperado", [("-10", -1000), ("1561.51", 156151), (0.1 + 0.2, 30), ("10000.55", 1000055), (-8.2, -820), ("0.005", 1)])
def test_centavos_sem_erro_de_ponto_flutuante(valor, esperado):
    assert db.centavos(valor) == esperado


def test_valor_e_inteiro_no_banco():
    ie.juntar([linha(valor="-1561.51")])
    assert consulta("SELECT valor_centavos, typeof(valor_centavos) FROM transacoes") == [(-156151, "integer")]
    assert db.ler_transacoes()[0]["valor"] == -1561.51


def test_lancamentos_identicos_no_mesmo_dia_ficam_separados():
    ie.juntar([linha(), linha()])
    assert len(db.ler_transacoes()) == 2


def test_reimportar_mantem_o_id():
    ie.juntar([linha(), linha(data="2026-01-02", desc="Outra")])
    antes = ids()
    ie.juntar([linha(), linha(data="2026-01-02", desc="Outra")])
    assert ids() == antes


def test_lancamento_novo_nao_muda_o_id_dos_antigos():
    ie.juntar([linha()])
    antes = ids()
    ie.juntar([linha(), linha(data="2026-01-02")])
    assert ids()[:1] == antes and len(ids()) == 2


def test_lancamento_que_sumiu_e_removido():
    ie.juntar([linha(desc="Fica"), linha(desc="Sai")])
    r = db.substituir_periodo(db_linhas := [linha(desc="Fica")], "2026-01-01")
    assert (r["removidas"], r["inseridas"], r["mantidas"]) == (1, 0, len(db_linhas))
    assert [t["descricao"] for t in db.ler_transacoes()] == ["Fica"]


def test_banco_que_chega_depois_atualiza_sem_trocar_o_id():
    ie.juntar([linha()])
    antes = ids()
    ie.juntar([linha(banco="31872495")])
    assert ids() == antes
    assert db.ler_transacoes()[0]["banco"] == "31872495"


def test_integridade_recusa_data_invalida():
    with pytest.raises(sqlite3.IntegrityError):
        db.substituir_periodo([linha(data="2026-1")], "2026-01-01")


def test_chave_estrangeira_esta_ativa():
    with db.conexao() as con, pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO transacoes (conta_id, chave, data, titulo, descricao, valor_centavos) VALUES (99, 'x', '2026-01-01', 't', 'd', 1)")


def test_classificacao_guarda_a_regra():
    ie.juntar([linha()])
    db.registrar_classificacoes([(ids()[0], "saida", "Alimentação", REGRA)])
    assert consulta("SELECT tipo, categoria, regra_tipo, regra_trecho FROM classificacao_atual") == [("saida", "Alimentação", *REGRA)]


def test_repetir_a_classificacao_nao_cria_historico():
    ie.juntar([linha()])
    item = (ids()[0], "saida", "Alimentação", REGRA)
    assert db.registrar_classificacoes([item]) == 1
    assert db.registrar_classificacoes([item]) == 0
    assert len(db.historico_de(ids()[0])) == 1


def test_mudanca_de_categoria_preserva_a_anterior():
    ie.juntar([linha()])
    tid = ids()[0]
    db.registrar_classificacoes([(tid, "saida", "Outros", ("padrao", "sem regra"))])
    db.registrar_classificacoes([(tid, "saida", "Mercado", ("destino", "loja"))])
    assert [h["categoria"] for h in db.historico_de(tid)] == ["Outros", "Mercado"]
    assert consulta("SELECT categoria FROM classificacao_atual") == [("Mercado",)]


def test_mudar_so_a_regra_tambem_entra_no_historico():
    ie.juntar([linha()])
    tid = ids()[0]
    db.registrar_classificacoes([(tid, "saida", "Mercado", ("estabelecimento", "a"))])
    db.registrar_classificacoes([(tid, "saida", "Mercado", ("destino", "b"))])
    assert len(db.historico_de(tid)) == 2


def test_historico_sobrevive_a_nova_sincronizacao():
    ie.juntar([linha()])
    db.registrar_classificacoes([(ids()[0], "saida", "Mercado", REGRA)])
    ie.juntar([linha(), linha(data="2026-01-02")])
    assert len(db.historico_de(ids()[0])) == 1


def test_lancamento_removido_leva_o_historico_junto():
    ie.juntar([linha(desc="Sai")])
    db.registrar_classificacoes([(ids()[0], "saida", "Mercado", REGRA)])
    db.substituir_periodo([linha(desc="Outra")], "2026-01-01")
    assert consulta("SELECT COUNT(*) FROM classificacoes") == [(0,)]


def test_categoria_e_regra_existem_uma_vez_so():
    ie.juntar([linha(desc="A"), linha(desc="B")])
    db.registrar_classificacoes([(i, "saida", "Mercado", REGRA) for i in ids()])
    assert consulta("SELECT COUNT(*) FROM categorias") == [(1,)]
    assert consulta("SELECT COUNT(*) FROM regras") == [(1,)]


@pytest.mark.parametrize("regra,origem", [(("estabelecimento", "x"), "arquivo"), (("padrao", "sem regra"), "sistema"), (("destino", "y"), "arquivo")])
def test_origem_da_regra(regra, origem):
    ie.juntar([linha()])
    db.registrar_classificacoes([(ids()[0], "saida", "C", regra)])
    assert db.regras_conhecidas()[regra]["origem"] == origem


def test_confirmacao_pelo_painel_marca_a_regra():
    db.registrar_regra("destino", "loja", "revisao")
    assert db.regras_conhecidas()[("destino", "loja")]["origem"] == "revisao"


def test_regra_ja_conhecida_passa_a_ser_confirmada():
    ie.juntar([linha()])
    db.registrar_classificacoes([(ids()[0], "saida", "C", ("destino", "loja"))])
    db.registrar_regra("destino", "loja", "revisao")
    assert db.regras_conhecidas()[("destino", "loja")]["origem"] == "revisao"


def banco_antigo(*linhas):
    con = sqlite3.connect(db.ARQUIVO)
    con.executescript("""CREATE TABLE transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, titulo TEXT, descricao TEXT, valor TEXT,
                         tipo TEXT DEFAULT '', banco TEXT DEFAULT ''); CREATE INDEX idx_transacoes_data ON transacoes (data);""")
    con.executemany("INSERT INTO transacoes (data, titulo, descricao, valor, tipo, banco) VALUES (?, ?, ?, ?, ?, ?)", linhas)
    con.commit()
    con.close()


ANTIGAS = [("2021-01-01", "Pix", "A", "-10.5", "PIX", ""), ("2021-01-01", "Pix", "A", "-10.5", "PIX", ""), ("2026-01-01", "Compra", "B", "20", "X", "123")]


def test_migra_o_banco_antigo():
    banco_antigo(*ANTIGAS)
    t = db.ler_transacoes()
    assert [(x["data"], x["descricao"], x["valor"], x["tipo"], x["banco"]) for x in t] == [
        ("2021-01-01", "A", -10.5, "PIX", ""), ("2021-01-01", "A", -10.5, "PIX", ""), ("2026-01-01", "B", 20.0, "X", "123")]


def test_migracao_guarda_copia_do_arquivo_antigo():
    banco_antigo(*ANTIGAS)
    db.ler_transacoes()
    assert db.ARQUIVO.with_suffix(".db.bak-v0").exists()


def test_migracao_que_falha_nao_altera_o_banco():
    banco_antigo(*[*ANTIGAS, ("2026-01-02", "Compra", "C", "nao-e-numero", "X", "")])
    with pytest.raises(ArithmeticError):
        db.ler_transacoes()
    con = sqlite3.connect(db.ARQUIVO)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0] == 4
    con.close()


def test_migracao_roda_uma_vez_so():
    banco_antigo(*ANTIGAS)
    db.ler_transacoes()
    primeiro = ids()
    assert ids() == primeiro


def test_painel_grava_a_classificacao_e_mostra_o_motivo():
    gp.REGRAS_PESSOAIS.write_text('{"voce_mesmo": ["ana"]}', encoding="utf-8")
    ie.juntar([linha(desc="Ifood *Sabor")])
    gp.main()
    assert consulta("SELECT categoria, regra_tipo, regra_trecho FROM classificacao_atual") == [("Alimentação", "estabelecimento", "ifood")]
    assert 'Regra de estabelecimento: contém \\"ifood\\"' in gp.SAIDA_HTML.read_text(encoding="utf-8")
    gp.main()
    assert consulta("SELECT COUNT(*) FROM classificacoes") == [(1,)]
