"""Lê o extrato do Inter, classifica cada transação e gera o painel local.

Uso:  python3 scripts/gerar_painel.py
Entrada: dados/financas.db  (histórico de transações, SQLite)
         regras_categorias.json  (estabelecimentos, versionado)
         dados/regras_pessoais.json  (pessoas e seus nomes, opcional, fora do git)
         dados/xp.json  (posição, evolução mensal e conciliação da XP, opcional)
         dados/inter_invest.json  (posição e evolução dos investimentos do Inter, opcional)
Saída:   dados/transacoes.json e painel/index.html
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import base_dados
import sugerir_categorias

import importar_extrato

RAIZ = Path(__file__).resolve().parent.parent
REGRAS = RAIZ / "regras_categorias.json"
REGRAS_PESSOAIS = RAIZ / "dados" / "regras_pessoais.json"
XP = RAIZ / "dados" / "xp.json"
INTER_INV = RAIZ / "dados" / "inter_invest.json"
PLUGGY = RAIZ / "dados" / "pluggy_investimentos.json"
INDICES = RAIZ / "dados" / "indices.json"
RADAR = RAIZ / "dados" / "radar_b3.json"
BASE = RAIZ / "painel" / "base.html"
SAIDA_JSON = RAIZ / "dados" / "transacoes.json"
SAIDA_HTML = RAIZ / "painel" / "index.html"

APORTE = {"Aplicação", "Aplicação em fundos"}
RESGATE = {"Resgate", "Resgate de fundo", "Vencimento Renda Fixa"}
DEVOLUCAO_ENTRADA = {"Estorno", "Pix enviado devolvido"}
DEVOLUCAO_SAIDA = {"Pix recebido devolvido"}

# nomes legíveis para os produtos de investimento que aparecem no extrato do Inter
PRODUTOS_INTER = [
    ("cdb pos di liq", "CDB Pós-DI Liquidez Diária"),
    ("lci ipca", "LCI IPCA+"),
    ("fator macro", "Fundo Fator Macro (multimercado)"),
    ("inter corporate", "Fundo Inter Corporate (renda fixa)"),
]


def produto(tipo, cat, desc):
    """Onde o dinheiro investido está: 'XP' ou o produto do Inter. Vazio para o resto."""
    if tipo not in ("aporte", "resgate"):
        return ""
    if cat == "XP":
        return "XP"
    d = desc.lower()
    return next((nome for trecho, nome in PRODUTOS_INTER if trecho in d), desc)


def montar_pagina():
    """base.html com o estilo e o JavaScript embutidos: o painel continua sendo um arquivo só."""
    pasta = BASE.parent
    return (BASE.read_text(encoding="utf-8")
            .replace("/*__CSS__*/", (pasta / "estilo.css").read_text(encoding="utf-8"))
            .replace("/*__JS__*/", (pasta / "app.js").read_text(encoding="utf-8")))


def carregar_regras():
    r = json.loads(REGRAS.read_text(encoding="utf-8"))
    cats = [(nome, [t.lower() for t in trechos]) for nome, trechos in r["categorias"]]
    p = json.loads(REGRAS_PESSOAIS.read_text(encoding="utf-8")) if REGRAS_PESSOAIS.exists() else {}
    destinos = [(nome.lower(), cat) for nome, cat in p.get("destinos", {}).items()]
    origens = [(nome.lower(), cat) for nome, cat in p.get("origens", {}).items()]
    return cats, destinos, origens, [n.lower() for n in p.get("voce_mesmo", [])]


def por_regra(desc, cats):
    d = desc.lower()
    for nome, trechos in cats:
        for t in trechos:
            if t in d:
                return nome, t
    return None


EMPRESA = re.compile(
    r"\b(ltda|s\.?a|s/a|eireli|epp|me|mei|comercio|servicos|serviços|pagamentos?|pay|tecnologia|digital|brasil|"
    r"industria|distribuidora|associacao|centro|sociedade|instituto|loja|store|bar|restaurante|alimentos?|"
    r"solucoes|gestao|agencia|eventos|turismo|marketplace|banco|bank|cooperativa|condominio|fundacao|club|"
    r"food|games|interactive|ingressos|internet|online)\b",
    re.I,
)


def parece_pessoa(desc):
    """Pix para CPF: nome com 2+ palavras e sem termos de empresa."""
    nome = re.sub(r"^[\d\s:.\-]+|^cp\s*:\s*\d+-", "", desc, flags=re.I)
    return len(nome.split()) >= 2 and not EMPRESA.search(nome)


def carregar_xp():
    """Dados da XP e a lista de Pix do Inter que de fato chegaram lá (conciliados)."""
    if not XP.exists():
        return None, {"envio": Counter(), "retorno": Counter()}
    xp = json.loads(XP.read_text(encoding="utf-8"))
    conc = {
        "envio": Counter((d, round(v, 2)) for d, v in xp.get("envios_inter_para_xp", [])),
        "retorno": Counter((d, round(v, 2)) for d, v in xp.get("retornos_xp_para_inter", [])),
    }
    return xp, conc


def carregar_inter_inv(tx):
    """Posição dos investimentos do Inter com o rendimento de cada mês.

    rendimento do mês = valor no fim do mês - valor no fim do mês anterior - (aplicações - resgates do mês)
    """
    if not INTER_INV.exists():
        return None
    inv = json.loads(INTER_INV.read_text(encoding="utf-8"))
    fluxo = defaultdict(float)
    for t in tx:
        if t[2] == "Investimentos" and t[7] != "XP":
            fluxo[t[0][:7]] += t[4] if t[3] == "aporte" else -t[4]
    ant = None
    for m in inv["mensal"]:
        m["aportes_liquidos"] = round(fluxo[m["mes"]], 2)
        m["rendimento"] = None if ant is None else round(m["valor"] - ant - fluxo[m["mes"]], 2)
        ant = m["valor"]
    return {k: v for k, v in inv.items() if not k.startswith("_")}


def carregar_indices():
    return json.loads(INDICES.read_text(encoding="utf-8")) if INDICES.exists() else None


def acumulado(pcts):
    """Rentabilidade composta, em %, de uma sequência de taxas em %."""
    f = 1.0
    for p in pcts:
        f *= 1 + p / 100
    return (f - 1) * 100


def recalcular_xp(xp, ind):
    """Recalcula, com o CDI e o IPCA do Banco Central, o % do CDI de cada mês, a performance e o resumo por ano.

    Encadeando os meses do portal da XP, o resultado bate com o deles (116,0% do CDI desde a abertura),
    então dá para estender o cálculo aos meses que a sincronização com a Pluggy acrescenta.
    """
    if not xp or not ind:
        return xp
    cdi = sorted(ind["cdi"].items())
    ant = (date.fromisoformat(xp["abertura"]) - timedelta(days=1)).isoformat()
    for r in xp["mensal"]:
        desde = r.get("desde", ant)
        r["cdi_pct"] = round(acumulado(v for d, v in cdi if desde < d <= r["data"]), 4)
        r["ipca_pct"] = ind["ipca"].get(r["data"][:7])
        if r.get("pct_cdi") is None and r["cdi_pct"]:
            r["pct_cdi"] = round(r["rent_pct"] / r["cdi_pct"] * 100, 2)
        ant = r["data"]
    # enquanto só houver meses do portal, ficam os números oficiais da XP (diferem em décimos dos recalculados)
    if not any(r.get("fonte") == "pluggy" for r in xp["mensal"]):
        return xp

    def resumo(linhas):
        rent, c = acumulado(r["rent_pct"] for r in linhas), acumulado(r["cdi_pct"] for r in linhas)
        return {"rendimento": round(sum(r["rendimento"] for r in linhas), 2), "rent_pct": round(rent, 2),
                "pct_cdi": round(rent / c * 100, 2) if c else None,
                "aportes_liquidos": round(sum(r["aportes_liquidos"] for r in linhas), 2)}

    m = xp["mensal"]
    xp["performance"] = {
        "desde_inicio": resumo(m),
        "doze_meses": resumo(m[-12:]),
        "meses_positivos": sum(r["rendimento"] >= 0 for r in m),
        "meses_negativos": sum(r["rendimento"] < 0 for r in m),
        "meses_acima_cdi": sum(r["rent_pct"] >= r["cdi_pct"] for r in m),
        "meses_abaixo_cdi": sum(r["rent_pct"] < r["cdi_pct"] for r in m),
        "melhor_mes_pct": max(r["rent_pct"] for r in m),
        "pior_mes_pct": min(r["rent_pct"] for r in m),
    }
    anos = defaultdict(list)
    for r in m:
        anos[int(r["data"][:4])].append(r)
    xp["por_ano"] = [{"ano": a, **{k: v for k, v in resumo(ls).items()}, "final": ls[-1]["final"]}
                     for a, ls in sorted(anos.items())]
    xp["performance_em"] = m[-1]["data"]
    return xp


def resumo_indices(ind):
    """CDI e IPCA mês a mês e dos últimos 12 meses, para o painel."""
    if not ind:
        return None
    cdi_mes = defaultdict(list)
    for d, v in ind["cdi"].items():
        cdi_mes[d[:7]].append(v)
    cdi_mensal = {m: round(acumulado(vs), 4) for m, vs in sorted(cdi_mes.items())}
    ultimo_cdi = max(ind["cdi"])
    um_ano = (date.fromisoformat(ultimo_cdi) - timedelta(days=365)).isoformat()
    ipca = sorted(ind["ipca"].items())
    return {"cdi_mensal": cdi_mensal, "ipca_mensal": dict(ipca),
            "cdi_12m": round(acumulado(v for d, v in ind["cdi"].items() if d > um_ano), 2),
            "ipca_12m": round(acumulado(v for _, v in ipca[-12:]), 2),
            "cdi_ate": ultimo_cdi, "ipca_ate": ipca[-1][0]}


def ultima_sincronizacao():
    """Data e hora da última sincronização com a Pluggy, gravada por sincronizar_pluggy.py."""
    if not PLUGGY.exists():
        return None
    return json.loads(PLUGGY.read_text(encoding="utf-8")).get("sincronizado_em")


def carregar_contas_proprias():
    """Outras contas suas, pelo ISPB do banco: {"31872495": {"nome": "C6", "recebido": "Categoria"}}.

    Pix do próprio nome vindo de uma delas, com "recebido" definido, conta como entrada nessa
    categoria (ex.: comissão recebida noutra conta). Fica em dados/regras_pessoais.json.
    """
    if not REGRAS_PESSOAIS.exists():
        return {}
    return json.loads(REGRAS_PESSOAIS.read_text(encoding="utf-8")).get("contas_proprias", {})


def carregar_neutros():
    """Movimentações que não são receita nem gasto seu (ex.: dinheiro de terceiros que só passou pela conta).

    Cada regra em dados/regras_pessoais.json → "neutros": {"categoria", "descricao" (trecho), e opcionais
    "titulo", "banco" (ISPB), "desde" e "ate" (AAAA-MM-DD)}.
    """
    if not REGRAS_PESSOAIS.exists():
        return []
    return json.loads(REGRAS_PESSOAIS.read_text(encoding="utf-8")).get("neutros", [])


def carregar_ajustes():
    """Lançamentos manuais que o extrato não mostra sozinho (ex.: a parte de um repasse que era comissão).

    dados/regras_pessoais.json → "ajustes": [{"data", "descricao", "valor", "categoria", "tipo": "entrada"|"saida"}].
    Aparecem no extrato como "Ajuste manual".
    """
    if not REGRAS_PESSOAIS.exists():
        return []
    ajustes = json.loads(REGRAS_PESSOAIS.read_text(encoding="utf-8")).get("ajustes", [])
    return [[a["data"], a["descricao"], a["categoria"], a["tipo"], round(abs(a["valor"]), 2), "Ajuste manual", "Inter", "", "Lançamento manual"]
            for a in ajustes]


def neutro(data, titulo, desc, banco, regras):
    d = desc.lower()
    for r in regras:
        if (r["descricao"].lower() in d and r.get("titulo", titulo) == titulo and r.get("banco", banco) == banco
                and r.get("desde", data) <= data <= r.get("ate", data)):
            return r
    return None


class Resultado(NamedTuple):
    tipo: str  # entrada | saida | aporte | resgate | transf
    categoria: str
    regra: tuple[str, str]  # o que decidiu: (tipo da regra, trecho)


def classificar(data, titulo, desc, valor, cats, destinos, origens, eu, conc, banco="", proprias=None, neutros=()):
    """Decide o tipo e a categoria do lançamento; a primeira regra que bater vence."""
    d = desc.lower()
    if titulo in APORTE:
        return Resultado("aporte", "Inter", ("operacao", titulo))
    if titulo in RESGATE:
        return Resultado("resgate", "Inter", ("operacao", titulo))
    r = neutro(data, titulo, desc, banco or "", neutros)
    if r:
        return Resultado("transf", r["categoria"], ("neutra", r["descricao"].lower()))
    if any(n in d for n in eu):
        # Pix para o próprio CPF: só conta como XP o que foi conciliado com o extrato de lá;
        # o resto foi para outra conta sua e não é gasto nem entrada
        chave = (data, round(abs(valor), 2))
        lado = "envio" if valor < 0 else "retorno"
        if conc[lado][chave] > 0:
            conc[lado][chave] -= 1
            return Resultado("aporte" if valor < 0 else "resgate", "XP", ("conciliacao", "corretora"))
        conta = (proprias or {}).get(banco or "", {})
        if valor > 0 and titulo == "Pix recebido" and conta.get("recebido"):
            return Resultado("entrada", conta["recebido"], ("conta_propria", banco))
        return Resultado("transf", "Entre suas contas", ("padrao", "proprio nome"))
    if titulo in DEVOLUCAO_ENTRADA:
        return Resultado("entrada", "Estornos e devoluções", ("operacao", titulo))
    if titulo in DEVOLUCAO_SAIDA:
        return Resultado("saida", "Estornos e devoluções", ("operacao", titulo))
    if valor > 0:
        origem = next(((nome, c) for nome, c in origens if nome in d), None)
        if origem:
            return Resultado("entrada", origem[1], ("origem", origem[0]))
        if "banco inter" in d:
            return Resultado("entrada", "Banco Inter", ("padrao", "banco inter"))
        return Resultado("entrada", "Pix recebido", ("padrao", "pix recebido"))
    destino = next(((nome, c) for nome, c in destinos if nome in d), None)
    if destino:
        return Resultado("saida", destino[1], ("destino", destino[0]))
    regra = por_regra(desc, cats)
    if regra:
        return Resultado("saida", regra[0], ("estabelecimento", regra[1]))
    if titulo == "Pagamento efetuado":
        return Resultado("saida", "Contas e boletos", ("operacao", titulo))
    if titulo in ("Pix enviado", "Transferência enviada") and parece_pessoa(desc):
        return Resultado("saida", "Pix para pessoas", ("padrao", "pix para pessoa"))
    return Resultado("saida", "Outros", ("padrao", "sem regra"))


TEXTO_REGRA = {
    "estabelecimento": 'Regra de estabelecimento: contém "{}"',
    "destino": 'Regra pessoal de destino: "{}"',
    "origem": 'Regra pessoal de origem: "{}"',
    "neutra": 'Movimentação neutra: contém "{}"',
    "operacao": "Pelo tipo de operação: {}",
    "conta_propria": "Pix de conta sua em outro banco ({})",
    "conciliacao": "Conciliado com o extrato da corretora",
}
TEXTO_PADRAO = {
    "proprio nome": "Pix no seu nome, sem conciliação com a corretora",
    "banco inter": "Recebido do próprio banco",
    "pix recebido": "Pix recebido sem regra de origem",
    "pix para pessoa": "Pix para pessoa física sem regra",
    "sem regra": "Nenhuma regra reconheceu",
}


def motivo(regra, conhecidas=None):
    """Explica em português por que o lançamento ficou nessa categoria."""
    info = (conhecidas or {}).get(regra)
    if info and info["origem"] == "revisao":
        return f"Você confirmou esta categoria em {info['criada_em'][8:10]}/{info['criada_em'][5:7]}/{info['criada_em'][:4]}"
    tipo, trecho = regra
    return TEXTO_PADRAO[trecho] if tipo == "padrao" else TEXTO_REGRA[tipo].format(trecho)


def main():
    cats, destinos, origens, eu = carregar_regras()
    xp, conc = carregar_xp()
    proprias = carregar_contas_proprias()
    neutros = carregar_neutros()
    linhas = importar_extrato.ler_historico()
    tx, resultados = [], []
    for l in linhas:
        v = l["valor"]
        desc = l["descricao"].strip() or l["titulo"]
        tipo, cat, regra = classificar(l["data"], l["titulo"], desc, v, cats, destinos, origens, eu, conc,
                                       l.get("banco"), proprias, neutros)
        prod = produto(tipo, cat, desc)
        if prod:
            cat = "Investimentos"
        resultados.append((l["id"], tipo, cat, regra))
        tx.append([l["data"], desc, cat, tipo, round(abs(v), 2), l["titulo"], "Inter", prod, regra])
    base_dados.registrar_classificacoes(resultados)
    conhecidas = base_dados.regras_conhecidas()
    for t in tx:
        t[8] = motivo(t[8], conhecidas)
    tx = sorted(tx + carregar_ajustes(), key=lambda t: t[0])

    SAIDA_JSON.write_text(json.dumps(tx, ensure_ascii=False), encoding="utf-8")
    ind = carregar_indices()
    privados = ("envios_inter_para_xp", "retornos_xp_para_inter", "fotos_mensais")
    xp_painel = {k: v for k, v in xp.items() if not k.startswith("_") and k not in privados} if xp else None
    xp_painel = recalcular_xp(xp_painel, ind)
    html = (montar_pagina()
            .replace("/*__DADOS__*/[]", json.dumps(tx, ensure_ascii=False))
            .replace("/*__XP__*/null", json.dumps(xp_painel, ensure_ascii=False))
            .replace("/*__INTERINV__*/null", json.dumps(carregar_inter_inv(tx), ensure_ascii=False))
            .replace("/*__SYNC__*/null", json.dumps(ultima_sincronizacao()))
            .replace("/*__INDICES__*/null", json.dumps(resumo_indices(ind)))
            .replace("/*__RADAR__*/null", RADAR.read_text(encoding="utf-8") if RADAR.exists() else "null")
            .replace("/*__REVISAR__*/[]", json.dumps(sugerir_categorias.revisar(tx, parece_pessoa), ensure_ascii=False)))
    SAIDA_HTML.write_text(html, encoding="utf-8")

    # resumo no terminal
    gasto = defaultdict(float)
    for t in tx:
        if t[3] == "saida":
            gasto[t[2]] += t[4]
    total = sum(gasto.values())
    print(f"{len(tx)} transações · {tx[0][0]} a {tx[-1][0]}")
    for c, v in sorted(gasto.items(), key=lambda x: -x[1]):
        print(f"  {c:24s} R$ {v:10.2f}  {v / total:5.1%}")
    outros = Counter(t[1] for t in tx if t[2] == "Outros")
    print("\nMais frequentes em 'Outros':")
    for d, n in outros.most_common(15):
        print(f"  {n:3d}× {d}")
    sobra = [k for lado in conc.values() for k, n in lado.items() if n > 0]
    if sobra:
        print(f"\nAtenção: envios da XP não encontrados no extrato do Inter: {sobra}")
    print(f"\nPainel gerado em {SAIDA_HTML.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
