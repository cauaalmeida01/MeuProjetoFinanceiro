"""Gera a demonstração pública do painel (docs/index.html) com dados 100% fictícios.

Uso:  python3 scripts/gerar_demo.py

Uma pessoa inventada ("Ana Exemplo") com 24 meses de extrato, investimentos no Inter e na XP.
O extrato passa pelo mesmo classificador do painel real (regras_categorias.json), então a demo
mostra o pipeline funcionando de verdade. Não lê nada de dados/: o que é público aqui é só
CDI e IPCA (Banco Central) e cotações de mercado (Yahoo Finance e Fundamentus), buscados na hora.
Os números são gerados com semente fixa, então rodar de novo produz o mesmo extrato.
"""
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_painel as gp  # noqa: E402
import indices_bcb  # noqa: E402
import radar_b3  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "docs" / "index.html"
EU = "Ana Exemplo da Silva"

# estabelecimentos fictícios que caem nas regras de regras_categorias.json: (descrição, faixa de valor, vezes por mês)
GASTOS = [
    ("Ifood *Restaurante Sabor da Casa", (28, 75), 6),
    ("Acaiteria Ponto do Acai Salvador Bra", (14, 30), 3),
    ("Lanchonete Xika Lanche E Refeic Salvador Bra", (8, 22), 4),
    ("Supermercado Bom Preco Salvador Bra", (60, 240), 3),
    ("Hortifruti Feira Livre Salvador Bra", (25, 70), 2),
    ("Uber *Trip Help.Uber.Com", (11, 38), 7),
    ("Posto Shell Paralela Salvador Bra", (80, 160), 1),
    ("Farmacia Pague Menos Salvador Bra", (18, 90), 1),
    ("Netflix.Com", (44.9, 44.9), 1),
    ("Spotify Brasil", (21.9, 21.9), 1),
    ("Cinemark Salvador Shopping", (32, 64), 1),
    ("Sympla Ingressos Show", (60, 180), 0.4),
    ("Barbearia Corte Fino Salvador Bra", (35, 50), 1),
    ("Amazon Marketplace", (40, 260), 0.8),
    ("Shopee Compras Online", (25, 120), 0.6),
    ("Deposito de Bebidas Gelada Salvador Bra", (20, 70), 1),
    ("Udemy Curso Online", (27.9, 59.9), 0.25),
    ("Steam Games", (20, 90), 0.3),
]
PIX_PESSOAS = ["Bruno Costa Ferreira", "Carla Mendes Rocha", "Diego Alves Pinto", "Fernanda Lima Souza", "Gustavo Ramos Teixeira"]
LETRA = "Pagamento efetuado"


