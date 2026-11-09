"""Conversão dos dados da Pluggy, resiliência da sincronização e atualização da XP."""
import io
import json
import urllib.error
import urllib.request
from datetime import date

import pytest

import gerar_painel as gp
import sincronizar_pluggy as s


def tx(descricao="Pix enviado  - Maria", valor=-10.5, quando="2026-03-10T15:00:00.000Z", **kw):
    return {"description": descricao, "amount": valor, "date": quando, "operationType": "PIX", "status": "POSTED", **kw}


def test_compra_de_madrugada_em_utc_fica_no_dia_certo():
    """00:18 UTC ainda é 21:18 do dia anterior em Salvador."""
    assert s.para_linha(tx(quando="2026-10-30T00:18:39.000Z"))["data"] == "2026-10-29"


def test_separa_titulo_e_descricao():
    l = s.para_linha(tx("Pix enviado  - Maria Souza"))
    assert (l["titulo"], l["descricao"]) == ("Pix enviado", "Maria Souza")


def test_hifen_no_nome_da_loja_e_mantido():
    assert s.para_linha(tx("Compra no débito - Loja - Centro"))["descricao"] == "Loja - Centro"


def test_espacos_repetidos_sao_removidos():
    assert s.para_linha(tx("Compra no débito - Loja Aurora     Salvador  Bra"))["descricao"] == "Loja Aurora Salvador Bra"


def test_tipo_da_compra():
    assert s.para_linha(tx("Compra no débito - Loja"))["tipo"] == "COMPRA_DEBITO"
    assert s.para_linha(tx("Pix enviado - Loja"))["tipo"] == "PIX"


def test_banco_e_de_quem_pagou_quando_recebo():
    pag = {"payer": {"routingNumberISPB": "111"}, "receiver": {"routingNumberISPB": "222"}}
    assert s.para_linha(tx(valor=10, paymentData=pag))["banco"] == "111"


def test_banco_e_de_quem_recebeu_quando_pago():
    pag = {"payer": {"routingNumberISPB": "111"}, "receiver": {"routingNumberISPB": "222"}}
    assert s.para_linha(tx(valor=-10, paymentData=pag))["banco"] == "222"


def test_compra_sem_dados_de_pagamento_fica_sem_banco():
    assert s.para_linha(tx(paymentData=None))["banco"] == ""


@pytest.fixture
def pluggy():
    p = s.Pluggy.__new__(s.Pluggy)
    p.chave = "chave"
    return p


@pytest.fixture
def esperas(monkeypatch):
    lista = []
    monkeypatch.setattr(s.time, "sleep", lista.append)
    return lista


def erro_http(codigo):
    return urllib.error.HTTPError("u", codigo, "m", {}, io.BytesIO(b"detalhe"))


def roteiro(monkeypatch, eventos):
    """Faz o urlopen devolver cada evento em ordem; exceções são levantadas."""
    chamadas = []

    def falso(req, timeout=None):
        chamadas.append(req)
        e = eventos[len(chamadas) - 1]
        if isinstance(e, Exception):
            raise e
        return e

    monkeypatch.setattr(urllib.request, "urlopen", falso)
    return chamadas


def test_tenta_de_novo_quando_a_pluggy_fica_instavel(pluggy, esperas, monkeypatch, resposta):
    chamadas = roteiro(monkeypatch, [erro_http(503), resposta(b'{"ok": 1}')])
    assert pluggy.chamar("GET", "/x") == {"ok": 1}
    assert len(chamadas) == 2
    assert esperas == [5]


def test_tenta_de_novo_sem_internet(pluggy, esperas, monkeypatch, resposta):
    roteiro(monkeypatch, [urllib.error.URLError("dns"), TimeoutError(), resposta(b"{}")])
    assert pluggy.chamar("GET", "/x") == {}
    assert esperas == [5, 15]


def test_desiste_depois_de_quatro_tentativas(pluggy, esperas, monkeypatch):
    chamadas = roteiro(monkeypatch, [urllib.error.URLError("dns")] * 4)
    with pytest.raises(RuntimeError, match="sem conexão"):
        pluggy.chamar("GET", "/x")
    assert len(chamadas) == 4
    assert esperas == [5, 15, 30]


