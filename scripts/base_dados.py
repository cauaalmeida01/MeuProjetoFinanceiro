"""Banco de dados do painel (dados/financas.db, SQLite): esquema, migração e consultas.

Modelo:
    contas          de onde vem cada lançamento
    transacoes      o que o banco informou; valores em centavos e identidade estável (chave)
    categorias      cada categoria existe uma vez só
    regras          o que pode classificar um lançamento, com origem e data
    classificacoes  histórico: uma linha nova só quando o resultado de um lançamento muda

As regras continuam sendo editadas nos arquivos JSON; a tabela `regras` as registra quando
são usadas, para que cada classificação aponte para o motivo dela.
"""
import shutil
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent.parent / "dados" / "financas.db"
VERSAO = 1
ORIGEM_POR_TIPO = {"estabelecimento": "arquivo", "destino": "arquivo", "origem": "arquivo", "neutra": "arquivo", "conta_propria": "arquivo"}

ESQUEMA = [
    """CREATE TABLE contas (
        id INTEGER PRIMARY KEY,
        instituicao TEXT NOT NULL,
        nome TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('corrente', 'investimento')),
        UNIQUE (instituicao, nome)
    )""",
    """CREATE TABLE categorias (
        id INTEGER PRIMARY KEY,
        nome TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE regras (
        id INTEGER PRIMARY KEY,
        tipo TEXT NOT NULL,
        trecho TEXT NOT NULL,
        origem TEXT NOT NULL CHECK (origem IN ('arquivo', 'revisao', 'sistema')),
        criada_em TEXT NOT NULL,
        UNIQUE (tipo, trecho)
    )""",
    """CREATE TABLE transacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conta_id INTEGER NOT NULL REFERENCES contas (id),
        chave TEXT NOT NULL UNIQUE,
        data TEXT NOT NULL CHECK (length(data) = 10),
        titulo TEXT NOT NULL,
        descricao TEXT NOT NULL,
        valor_centavos INTEGER NOT NULL,
        operacao TEXT NOT NULL DEFAULT '',
        banco_contraparte TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX idx_transacoes_data ON transacoes (data)",
    """CREATE TABLE classificacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transacao_id INTEGER NOT NULL REFERENCES transacoes (id) ON DELETE CASCADE,
        categoria_id INTEGER NOT NULL REFERENCES categorias (id),
        regra_id INTEGER NOT NULL REFERENCES regras (id),
        tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida', 'aporte', 'resgate', 'transf')),
        criada_em TEXT NOT NULL
    )""",
    "CREATE INDEX idx_classificacoes_transacao ON classificacoes (transacao_id, id)",
    """CREATE VIEW classificacao_atual AS
        SELECT c.transacao_id, c.tipo, cat.nome AS categoria, r.tipo AS regra_tipo, r.trecho AS regra_trecho,
               r.origem AS regra_origem, r.criada_em AS regra_criada_em, c.criada_em
        FROM classificacoes c
        JOIN categorias cat ON cat.id = c.categoria_id
        JOIN regras r ON r.id = c.regra_id
        WHERE c.id = (SELECT MAX(id) FROM classificacoes WHERE transacao_id = c.transacao_id)""",
    "INSERT INTO contas (id, instituicao, nome, tipo) VALUES (1, 'Inter', 'Conta corrente', 'corrente')",
]
INSERIR = """INSERT INTO transacoes (conta_id, chave, data, titulo, descricao, valor_centavos, operacao, banco_contraparte)
             VALUES (1, ?, ?, ?, ?, ?, ?, ?)"""


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def centavos(valor):
    """Dinheiro como número inteiro de centavos, sem os arredondamentos de ponto flutuante."""
    return int((Decimal(str(valor)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def preparar(linhas):
    """Acrescenta centavos e a chave estável. n separa lançamentos idênticos no mesmo dia."""
    vistos = Counter()
    saida = []
    for l in linhas:
        c = centavos(l["valor"])
        base = (l["data"], l["titulo"], l["descricao"], c)
        vistos[base] += 1
        saida.append({**l, "centavos": c, "chave": "|".join(map(str, base + (vistos[base],)))})
    return saida


@contextmanager
def transacao(con):
    """Grupo de escritas que acontece por inteiro ou não acontece."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.rollback()
        raise
    con.commit()


def migrar(con):
    """Leva o arquivo até a versão atual do esquema, em uma única transação."""
    if con.execute("PRAGMA user_version").fetchone()[0] >= VERSAO:
        return
    antiga = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transacoes'").fetchone()
    if antiga:
        copia = ARQUIVO.with_suffix(".db.bak-v0")
        if not copia.exists():
            shutil.copy(ARQUIVO, copia)
    with transacao(con):
        if con.execute("PRAGMA user_version").fetchone()[0] >= VERSAO:  # outro processo migrou enquanto este esperava
            return
        linhas = []
        if antiga:
            linhas = [dict(l) for l in con.execute("SELECT data, titulo, descricao, valor, tipo, banco FROM transacoes ORDER BY data, id")]
            con.execute("DROP TABLE transacoes")
        for comando in ESQUEMA:
            con.execute(comando)
        con.executemany(INSERIR, [(l["chave"], l["data"], l["titulo"], l["descricao"], l["centavos"], l["tipo"], l["banco"]) for l in preparar(linhas)])
        if con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0] != len(linhas):
            raise RuntimeError("migração incompleta: a contagem de transações não bate")
        con.execute(f"PRAGMA user_version = {VERSAO}")