def extrato(meses):
    """Linhas no formato do extrato do Inter: (data, titulo, descricao, valor)."""
    rnd = random.Random(42)
    linhas, envios_xp = [], []
    for i, (ano, mes) in enumerate(meses):
        ultimo = (date(ano + mes // 12, mes % 12 + 1, 1) - timedelta(days=1)).day
        dia = lambda a=ano, m=mes, u=ultimo: date(a, m, rnd.randint(1, u)).isoformat()  # noqa: E731
        salario = 3200 + 150 * (i // 6)
        linhas.append((date(ano, mes, 5).isoformat(), "Pix recebido", "Empresa Exemplo Tecnologia Ltda", salario))
        if rnd.random() < 0.35:
            linhas.append((dia(), "Pix recebido", "Freela Cliente Exemplo Ltda", round(rnd.uniform(300, 900), 2)))
        linhas.append((date(ano, mes, 8).isoformat(), "Pix enviado", "Imobiliaria Aluguel Facil Ltda", -1150))
        linhas.append((date(ano, mes, 12).isoformat(), LETRA, "Coelba Energia Eletrica", -round(rnd.uniform(110, 190), 2)))
        for desc, (lo, hi), vezes in GASTOS:
            n = int(vezes) + (1 if rnd.random() < vezes % 1 else 0)
            for _ in range(n):
                linhas.append((dia(), "Compra no débito", desc, -round(rnd.uniform(lo, hi), 2)))
        for _ in range(rnd.randint(1, 3)):
            linhas.append((dia(), "Pix enviado", rnd.choice(PIX_PESSOAS), -round(rnd.uniform(15, 120), 2)))
        if rnd.random() < 0.15:  # um gasto que nenhuma regra conhece, para "Outros" ter algo
            linhas.append((dia(), "Compra no débito", "Loja Variedades Centro Salvador Bra", -round(rnd.uniform(20, 140), 2)))
        # investimentos: aplica no CDB do Inter e manda uma parte para a XP
        linhas.append((date(ano, mes, 6).isoformat(), "Aplicação", "CDB POS DI LIQ", -rnd.choice([300, 400, 500])))
        if i % 2 == 0:
            d = date(ano, mes, 7).isoformat()
            v = rnd.choice([200, 300, 400])
            linhas.append((d, "Pix enviado", EU, -v))
            envios_xp.append([d, v])
        if i % 9 == 4:
            linhas.append((date(ano, mes, 20).isoformat(), "Resgate", "CDB POS DI LIQ", rnd.choice([400, 600])))
    linhas.sort()
    return linhas, envios_xp


def transacoes(linhas, envios_xp):
    """Mesmo caminho do painel real: classificar() e produto() de gerar_painel.py."""
    r = json.loads(gp.REGRAS.read_text(encoding="utf-8"))
    cats = [(nome, [t.lower() for t in trechos]) for nome, trechos in r["categorias"]]
    destinos = [("imobiliaria aluguel", "Moradia")]
    origens = [("empresa exemplo", "Salário"), ("freela cliente", "Freelas")]
    conc = {"envio": Counter((d, round(v, 2)) for d, v in envios_xp), "retorno": Counter()}
    tx = []
    for d, titulo, desc, v in linhas:
        tipo, cat, regra = gp.classificar(d, titulo, desc, v, cats, destinos, origens, [EU.lower()], conc)
        prod = gp.produto(tipo, cat, desc)
        if prod:
            cat = "Investimentos"
        tx.append([d, desc, cat, tipo, round(abs(v), 2), titulo, "Inter", prod, gp.motivo(regra)])
    return tx


def inter_invest(tx, meses):
    fluxo = defaultdict(float)
    for t in tx:
        if t[2] == "Investimentos" and t[7] != "XP":
            fluxo[t[0][:7]] += t[4] if t[3] == "aporte" else -t[4]
    mensal, valor = [], 0.0
    for ano, mes in meses:
        m = f"{ano}-{mes:02d}"
        rend = valor * 0.0095
        valor += fluxo[m] + rend
        mensal.append({"mes": m, "valor": round(valor, 2), "aportes_liquidos": round(fluxo[m], 2),
                       "rendimento": None if len(mensal) == 0 else round(rend, 2)})
    aplicado = sum(fluxo.values())
    cdb, lci, fundo = valor * 0.82, valor * 0.10, valor * 0.08
    return {
        "atualizado_em": date.today().isoformat(), "total": round(valor, 2), "mensal": mensal,
        "posicoes": [
            {"produto": "CDB Pós-DI Liquidez Diária", "classe": "Renda fixa", "valor": round(cdb, 2),
             "liquido": round(cdb - (cdb - aplicado * 0.82) * 0.175, 2), "aplicado": round(aplicado * 0.82, 2),
             "impostos": round((cdb - aplicado * 0.82) * 0.175, 2), "info": "102% do CDI · resgate a qualquer momento"},
            {"produto": "LCI IPCA+", "classe": "Renda fixa", "valor": round(lci, 2), "liquido": round(lci, 2),
             "aplicado": round(aplicado * 0.095, 2), "impostos": 0, "info": "Isenta de IR · vence em 2029"},
            {"produto": "Fundo Multimercado Exemplo", "classe": "Fundos", "valor": round(fundo, 2),
             "liquido": round(fundo * 0.995, 2), "aplicado": round(aplicado * 0.08, 2),
             "impostos": round(fundo * 0.005, 2), "info": "Resgate em D+5"},
        ],
    }


def xp(meses, envios_xp, ind):
    rnd = random.Random(7)
    ap = defaultdict(float)
    for d, v in envios_xp:
        ap[d[:7]] += v
    mensal, final = [], 0.0
    for ano, mes in meses:
        m = f"{ano}-{mes:02d}"
        ultimo = (date(ano + mes // 12, mes % 12 + 1, 1) - timedelta(days=1))
        rent = rnd.gauss(1.1, 1.6) if final else 0.0
        inicial = final
        rend = (inicial + ap[m] / 2) * rent / 100
        final = inicial + ap[m] + rend
        mensal.append({"data": ultimo.isoformat(), "inicial": round(inicial, 2), "aportes_liquidos": ap[m],
                       "rendimento": round(rend, 2), "final": round(final, 2), "rent_pct": round(rent, 2),
                       "pct_cdi": None, "fonte": "pluggy"})
    pos = [("Tesouro Direto", "Selic", "Tesouro Selic 2029", 0.30, 0.26), ("Renda Fixa", "Pós-fixado", "CDB Banco Exemplo 2028", 0.25, 0.23),
           ("Tesouro Direto", "IPCA+", "Tesouro IPCA+ 2035", 0.15, 0.145), ("Ações", "Renda variável", "WEGE3", 0.10, 0.085),
           ("Ações", "Renda variável", "ITSA4", 0.08, 0.075), ("Ações", "Renda variável", "BOVA11", 0.12, 0.11)]
    saldo = 12.40
    patrimonio = final
    investido = patrimonio - saldo
    posicoes = []
    for classe, sub, ativo, peso, peso_apl in pos:
        info = {"Tesouro Selic 2029": "vence 01/03/2029", "CDB Banco Exemplo 2028": "101% do CDI · vence 2028",
                "Tesouro IPCA+ 2035": "vence 15/05/2035"}.get(ativo, "")
        posicoes.append({"classe": classe, "sub": sub, "ativo": ativo, "valor": round(investido * peso, 2),
                         "aplicado": round(sum(ap.values()) * peso_apl, 2), "info": info})
    for p in posicoes:  # ações: quantidade e preço médio coerentes, para o Radar B3
        if p["classe"] == "Ações":
            q = {"WEGE3": 6, "ITSA4": 20, "BOVA11": 2}[p["ativo"]]
            p["info"] = f"{q} ações · PM R$ {p['aplicado'] / q:.2f}".replace(".", ",")
    lanc = [{"data": f"{a}-{m:02d}-15", "descricao": f"DIVIDENDOS {t}", "valor": round(rnd.uniform(0.8, 6), 2), "tipo": "provento"}
            for a, m in meses[-12:] for t in ("ITSA4", "WEGE3") if rnd.random() < 0.45]
    dados = {"atualizado_em": date.today().isoformat(), "abertura": f"{meses[0][0]}-{meses[0][1]:02d}-01",
             "patrimonio": round(patrimonio, 2), "saldo_conta": saldo, "posicoes": posicoes, "mensal": mensal,
             "lancamentos_recentes": lanc, "performance": {}, "por_ano": []}
    return gp.recalcular_xp(dados, ind)


def indices():
    try:
        ini = date.today() - timedelta(days=800)
        return {"cdi": dict(indices_bcb.baixar(12, ini, date.today())),
                "ipca": {d[:7]: v for d, v in indices_bcb.baixar(433, ini, date.today())}}
    except Exception as e:
        sys.exit(f"A demo precisa do CDI e do IPCA do Banco Central, e a API não respondeu ({e}). Tente de novo.")


def radar(dados_xp, ind):
    """Radar com cotações reais das ações fictícias da carteira de exemplo."""
    try:
        minhas = {}
        for p in dados_xp["posicoes"]:
            if p["classe"] == "Ações":
                q = int(p["info"].split()[0])
                minhas[p["ativo"]] = {"quantidade": q, "aplicado": p["aplicado"], "valor": p["valor"],
                                      "proventos": round(sum(l["valor"] for l in dados_xp["lancamentos_recentes"]
                                                             if l["descricao"].endswith(p["ativo"])), 2)}
        acoes = [radar_b3.analisar(t, None, minhas) for t in sorted(minhas)]
        for a in acoes:  # a carteira de exemplo passa a valer o preço de hoje
            a["carteira"]["valor"] = round(a["carteira"]["quantidade"] * a["preco"], 2)
        _, serie, _ = radar_b3.historico("^BVSP")
        ibov = {"nome": "Ibovespa", "pontos": round(serie[-1][1]), "data": serie[-1][0],
                **{k: round(v, 2) if v is not None else None for k, v in radar_b3.metricas(serie).items()},
                "serie": [[d, round(c)] for d, c in serie[::max(1, len(serie) // 60)]]}
        cdi_12m = gp.resumo_indices(ind)["cdi_12m"] if ind else None
        return {"atualizado_em": date.today().isoformat(), "ibovespa": ibov, "cdi_12m": cdi_12m,
                "com_token": False, "acoes": acoes}
    except Exception as e:
        print(f"Sem Radar B3 ({e}); a demo sai sem ele.")
        return None


def main():
    hoje = date.today()
    meses = [((hoje.year * 12 + hoje.month - 1 - k) // 12, (hoje.year * 12 + hoje.month - 1 - k) % 12 + 1) for k in range(23, -1, -1)]
    linhas, envios = extrato(meses)
    linhas = [l for l in linhas if l[0] <= hoje.isoformat()]
    envios = [e for e in envios if e[0] <= hoje.isoformat()]
    tx = transacoes(linhas, envios)
    ind = indices()
    dados_xp = xp(meses, envios, ind)
    html = (gp.montar_pagina()
            .replace("/*__DADOS__*/[]", json.dumps(tx, ensure_ascii=False))
            .replace("/*__XP__*/null", json.dumps(dados_xp, ensure_ascii=False))
            .replace("/*__INTERINV__*/null", json.dumps(inter_invest(tx, meses), ensure_ascii=False))
            .replace("/*__SYNC__*/null", json.dumps(datetime.now().astimezone().isoformat(timespec="seconds")))
            .replace("/*__INDICES__*/null", json.dumps(gp.resumo_indices(ind)))
            .replace("/*__RADAR__*/null", json.dumps(radar(dados_xp, ind), ensure_ascii=False))
            .replace("/*__REVISAR__*/[]", "[]")
            .replace("/*__DEMO__*/false", "true"))
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(html, encoding="utf-8")
    outros = sum(t[4] for t in tx if t[2] == "Outros") / sum(t[4] for t in tx if t[3] == "saida")
    print(f"Demo gerada em {SAIDA.relative_to(RAIZ)}: {len(tx)} transações fictícias, "
          f"{len(set(t[2] for t in tx))} categorias, {outros:.1%} em Outros")


if __name__ == "__main__":
    main()
