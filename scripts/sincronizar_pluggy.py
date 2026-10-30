"""Busca o extrato e os investimentos na Pluggy (Open Finance) e atualiza o painel.

Uso:  python3 scripts/sincronizar_pluggy.py
Precisa de um .env na raiz do projeto com:
    PLUGGY_CLIENT_ID=...
    PLUGGY_CLIENT_SECRET=...
    PLUGGY_ITEM_IDS=id-do-inter,id-da-xp   (dashboard.pluggy.ai > Demo > "Copiar Item ID")

O Open Finance só devolve os últimos ~12 meses. O histórico antigo continua
em dados/inter_extrato.psv; só o período que a Pluggy cobre é substituído.
Saída: dados/inter_extrato.psv, dados/pluggy_investimentos.json e o painel.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_painel  # noqa: E402
import importar_extrato  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"
INVESTIMENTOS = RAIZ / "dados" / "pluggy_investimentos.json"
API = "https://api.pluggy.ai"
FUSO = timezone(timedelta(hours=-3))  # Salvador, sem horário de verão


def ler_env():
    env = {}
    for linha in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    faltando = [k for k in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS") if not env.get(k)]
    if faltando:
        sys.exit(f"Falta no .env: {', '.join(faltando)}")
    return env


class Pluggy:
    def __init__(self, client_id, client_secret):
        self.chave = None
        self.chave = self.chamar("POST", "/auth", {"clientId": client_id, "clientSecret": client_secret})["apiKey"]

    def chamar(self, metodo, caminho, corpo=None):
        req = urllib.request.Request(API + caminho, method=metodo,
                                     data=json.dumps(corpo).encode() if corpo else None)
        req.add_header("Content-Type", "application/json")
        if self.chave:
            req.add_header("X-API-KEY", self.chave)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"Pluggy respondeu {e.code} em {metodo} {caminho.split('?')[0]}: {e.read().decode()[:200]}")

    def transacoes(self, conta):
        """Todas as transações da conta, seguindo a paginação por cursor."""
        tudo, caminho = [], f"/v2/transactions?accountId={conta}"
        while caminho:
            r = self.chamar("GET", caminho)
            tudo += r["results"]
            caminho = "/v2/transactions" + r["next"] if r.get("next") else None
        return tudo


def para_linha(t):
    """Transação da Pluggy → linha do extrato (data|titulo|descricao|valor|tipo), igual ao site do Inter."""
    quando = datetime.fromisoformat(t["date"].replace("Z", "+00:00")).astimezone(FUSO)
    titulo, _, desc = t["description"].partition(" - ")
    titulo = titulo.strip()
    tipo = "COMPRA_DEBITO" if titulo == "Compra no débito" else t.get("operationType") or ""
    return {
        "data": quando.date().isoformat(),
        "titulo": titulo,
        "descricao": re.sub(r"\s+", " ", desc).strip(),
        "valor": f"{t['amount']:g}",
        "tipo": tipo,
        "_quando": quando,
    }


MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()
TITULOS = {"LTN": "LTN", "LFT": "LFT", "NTNB PRINC": "NTN-B Principal", "NTNB": "NTN-B", "NTNF": "NTN-F"}


def dia(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(FUSO).date()


def nome_ativo(p):
    """Mesmo nome que o painel já usa: 'PETR4', 'LTN jan/2027', 'CDB Banco XP out/2027'."""
    if p["type"] == "EQUITY":
        return p["code"]
    venc = dia(p["dueDate"]) if p.get("dueDate") else None
    sufixo = f" {MESES[venc.month - 1]}/{venc.year}" if venc else ""
    if p["subtype"] == "TREASURY":
        return TITULOS.get(p["name"], p["name"]) + sufixo
    emissor = re.sub(r"\s+S\.?/?A\.?$", "", p.get("issuer") or "").title().replace("Xp", "XP")
    return f"{p['subtype']} {emissor}".strip() + sufixo


def nova_posicao(p):
    """Posição que ainda não existia no xp.json: classe, subclasse e descrição a partir da Pluggy."""
    venc = dia(p["dueDate"]).strftime("%d/%m/%Y") if p.get("dueDate") else ""
    if p["type"] == "EQUITY":
        q = p.get("quantity") or 0
        return {"classe": "Ações", "sub": "Renda variável", "info": f"{q:g} {'ação' if q == 1 else 'ações'}"}
    sub = {"CDI": "Pós-fixado", "SELIC": "Selic", "IPCA": "IPCA+"}.get(p.get("rateType"), "Prefixado")
    classe = {"TREASURY": "Tesouro Direto"}.get(p["subtype"], "Renda Fixa" if p["type"] == "FIXED_INCOME" else "Outros")
    taxa = f"{p['rate']:g}% do CDI · " if p.get("rateType") == "CDI" and p.get("rate") else ""
    return {"classe": classe, "sub": sub, "info": f"{taxa}vence {venc}" if venc else taxa.rstrip(" ·")}


def lancamento_xp(t):
    """Movimento da conta de investimentos da XP → {data, descricao, valor, tipo}, como no xp.json."""
    d, v = t["description"], round(t["amount"], 2)
    ativo = re.search(r"CLIENTES\s+(\w+)", d)
    for chave, rotulo in (("JUROS S/ CAPITAL", "JUROS S/ CAPITAL"), ("DIVIDENDOS", "DIVIDENDOS"), ("RENDIMENTOS", "RENDIMENTOS")):
        if d.startswith(chave) and ativo:
            return rotulo + " " + ativo.group(1), "provento"
    nota = re.search(r"NOTA N\S*\s*(\d+)", d)
    if nota:
        return f"Operações em bolsa (nota {nota.group(1)})", "compra" if v < 0 else "venda"
    if d.startswith("FRAÇÕES DE AÇÕES"):
        return d.title().replace("De ", "de "), "venda"
    if d.startswith("COMPRA TESOURO"):
        return "Compra Tesouro Direto", "compra"
    if d.startswith("COMPRA "):
        return "Compra " + d.split("|")[0][7:].strip().title().replace("Xp", "XP"), "compra"
    if "conta digital" in d.lower() or "RETIRADA" in d:
        return ("Transferência recebida da conta digital" if v > 0 else "Transferência enviada para a conta digital"), "transferencia"
    return d.strip(), "outro"


def atualizar_xp(pluggy, contas, posicoes, eu):
    """Atualiza dados/xp.json com a posição, o saldo, os lançamentos e os Pix vindos do Inter."""
    if not gerar_painel.XP.exists():
        print("  dados/xp.json não existe; a XP fica de fora.")
        return
    xp = json.loads(gerar_painel.XP.read_text(encoding="utf-8"))
    hoje = date.today()
    xp.setdefault("performance_em", xp["atualizado_em"])

    # posições: atualiza as que já existiam (mantendo nome, classe e preço médio) e cria as novas
    antigas = {p["ativo"]: p for p in xp["posicoes"]}
    novas = []
    for p in posicoes:
        nome = nome_ativo(p)
        pos = dict(antigas.get(nome) or {"ativo": nome, **nova_posicao(p)})
        pos["valor"] = round(p["amount"], 2)
        if p.get("amountOriginal"):
            pos["aplicado"] = round(p["amountOriginal"], 2)
        elif p["type"] == "EQUITY":
            q = p.get("quantity") or 0
            pm = re.search(r"PM R\$ ([\d.,]+)", pos.get("info", ""))
            qtd_antiga = re.match(r"(\d+)", pos.get("info", ""))
            if not (pm and qtd_antiga and int(qtd_antiga.group(1)) == q):
                pos["aplicado"] = None  # comprou ou vendeu: o preço médio novo não vem pela Pluggy
                pos["info"] = f"{q:g} {'ação' if q == 1 else 'ações'}"
        novas.append(pos)
    xp["posicoes"] = novas
    xp["saldo_conta"] = round(sum(c["balance"] for c in contas), 2)
    xp["patrimonio"] = round(sum(p["valor"] for p in novas) + xp["saldo_conta"], 2)
    xp["atualizado_em"] = hoje.isoformat()

    # movimentos: a conta digital mostra os Pix vindos do Inter; a de investimentos, proventos e compras
    movs = {c["id"]: pluggy.transacoes(c["id"]) for c in contas}
    digital = next((c["id"] for c in contas if any("Pix recebido de" in t["description"] for t in movs[c["id"]])), None)
    for c in contas:
        for t in movs[c["id"]]:
            quem = t["description"].lower()
            chave = [dia(t["date"]).isoformat(), round(abs(t["amount"]), 2)]
            if c["id"] == digital and any(n in quem for n in eu):
                lista = xp["envios_inter_para_xp"] if t["amount"] > 0 else xp["retornos_xp_para_inter"]
                if quem.startswith(("pix recebido de", "pix enviado para")) and chave not in lista:
                    lista.append(chave)
    xp["envios_inter_para_xp"].sort()
    xp["retornos_xp_para_inter"].sort()

    invest = [t for c in contas if c["id"] != digital for t in movs[c["id"]]]
    if invest:
        inicio = min(dia(t["date"]) for t in invest).isoformat()
        # o que já tinha descrição melhor (coletada no portal) continua com ela
        antes = {(l["data"], l["valor"]): l for l in xp["lancamentos_recentes"]}
        lanc = [l for l in xp["lancamentos_recentes"] if l["data"] < inicio]
        for t in sorted(invest, key=lambda t: t["date"]):
            d, v = dia(t["date"]).isoformat(), round(t["amount"], 2)
            desc, tipo = lancamento_xp(t)
            lanc.append(antes.get((d, v)) or {"data": d, "descricao": desc, "valor": v, "tipo": tipo})
        xp["lancamentos_recentes"] = lanc

    # evolução mensal: guarda o patrimônio do fim de cada mês e, a partir do mês seguinte
    # à última linha do portal, calcula o mês com aportes e rendimento
    fotos = xp.setdefault("fotos_mensais", {})
    mes = hoje.strftime("%Y-%m")
    fotos[mes] = xp["patrimonio"]
    ultimo_portal = max(r["data"][:7] for r in xp["mensal"] if r.get("fonte") != "pluggy")
    xp["mensal"] = [r for r in xp["mensal"] if r.get("fonte") != "pluggy"]
    for m in sorted(fotos):
        anterior = (date.fromisoformat(m + "-01") - timedelta(days=1)).strftime("%Y-%m")
        if m <= ultimo_portal or anterior not in fotos:
            continue
        aportes = sum(t["amount"] for t in invest if dia(t["date"]).strftime("%Y-%m") == m
                      and lancamento_xp(t)[1] == "transferencia")
        inicial, final = fotos[anterior], fotos[m]
        rend = final - inicial - aportes
        base = inicial + max(aportes, 0)
        xp["mensal"].append({"data": hoje.isoformat() if m == mes else m + "-28", "inicial": inicial,
                             "aportes_liquidos": round(aportes, 2), "rendimento": round(rend, 2), "final": final,
                             "rent_pct": round(rend / base * 100, 2) if base else 0, "pct_cdi": None,
                             "fonte": "pluggy"})

    gerar_painel.XP.write_text(json.dumps(xp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  XP: {len(novas)} posições · patrimônio R$ {xp['patrimonio']:.2f} · "
          f"{len(xp['envios_inter_para_xp'])} envios do Inter conciliados")


def main():
    env = ler_env()
    pluggy = Pluggy(env["PLUGGY_CLIENT_ID"], env["PLUGGY_CLIENT_SECRET"])
    eu = gerar_painel.carregar_regras()[3]
    linhas, investimentos = [], []
    for item_id in [i.strip() for i in env["PLUGGY_ITEM_IDS"].split(",") if i.strip()]:
        item = pluggy.chamar("GET", f"/items/{item_id}")
        contas = pluggy.chamar("GET", f"/accounts?itemId={item_id}")["results"]
        nomes = ", ".join(c["name"] for c in contas) or "sem contas"
        print(f"Item {item_id[:8]}: {item['status']} · atualizado {item.get('lastUpdatedAt', '')[:10]} · {nomes}")
        if item["status"] != "UPDATED":
            print(f"  Atenção: {item.get('statusDetail') or item.get('error')}")
        for c in contas:
            if c["type"] == "BANK" and "INTER" in c["name"].upper():
                tx = pluggy.transacoes(c["id"])
                linhas += [para_linha(t) for t in tx if t.get("status") == "POSTED"]
                print(f"  {len(tx)} transações do Inter")
        inv = pluggy.chamar("GET", f"/investments?itemId={item_id}")["results"]
        investimentos += inv
        if inv:
            print(f"  {len(inv)} investimentos")
        contas_xp = [c for c in contas if c["type"] == "BANK" and c["name"].upper().startswith("XP")]
        if contas_xp:
            atualizar_xp(pluggy, contas_xp, [p for p in inv if p.get("status") == "ACTIVE"], eu)

    INVESTIMENTOS.write_text(json.dumps({"atualizado_em": date.today().isoformat(),
                                         "sincronizado_em": datetime.now(FUSO).isoformat(timespec="seconds"),
                                         "posicoes": investimentos},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
    if linhas:
        linhas.sort(key=lambda l: l["_quando"])
        # o primeiro dia da janela da Pluggy pode vir pela metade, então ele fica com o histórico
        inicio = (date.fromisoformat(linhas[0]["data"]) + timedelta(days=1)).isoformat()
        importar_extrato.juntar(linhas, inicio)
    else:
        print("Nenhuma transação do Inter veio da Pluggy; o histórico ficou como estava.")
    print()
    gerar_painel.main()


if __name__ == "__main__":
    main()