@contextmanager
def conexao():
    con = sqlite3.connect(ARQUIVO, timeout=30, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        migrar(con)
        yield con
    finally:
        con.close()


def ler_transacoes():
    """Todas as transações, em ordem de data e, no mesmo dia, de chegada."""
    with conexao() as con:
        return [{**dict(l), "valor": l["valor_centavos"] / 100} for l in con.execute(
            """SELECT id, data, titulo, descricao, valor_centavos, operacao AS tipo, banco_contraparte AS banco
               FROM transacoes ORDER BY data, id""")]


def substituir_periodo(novas, inicio):
    """Atualiza o período: mantém o id de quem continua, remove o que sumiu e insere o que é novo."""
    linhas = preparar(novas)
    chaves = {l["chave"] for l in linhas}
    with conexao() as con, transacao(con):
        atuais = {l["chave"]: l for l in con.execute("SELECT id, chave, operacao, banco_contraparte FROM transacoes WHERE data >= ?", (inicio,))}
        removidas = [(l["id"],) for c, l in atuais.items() if c not in chaves]
        con.executemany("DELETE FROM transacoes WHERE id = ?", removidas)
        inseridas = 0
        for l in linhas:
            operacao, banco = l.get("tipo") or "", l.get("banco") or ""
            atual = atuais.get(l["chave"])
            if atual is None:
                con.execute(INSERIR, (l["chave"], l["data"], l["titulo"], l["descricao"], l["centavos"], operacao, banco))
                inseridas += 1
            elif (atual["operacao"], atual["banco_contraparte"]) != (operacao, banco):
                con.execute("UPDATE transacoes SET operacao = ?, banco_contraparte = ? WHERE id = ?", (operacao, banco, atual["id"]))
        total, primeira, ultima = con.execute("SELECT COUNT(*), MIN(data), MAX(data) FROM transacoes").fetchone()
    return {"inseridas": inseridas, "removidas": len(removidas), "mantidas": len(linhas) - inseridas,
            "total": total, "primeira": primeira, "ultima": ultima}


def _regra_id(con, tipo, trecho, origem=None):
    origem = origem or ORIGEM_POR_TIPO.get(tipo, "sistema")
    con.execute("INSERT OR IGNORE INTO regras (tipo, trecho, origem, criada_em) VALUES (?, ?, ?, ?)", (tipo, trecho, origem, agora()))
    return con.execute("SELECT id FROM regras WHERE tipo = ? AND trecho = ?", (tipo, trecho)).fetchone()[0]


def registrar_regra(tipo, trecho, origem):
    """Registra uma regra criada por uma ação do usuário, guardando quando foi confirmada."""
    with conexao() as con, transacao(con):
        regra = _regra_id(con, tipo, trecho, origem)
        con.execute("UPDATE regras SET origem = ?, criada_em = ? WHERE id = ? AND origem <> ?", (origem, agora(), regra, origem))


def registrar_classificacoes(itens):
    """itens: (transacao_id, tipo, categoria, (regra_tipo, trecho)). Só grava o que mudou; devolve quantos."""
    with conexao() as con, transacao(con):
        atuais = {l["transacao_id"]: (l["tipo"], l["categoria"], l["regra_tipo"], l["regra_trecho"]) for l in con.execute("SELECT * FROM classificacao_atual")}
        categorias, regras, novas = {}, {}, 0
        for transacao_id, tipo, categoria, regra in itens:
            if atuais.get(transacao_id) == (tipo, categoria, *regra):
                continue
            if categoria not in categorias:
                con.execute("INSERT OR IGNORE INTO categorias (nome) VALUES (?)", (categoria,))
                categorias[categoria] = con.execute("SELECT id FROM categorias WHERE nome = ?", (categoria,)).fetchone()[0]
            if regra not in regras:
                regras[regra] = _regra_id(con, *regra)
            con.execute("INSERT INTO classificacoes (transacao_id, categoria_id, regra_id, tipo, criada_em) VALUES (?, ?, ?, ?, ?)",
                        (transacao_id, categorias[categoria], regras[regra], tipo, agora()))
            novas += 1
    return novas


def regras_conhecidas():
    """{(tipo, trecho): {origem, criada_em}}, para explicar cada categoria no painel."""
    with conexao() as con:
        return {(l["tipo"], l["trecho"]): {"origem": l["origem"], "criada_em": l["criada_em"]} for l in con.execute("SELECT * FROM regras")}


def historico_de(transacao_id):
    """Todas as classificações de um lançamento, da mais antiga para a mais recente."""
    with conexao() as con:
        return [dict(l) for l in con.execute(
            """SELECT c.criada_em, c.tipo, cat.nome AS categoria, r.tipo AS regra_tipo, r.trecho AS regra_trecho
               FROM classificacoes c JOIN categorias cat ON cat.id = c.categoria_id JOIN regras r ON r.id = c.regra_id
               WHERE c.transacao_id = ? ORDER BY c.id""", (transacao_id,))]
