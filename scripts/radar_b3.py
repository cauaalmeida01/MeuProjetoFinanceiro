"""Radar B3: preço, desempenho, risco, proventos e fundamentos das ações que você tem ou acompanha.

Uso:
    python3 scripts/radar_b3.py                      atualiza o radar (dados/radar_b3.json)
    python3 scripts/radar_b3.py --adicionar WEGE3 ...  passa a acompanhar essas ações
    python3 scripts/radar_b3.py --remover WEGE3 ...    deixa de acompanhar
    python3 scripts/radar_b3.py --ver PETR4            mostra os dados de uma ação sem salvar nada

Entram no radar as ações da sua carteira na XP (dados/xp.json) e as de dados/radar_lista.json.
Fontes: Yahoo Finance (cotações, histórico de 1 ano e proventos), Fundamentus (P/L, P/VP, ROE,
margem, dívida líquida e setor), ambos sem chave, e brapi.dev (descrição da empresa; com BRAPI_TOKEN
no .env funciona para qualquer ação, sem token só para algumas de teste, como PETR4).

Não é recomendação de compra ou venda: são os números de cada ação lado a lado.
"""
import html
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LISTA = RAIZ / "dados" / "radar_lista.json"
SAIDA = RAIZ / "dados" / "radar_b3.json"
XP = RAIZ / "dados" / "xp.json"
INDICES = RAIZ / "dados" / "indices.json"
ENV = RAIZ / ".env"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1y&interval=1d&events=div"
BRAPI = "https://brapi.dev/api/quote/{}?modules=summaryProfile"  # o plano grátis só libera este módulo
FUNDAMENTUS = "https://www.fundamentus.com.br/detalhes.php?papel={}"
TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except ValueError:
            return {"error": True, "message": f"HTTP {e.code}"}


def token_brapi():
    if not ENV.exists():
        return None
    for linha in ENV.read_text(encoding="utf-8").splitlines():
        if linha.strip().startswith("BRAPI_TOKEN="):
            return linha.split("=", 1)[1].strip().strip("'\"") or None
    return None


def historico(simbolo):
    """Fechamentos diários de 1 ano e proventos pagos, do Yahoo Finance."""
    r = get_json(YAHOO.format(urllib.parse.quote(simbolo)))
    res = (r.get("chart") or {}).get("result")
    if not res:
        raise ValueError(((r.get("chart") or {}).get("error") or {}).get("description") or "sem dados")
    res = res[0]
    quando = [datetime.fromtimestamp(t, UTC).date().isoformat() for t in res["timestamp"]]
    fech = res["indicators"]["quote"][0]["close"]
    serie = [(d, c) for d, c in zip(quando, fech, strict=False) if c is not None]
    divs = sorted((datetime.fromtimestamp(int(t), UTC).date().isoformat(), v["amount"])
                  for t, v in (res.get("events") or {}).get("dividends", {}).items())
    return res["meta"], serie, divs


def metricas(serie):
    """Retorno em 1, 3 e 12 meses, volatilidade anual e maior queda do ano, em %."""
    precos = [c for _, c in serie]
    ult = precos[-1]
    ret = lambda n: (ult / precos[-n - 1] - 1) * 100 if len(precos) > n else None  # noqa: E731
    diarios = [math.log(b / a) for a, b in zip(precos, precos[1:], strict=False)]
    media = sum(diarios) / len(diarios)
    vol = math.sqrt(sum((x - media) ** 2 for x in diarios) / (len(diarios) - 1)) * math.sqrt(252) * 100
    pico, queda = precos[0], 0.0
    for p in precos:
        pico = max(pico, p)
        queda = min(queda, (p / pico - 1) * 100)
    return {"ret_1m": ret(21), "ret_3m": ret(63), "ret_12m": (ult / precos[0] - 1) * 100,
            "volatilidade": vol, "maior_queda": queda}


def numero(txt):
    """'6,52' → 6.52 · '8,0%' → 8.0 · '94.386.800.000' → 94386800000.0 · '-' → None."""
    txt = txt.replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(txt)
    except ValueError:
        return None