def test_erro_do_pedido_nao_e_repetido(pluggy, esperas, monkeypatch):
    chamadas = roteiro(monkeypatch, [erro_http(400)])
    with pytest.raises(RuntimeError, match="400"):
        pluggy.chamar("GET", "/x?segredo=1")
    assert len(chamadas) == 1
    assert esperas == []


def test_mensagem_de_erro_nao_expoe_parametros_da_url(pluggy, esperas, monkeypatch):
    roteiro(monkeypatch, [erro_http(401)])
    with pytest.raises(RuntimeError) as e:
        pluggy.chamar("GET", "/x?segredo=1")
    assert "segredo" not in str(e.value)


def test_envia_a_chave_da_api(pluggy, monkeypatch, resposta):
    chamadas = roteiro(monkeypatch, [resposta(b"{}")])
    pluggy.chamar("GET", "/x")
    assert chamadas[0].get_header("X-api-key") == "chave"


def test_segue_a_paginacao_ate_o_fim(pluggy, monkeypatch):
    paginas = iter([{"results": [1, 2], "next": "?after=abc"}, {"results": [3], "next": None}])
    caminhos = []

    def falso(metodo, caminho):
        caminhos.append(caminho)
        return next(paginas)

    monkeypatch.setattr(pluggy, "chamar", falso)
    assert pluggy.transacoes("conta") == [1, 2, 3]
    assert caminhos == ["/v2/transactions?accountId=conta", "/v2/transactions?after=abc"]