def fundamentus(ticker):
    """Indicadores da página de detalhes do Fundamentus (gratuito, sem chave)."""
    req = urllib.request.Request(FUNDAMENTUS.format(ticker), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pagina = r.read().decode("latin-1")
    pares = re.findall(r'<td class="label[^"]*">.*?<span class="txt">(.*?)</span>.*?</td>\s*'
                       r'<td class="data[^"]*">\s*<span class="(?:txt|oscil)">(.*?)</span>', pagina, re.S)
    campos = {}
    for k, v in pares:
        k, v = (html.unescape(re.sub(r"<.*?>", "", x)).strip() for x in (k, v))
        campos.setdefault(k, v)  # alguns rótulos se repetem (12 meses e trimestre); fica o primeiro
    if campos.get("Papel") != ticker:
        return None
    return campos


def fundamentos(ticker, token):
    """Fundamentus para os indicadores; brapi (com token) para a descrição e como reserva do P/L."""
    f = fundamentus(ticker)
    q = {}
    r = get_json(BRAPI.format(ticker) + (f"&token={token}" if token else ""))
    if r.get("results"):
        q = r["results"][0]
    p = q.get("summaryProfile") or {}
    if not f and not q:
        return None, r.get("message") or "sem dados no Fundamentus nem na brapi"
    f = f or {}
    banco = "banco" in (f.get("Subsetor", "") + f.get("Setor", "")).lower() or "financ" in f.get("Setor", "").lower()
    margem = numero(f.get("Marg. Líquida", "-"))
    return {
        "setor": f.get("Setor") or p.get("sectorDisp") or p.get("sector"),
        "subsetor": f.get("Subsetor") or p.get("industryDisp") or p.get("industry"),
        "banco": banco,
        "valor_mercado": numero(f.get("Valor de mercado", "-")) or q.get("marketCap"),
        "pl": numero(f.get("P/L", "-")) or q.get("priceEarnings"),
        "pvp": numero(f.get("P/VP", "-")),
        "roe": numero(f.get("ROE", "-")),
        "margem_liquida": None if banco and not margem else margem,
        "divida_liq_pl": None if banco else numero(f.get("Dív Líq / Patrim", "-")),
        "crescimento_receita_5a": numero(f.get("Cres. Rec (5a)", "-")),
        "ultimo_balanco": f.get("Últ balanço processado"),
        "resumo": (p.get("longBusinessSummary") or "")[:600],
    }, None


def carteira():
    """Ações que você tem na XP, com quantidade, preço médio e proventos recebidos."""
    if not XP.exists():
        return {}
    xp = json.loads(XP.read_text(encoding="utf-8"))
    pos = {}
    for p in xp["posicoes"]:
        if p["classe"] != "Ações":
            continue
        qtd = re.match(r"(\d+)", p.get("info", ""))
        pos[p["ativo"]] = {"quantidade": int(qtd.group(1)) if qtd else None, "aplicado": p.get("aplicado"),
                           "valor": p["valor"], "proventos": round(sum(
                               l["valor"] for l in xp["lancamentos_recentes"]
                               if l["tipo"] == "provento" and l["descricao"].endswith(" " + p["ativo"])), 2)}
    return pos


def analisar(ticker, token, minhas):
    meta, serie, divs = historico(ticker + ".SA")
    preco = meta.get("regularMarketPrice") or serie[-1][1]
    um_ano = serie[0][0]
    prov_12m = sum(v for d, v in divs if d >= um_ano)
    fund, erro = fundamentos(ticker, token)
    passo = max(1, len(serie) // 60)
    return {
        "ticker": ticker,
        "nome": meta.get("longName") or meta.get("shortName") or ticker,
        "preco": round(preco, 2),
        "data": serie[-1][0],
        "max_52s": meta.get("fiftyTwoWeekHigh"),
        "min_52s": meta.get("fiftyTwoWeekLow"),
        **{k: round(v, 2) if v is not None else None for k, v in metricas(serie).items()},
        "proventos_12m": round(prov_12m, 4),
        "dy_12m": round(prov_12m / preco * 100, 2) if preco else None,
        "ultimos_proventos": [[d, round(v, 4)] for d, v in divs[-4:]],
        "serie": [[d, round(c, 2)] for d, c in serie[::passo]] + ([[serie[-1][0], round(serie[-1][1], 2)]] if (len(serie) - 1) % passo else []),
        "fundamentos": fund,
        "fundamentos_erro": erro,
        "carteira": minhas.get(ticker),
    }


def ler_lista():
    return json.loads(LISTA.read_text(encoding="utf-8")) if LISTA.exists() else {"acompanhar": []}


def main(args):
    lista = ler_lista()
    if args[:1] in (["--adicionar"], ["--remover"]):
        tickers = [t.upper() for t in args[1:]]
        invalidos = [t for t in tickers if not TICKER.match(t)]
        if invalidos:
            sys.exit(f"Ticker inválido: {', '.join(invalidos)} (use o código da B3, como PETR4)")
        atual = set(lista["acompanhar"])
        atual = atual | set(tickers) if args[0] == "--adicionar" else atual - set(tickers)
        lista["acompanhar"] = sorted(atual)
        LISTA.write_text(json.dumps(lista, indent=1), encoding="utf-8")
        print("Acompanhando:", ", ".join(lista["acompanhar"]) or "nenhuma além da carteira")
        return
    token = token_brapi()
    minhas = carteira()
    if args[:1] == ["--ver"]:
        for t in args[1:]:
            print(json.dumps(analisar(t.upper(), token, minhas), ensure_ascii=False, indent=1))
        return

    tickers = sorted(set(minhas) | set(lista["acompanhar"]))
    acoes, falhas = [], []
    for t in tickers:
        try:
            acoes.append(analisar(t, token, minhas))
        except Exception as e:  # uma ação com problema não derruba o radar inteiro
            falhas.append(f"{t} ({e})")
    meta, serie, _ = historico("^BVSP")
    ibov = {"nome": "Ibovespa", "pontos": round(serie[-1][1]), "data": serie[-1][0],
            **{k: round(v, 2) if v is not None else None for k, v in metricas(serie).items()},
            "serie": [[d, round(c)] for d, c in serie[::max(1, len(serie) // 60)]]}
    cdi_12m = None
    if INDICES.exists():
        cdi = json.loads(INDICES.read_text(encoding="utf-8"))["cdi"]
        f = 1.0
        for d, v in cdi.items():
            if d > serie[0][0]:
                f *= 1 + v / 100
        cdi_12m = round((f - 1) * 100, 2)
    SAIDA.write_text(json.dumps({"atualizado_em": date.today().isoformat(), "ibovespa": ibov, "cdi_12m": cdi_12m,
                                 "com_token": bool(token), "acoes": acoes}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    sem_fund = [a["ticker"] for a in acoes if not a["fundamentos"]]
    print(f"Radar B3: {len(acoes)} ações · Ibovespa {ibov['ret_12m']:+.1f}% em 12 meses"
          + (f" · sem fundamentos: {', '.join(sem_fund)}" if sem_fund else "")
          + (f" · falharam: {', '.join(falhas)}" if falhas else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