def test_espera_a_internet_voltar(monkeypatch, esperas):
    respostas = iter([OSError(), OSError(), [("ok",)]])

    def falso(*a):
        r = next(respostas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(s.socket, "getaddrinfo", falso)
    s.esperar_rede()
    assert esperas == [15, 15]


def test_desiste_de_esperar_a_internet(monkeypatch, esperas):
    def falso(*a):
        raise OSError

    relogio = iter([0, 10, 301])
    monkeypatch.setattr(s.socket, "getaddrinfo", falso)
    monkeypatch.setattr(s.time, "monotonic", lambda: next(relogio))
    with pytest.raises(RuntimeError, match="sem internet"):
        s.esperar_rede()


def test_env_incompleto(monkeypatch):
    s.ENV.write_text("PLUGGY_CLIENT_ID=abc\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="PLUGGY_CLIENT_SECRET"):
        s.ler_env()


def test_env_aceita_espacos_e_aspas():
    s.ENV.write_text("PLUGGY_CLIENT_ID = 'abc'\nPLUGGY_CLIENT_SECRET=\"d=e\"\n# comentario=1\nPLUGGY_ITEM_IDS=1,2\n", encoding="utf-8")
    assert s.ler_env() == {"PLUGGY_CLIENT_ID": "abc", "PLUGGY_CLIENT_SECRET": "d=e", "PLUGGY_ITEM_IDS": "1,2"}


@pytest.mark.parametrize("pos,nome", [
    ({"type": "EQUITY", "code": "PETR4"}, "PETR4"),
    ({"type": "FIXED_INCOME", "subtype": "TREASURY", "name": "LTN", "dueDate": "2027-01-01T03:00:00.000Z"}, "LTN jan/2027"),
    ({"type": "FIXED_INCOME", "subtype": "TREASURY", "name": "NTNB PRINC", "dueDate": "2032-08-15T03:00:00.000Z"}, "NTN-B Principal ago/2032"),
    ({"type": "FIXED_INCOME", "subtype": "CDB", "issuer": "BANCO XP S.A", "dueDate": "2027-10-18T03:00:00.000Z"}, "CDB Banco XP out/2027"),
])
def test_nome_do_ativo(pos, nome):
    assert s.nome_ativo(pos) == nome


@pytest.mark.parametrize("desc,valor,esperado", [
    ("JUROS S/ CAPITAL DE CLIENTES ITUB4 S/   1", 0.01, ("JUROS S/ CAPITAL ITUB4", "provento")),
    ("DIVIDENDOS DE CLIENTES SCAR3 S/  4", 28.4, ("DIVIDENDOS SCAR3", "provento")),
    ("RENDIMENTOS DE CLIENTES PETR4 S/  3", 0.05, ("RENDIMENTOS PETR4", "provento")),
    ("OPERAÇÕES EM BOLSA PR 16/07/2026 NOTA Nº 140357637", -108.88, ("Operações em bolsa (nota 140357637)", "compra")),
    ("OPERAÇÕES EM BOLSA PR 13/04/2026 NOTA Nº 134164474", 283.81, ("Operações em bolsa (nota 134164474)", "venda")),
    ("COMPRA TESOURO DIRETO CLIENTES", -135.2, ("Compra Tesouro Direto", "compra")),
    ("Transferência recebida da conta digital", 100, ("Transferência recebida da conta digital", "transferencia")),
    ("TED BCO 348 AGE 1 CTA 1 - RETIRADA EM C/C", -150, ("Transferência enviada para a conta digital", "transferencia")),
    ("Algo Novo", 1, ("Algo Novo", "outro")),
])
def test_lancamentos_da_xp(desc, valor, esperado):
    assert s.lancamento_xp({"description": desc, "amount": valor}) == esperado


class FalsaPluggy:
    def __init__(self, movimentos):
        self.movimentos = movimentos

    def transacoes(self, conta):
        return self.movimentos[conta]


CONTAS = [{"id": "digital", "balance": 0}, {"id": "invest", "balance": 4.83}]
EU = ["ana exemplo"]


def mov(desc, valor, quando="2026-10-16T12:00:00.000Z"):
    return {"description": desc, "amount": valor, "date": quando}


def base_xp(**kw):
    return {"atualizado_em": "2026-10-01", "lancamentos_recentes": [], "envios_inter_para_xp": [["2024-11-28", 400]], "retornos_xp_para_inter": [],
            "mensal": [{"data": "2026-10-21", "final": 500}],
            "posicoes": [{"classe": "Ações", "sub": "RV", "ativo": "PETR4", "valor": 1, "aplicado": 92.88, "info": "3 ações · PM R$ 30,96"},
                         {"classe": "Ações", "sub": "RV", "ativo": "VENDIDA3", "valor": 1, "aplicado": 1, "info": "1 ação · PM R$ 1,00"}], **kw}


def acao(codigo="PETR4", qtd=3, valor=156.6):
    return {"type": "EQUITY", "code": codigo, "amount": valor, "quantity": qtd, "amountOriginal": None}


def rodar_xp(movimentos=None, posicoes=None, dados=None):
    if dados is not None or not gp.XP.exists():
        gp.XP.write_text(json.dumps(dados or base_xp()), encoding="utf-8")
    s.atualizar_xp(FalsaPluggy(movimentos or {"digital": [mov("Pix recebido de Ana", 1)], "invest": []}), CONTAS, posicoes or [acao()], EU)
    return json.loads(gp.XP.read_text(encoding="utf-8"))


def test_xp_atualiza_valor_e_mantem_preco_medio():
    p = rodar_xp()["posicoes"][0]
    assert (p["valor"], p["aplicado"], p["info"]) == (156.6, 92.88, "3 ações · PM R$ 30,96")


def test_xp_remove_posicao_vendida():
    assert [p["ativo"] for p in rodar_xp()["posicoes"]] == ["PETR4"]


def test_xp_quantidade_mudou_preco_medio_fica_desconhecido():
    p = rodar_xp(posicoes=[acao(qtd=5)])["posicoes"][0]
    assert p["aplicado"] is None
    assert p["info"] == "5 ações"


def test_xp_posicao_nova_ganha_classe():
    novo = {"type": "FIXED_INCOME", "subtype": "TREASURY", "name": "LFT", "rateType": "SELIC", "amount": 200, "amountOriginal": 150,
            "dueDate": "2029-03-01T03:00:00.000Z"}
    p = rodar_xp(posicoes=[novo])["posicoes"][0]
    assert (p["ativo"], p["classe"], p["sub"], p["aplicado"]) == ("LFT mar/2029", "Tesouro Direto", "Selic", 150)


def test_xp_patrimonio_e_posicoes_mais_saldo():
    x = rodar_xp()
    assert x["saldo_conta"] == 4.83
    assert x["patrimonio"] == pytest.approx(161.43)


def test_xp_concilia_pix_vindo_do_proprio_nome():
    m = {"digital": [mov("Pix recebido de Ana Exemplo", 1200)], "invest": []}
    assert ["2026-10-16", 1200] in rodar_xp(m)["envios_inter_para_xp"]


def test_xp_nao_duplica_conciliacao_em_nova_sincronizacao():
    m = {"digital": [mov("Pix recebido de Ana Exemplo", 1200)], "invest": []}
    rodar_xp(m)
    assert rodar_xp(m)["envios_inter_para_xp"].count(["2026-10-16", 1200]) == 1


def test_xp_preserva_conciliacao_antiga():
    assert ["2024-11-28", 400] in rodar_xp()["envios_inter_para_xp"]


def test_xp_ted_da_corretora_nao_e_envio_do_inter():
    m = {"digital": [mov("Pix recebido de Ana", 1), mov("TED recebida de ANA EXEMPLO", 150)], "invest": []}
    assert ["2026-10-16", 150] not in rodar_xp(m)["envios_inter_para_xp"]


def test_xp_pix_de_terceiro_nao_e_envio():
    m = {"digital": [mov("Pix recebido de Fulano", 50)], "invest": []}
    assert ["2026-10-16", 50] not in rodar_xp(m)["envios_inter_para_xp"]


def test_xp_pix_para_si_saindo_da_corretora_e_retorno():
    m = {"digital": [mov("Pix recebido de Fulano", 1), mov("Pix enviado para Ana Exemplo", -80)], "invest": []}
    assert rodar_xp(m)["retornos_xp_para_inter"] == [["2026-10-16", 80]]


def test_xp_mantem_descricao_melhor_do_portal():
    antigo = {"data": "2026-10-16", "descricao": "Compra CDB Banco XP out/2027", "valor": -1000, "tipo": "compra"}
    m = {"digital": [mov("Pix recebido de Ana", 1)], "invest": [mov("COMPRA CDB | X", -1000)]}
    assert rodar_xp(m, dados=base_xp(lancamentos_recentes=[antigo]))["lancamentos_recentes"] == [antigo]


def test_xp_guarda_lancamentos_anteriores_a_janela():
    antigo = {"data": "2025-01-01", "descricao": "Antigo", "valor": 1, "tipo": "provento"}
    m = {"digital": [mov("Pix recebido de Ana", 1)], "invest": [mov("DIVIDENDOS DE CLIENTES ITUB4 S/ 1", 2)]}
    assert [l["descricao"] for l in rodar_xp(m, dados=base_xp(lancamentos_recentes=[antigo]))["lancamentos_recentes"]] == ["Antigo", "DIVIDENDOS ITUB4"]


def hoje(monkeypatch, ano, mes, dia):
    class Data(date):
        @classmethod
        def today(cls):
            return cls(ano, mes, dia)

    monkeypatch.setattr(s, "date", Data)


def test_xp_mes_coberto_pelo_portal_nao_ganha_linha(monkeypatch):
    hoje(monkeypatch, 2026, 10, 31)
    x = rodar_xp()
    assert len(x["mensal"]) == 1
    assert x["fotos_mensais"]["2026-10"][0] == "2026-10-31"


def test_xp_mes_seguinte_calcula_aporte_e_rendimento(monkeypatch):
    hoje(monkeypatch, 2026, 10, 31)
    rodar_xp()
    hoje(monkeypatch, 2026, 11, 30)
    m = {"digital": [mov("Pix recebido de Ana", 1)],
         "invest": [mov("Transferência recebida da conta digital", 100, "2026-11-10T12:00:00.000Z"),
                    mov("Transferência recebida da conta digital", 999, "2026-10-20T12:00:00.000Z")]}
    linha = rodar_xp(m, posicoes=[acao(valor=270)])["mensal"][-1]
    assert (linha["desde"], linha["data"], linha["fonte"]) == ("2026-10-31", "2026-11-30", "pluggy")
    assert linha["aportes_liquidos"] == 100  # a transferência de outubro já pertence ao mês anterior
    assert linha["inicial"] == pytest.approx(161.43)
    assert linha["rendimento"] == pytest.approx(274.83 - 161.43 - 100)
    assert linha["pct_cdi"] is None


def test_xp_nova_sincronizacao_no_mesmo_mes_nao_duplica_linha(monkeypatch):
    hoje(monkeypatch, 2026, 10, 31)
    rodar_xp()
    hoje(monkeypatch, 2026, 11, 15)
    rodar_xp()
    hoje(monkeypatch, 2026, 11, 30)
    x = rodar_xp()
    assert len([r for r in x["mensal"] if r.get("fonte") == "pluggy"]) == 1


def test_xp_converte_fotos_no_formato_antigo(monkeypatch):
    hoje(monkeypatch, 2026, 11, 30)
    x = rodar_xp(dados=base_xp(fotos_mensais={"2026-10": 100.0}))
    assert x["fotos_mensais"]["2026-10"] == ["2026-10-28", 100.0]


class SyncFalsa:
    """Dois itens: 'inter' funciona; o comportamento de 'xp' depende do teste."""

    falha_xp = False

    def __init__(self, *a):
        pass

    def chamar(self, metodo, caminho):
        if "/items/xp" in caminho and self.falha_xp:
            raise RuntimeError("sem conexão com a Pluggy")
        if caminho.startswith("/items/"):
            return {"status": "UPDATED", "lastUpdatedAt": "2026-11-07T00:00:00Z"}
        if caminho.startswith("/accounts"):
            return {"results": [{"id": "c1", "type": "BANK", "name": "BANCO INTER"}] if "inter" in caminho else []}
        return {"results": []}

    def transacoes(self, conta):
        return [tx("Pix enviado - Maria", quando="2026-11-01T15:00:00Z"), tx("Pix enviado - João", quando="2026-11-02T15:00:00Z"),
                tx("Pix enviado - Pendente", quando="2026-11-02T15:00:00Z", status="PENDING")]


@pytest.fixture
def sync(monkeypatch):
    s.ENV.write_text("PLUGGY_CLIENT_ID=a\nPLUGGY_CLIENT_SECRET=b\nPLUGGY_ITEM_IDS=inter, xp\n", encoding="utf-8")
    juntados = []
    monkeypatch.setattr(s, "Pluggy", SyncFalsa)
    monkeypatch.setattr(SyncFalsa, "falha_xp", False)
    monkeypatch.setattr(s, "esperar_rede", lambda: None)
    monkeypatch.setattr(s.importar_extrato, "juntar", lambda l, i: juntados.append((l, i)))
    monkeypatch.setattr(s.indices_bcb, "atualizar", lambda: {"cdi": {"2026-11-01": 1}, "ipca": {"2026-10": 1}})
    monkeypatch.setattr(s.radar_b3, "main", lambda a: None)
    monkeypatch.setattr(s.gerar_painel, "main", lambda: None)
    monkeypatch.setattr(s.gerar_painel, "carregar_regras", lambda: ([], [], [], ["ana"]))
    return juntados


def test_sync_salva_o_inter_mesmo_se_a_xp_falhar(sync, monkeypatch, capsys):
    monkeypatch.setattr(SyncFalsa, "falha_xp", True)
    s.main()
    assert len(sync[0][0]) == 2
    assert "item xp falhou" in capsys.readouterr().out


def test_sync_ignora_transacao_pendente(sync):
    s.main()
    assert [l["descricao"] for l in sync[0][0]] == ["Maria", "João"]


def test_sync_primeiro_dia_da_janela_fica_com_o_historico(sync):
    s.main()
    assert sync[0][1] == "2026-11-02"


def test_sync_grava_horario(sync):
    s.main()
    assert "sincronizado_em" in json.loads(s.INVESTIMENTOS.read_text(encoding="utf-8"))


def test_sync_sem_nenhum_banco_nao_altera_nada(sync, monkeypatch):
    def falha(self, m, c):
        raise RuntimeError("fora do ar")

    monkeypatch.setattr(SyncFalsa, "chamar", falha)
    with pytest.raises(RuntimeError, match="nada foi alterado"):
        s.main()
    assert sync == []
    assert not s.INVESTIMENTOS.exists()


def test_sync_falha_no_banco_central_nao_impede_o_painel(sync, monkeypatch, capsys):
    gerados = []

    def falha():
        raise OSError("bcb fora")

    monkeypatch.setattr(s.indices_bcb, "atualizar", falha)
    monkeypatch.setattr(s.gerar_painel, "main", lambda: gerados.append(1))
    s.main()
    assert gerados == [1]
    assert "CDI/IPCA" in capsys.readouterr().out


def test_sync_falha_no_radar_nao_impede_o_painel(sync, monkeypatch, capsys):
    gerados = []

    def falha(a):
        raise OSError("yahoo fora")

    monkeypatch.setattr(s.radar_b3, "main", falha)
    monkeypatch.setattr(s.gerar_painel, "main", lambda: gerados.append(1))
    s.main()
    assert gerados == [1]
    assert "Radar B3" in capsys.readouterr().out


def test_sync_nao_roda_duas_vezes_ao_mesmo_tempo(sync, capsys):
    import fcntl

    trava = open(s.RAIZ / "dados" / ".sincronizando", "w")
    fcntl.flock(trava, fcntl.LOCK_EX)
    s.main()
    fcntl.flock(trava, fcntl.LOCK_UN)
    trava.close()
    assert sync == []
    assert "cancelada" in capsys.readouterr().out


def aplicacao(tipo="CDB", valor=110.0, aplicado=100.0, liquido=108.0, venc="2027-07-30T03:00:00.000Z", ir=2.0, taxa=102):
    return {"type": "FIXED_INCOME", "subtype": tipo, "name": f"{tipo} - BANCO", "amount": valor, "amountOriginal": aplicado, "balance": liquido,
            "taxes": ir, "taxes2": 0, "dueDate": venc, "rate": taxa, "rateType": "CDI", "status": "ACTIVE"}


FUNDO = {"type": "MUTUAL_FUND", "subtype": "MULTIMARKET_FUND", "name": "Fator Macro FIC FIM", "amount": 155.0, "amountOriginal": None,
         "balance": 154.0, "taxes": 1.0, "taxes2": 0, "status": "ACTIVE"}


def inter_base():
    gp.INTER_INV.write_text(json.dumps({
        "total": 1, "atualizado_em": "2026-10-28", "mensal": [{"mes": "2026-10", "valor": 1}],
        "posicoes": [{"produto": "Fundo Fator Macro (multimercado)", "aplicado": 150.0}]}), encoding="utf-8")


def inter_salvo():
    return json.loads(gp.INTER_INV.read_text(encoding="utf-8"))


def test_inter_soma_as_aplicacoes_do_mesmo_produto(monkeypatch):
    hoje(monkeypatch, 2026, 11, 8)
    inter_base()
    s.atualizar_inter([aplicacao(), aplicacao(valor=220, aplicado=200, liquido=216, venc="2028-09-04T03:00:00.000Z", ir=4)])
    i = inter_salvo()
    assert len(i["posicoes"]) == 1
    p = i["posicoes"][0]
    assert (p["valor"], p["aplicado"], p["liquido"], p["impostos"]) == (330, 300, 324, 6)
    assert p["info"] == "102% do CDI · 2 aplicações · vencimentos de 07/2027 a 09/2028"


def test_inter_fundo_mantem_o_aplicado_conhecido(monkeypatch):
    hoje(monkeypatch, 2026, 11, 8)
    inter_base()
    s.atualizar_inter([FUNDO])
    p = inter_salvo()["posicoes"][0]
    assert (p["produto"], p["aplicado"], p["classe"]) == ("Fundo Fator Macro", 150, "Fundos")


def test_inter_guarda_o_valor_do_mes_sem_duplicar(monkeypatch):
    hoje(monkeypatch, 2026, 11, 8)
    inter_base()
    s.atualizar_inter([aplicacao()])
    s.atualizar_inter([aplicacao(valor=111)])
    i = inter_salvo()
    assert i["mensal"] == [{"mes": "2026-10", "valor": 1}, {"mes": "2026-11", "valor": 111}]
    assert i["total"] == 111


def test_inter_sem_posicoes_nao_apaga_o_que_existe():
    inter_base()
    s.atualizar_inter([])
    assert inter_salvo()["total"] == 1


def test_valor_grande_nao_perde_centavos():
    """O formato anterior cortava em 6 dígitos significativos: 12345.67 virava 12345.7."""
    assert s.para_linha(tx(valor=-12345.67))["valor"] == "-12345.67"
