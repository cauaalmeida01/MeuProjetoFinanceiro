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
import fcntl
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_painel  # noqa: E402
import importar_extrato  # noqa: E402
import indices_bcb  # noqa: E402
import radar_b3  # noqa: E402

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
        for tentativa, espera in enumerate((5, 15, 30, None), 1):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                # 4xx é problema do pedido (chave, item): não adianta repetir; 5xx é instabilidade da Pluggy
                if e.code < 500 or espera is None:
                    raise RuntimeError(f"Pluggy respondeu {e.code} em {metodo} {caminho.split('?')[0]}: "
                                       f"{e.read().decode()[:200]}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if espera is None:
                    raise RuntimeError(f"sem conexão com a Pluggy ({e})") from None
            print(f"  Pluggy não respondeu (tentativa {tentativa}); tentando de novo em {espera}s")
            time.sleep(espera)

    def transacoes(self, conta):
        """Todas as transações da conta, seguindo a paginação por cursor."""
        tudo, caminho = [], f"/v2/transactions?accountId={conta}"
        while caminho:
            r = self.chamar("GET", caminho)
            tudo += r["results"]
            caminho = "/v2/transactions" + r["next"] if r.get("next") else None
        return tudo


def esperar_rede(limite=300):
    """Espera a internet voltar (o Mac pode estar acordando com o Wi-Fi ainda desligado)."""
    inicio = time.monotonic()
    while True:
        try:
            socket.getaddrinfo("api.pluggy.ai", 443)
            return
        except OSError:
            if time.monotonic() - inicio > limite:
                raise RuntimeError("sem internet há 5 minutos; fica para a próxima execução") from None
            time.sleep(15)


def para_linha(t):
    """Transação da Pluggy → linha do extrato (data|titulo|descricao|valor|tipo), igual ao site do Inter."""
    quando = datetime.fromisoformat(t["date"].replace("Z", "+00:00")).astimezone(FUSO)
    titulo, _, desc = t["description"].partition(" - ")
    titulo = titulo.strip()
    tipo = "COMPRA_DEBITO" if titulo == "Compra no débito" else t.get("operationType") or ""
    pag = t.get("paymentData") or {}
    return {
        "data": quando.date().isoformat(),
        "titulo": titulo,
        "descricao": re.sub(r"\s+", " ", desc).strip(),
        "valor": f"{t['amount']:.2f}",
        "tipo": tipo,
        "banco": ((pag.get("payer") if t["amount"] > 0 else pag.get("receiver")) or {}).get("routingNumberISPB") or "",
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
    # cada foto é [data, patrimônio]; a do mês vai sendo trocada até a última sincronização dele
    fotos.update({m: [m + "-28", v] for m, v in fotos.items() if not isinstance(v, list)})
    mes = hoje.strftime("%Y-%m")
    fotos[mes] = [hoje.isoformat(), xp["patrimonio"]]
    ultimo_portal = max(r["data"][:7] for r in xp["mensal"] if r.get("fonte") != "pluggy")
    xp["mensal"] = [r for r in xp["mensal"] if r.get("fonte") != "pluggy"]
    for m in sorted(fotos):
        anterior = (date.fromisoformat(m + "-01") - timedelta(days=1)).strftime("%Y-%m")
        if m <= ultimo_portal or anterior not in fotos:
            continue
        (desde, inicial), (ate, final) = fotos[anterior], fotos[m]
        aportes = sum(t["amount"] for t in invest if desde < dia(t["date"]).isoformat() <= ate
                      and lancamento_xp(t)[1] == "transferencia")
        rend = final - inicial - aportes
        base = inicial + max(aportes, 0)
        # o % do CDI de cada mês é calculado pelo gerar_painel.py com o CDI do Banco Central
        xp["mensal"].append({"data": ate, "desde": desde, "inicial": inicial,
                             "aportes_liquidos": round(aportes, 2), "rendimento": round(rend, 2), "final": final,
                             "rent_pct": round(rend / base * 100, 2) if base else 0, "pct_cdi": None,
                             "fonte": "pluggy"})

    gerar_painel.XP.write_text(json.dumps(xp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  XP: {len(novas)} posições · patrimônio R$ {xp['patrimonio']:.2f} · "
          f"{len(xp['envios_inter_para_xp'])} envios do Inter conciliados")


def grupo_inter(p):
    """Em qual linha da carteira do painel entra cada aplicação do Inter."""
    if p["type"] == "MUTUAL_FUND":
        return "Fundos", "Fundo " + re.sub(r"\s+FIC.*$", "", p["name"]).strip()
    return "Renda fixa", {"CDB": "CDB Banco Inter", "LCI": "LCI IPCA+", "LCA": "LCA"}.get(p.get("subtype"), p["name"])


def atualizar_inter(posicoes):
    """Atualiza dados/inter_invest.json: soma as aplicações por produto e guarda o valor do mês."""
    if not posicoes or not gerar_painel.INTER_INV.exists():
        return
    inv = json.loads(gerar_painel.INTER_INV.read_text(encoding="utf-8"))
    grupos = {}
    for p in posicoes:
        classe, nome = grupo_inter(p)
        g = grupos.setdefault(nome, {"produto": nome, "classe": classe, "valor": 0.0, "liquido": 0.0, "aplicado": 0.0, "impostos": 0.0,
                                     "_n": 0, "_venc": [], "_taxas": set(), "_sem_custo": False})
        g["valor"] += p["amount"]
        g["liquido"] += p["balance"] if p.get("balance") is not None else p["amount"]  # balance já vem sem IR/IOF
        g["impostos"] += (p.get("taxes") or 0) + (p.get("taxes2") or 0)
        g["_n"] += 1
        if p.get("amountOriginal"):
            g["aplicado"] += p["amountOriginal"]
        else:
            g["_sem_custo"] = True
        if p.get("dueDate"):
            g["_venc"].append(dia(p["dueDate"]))
        if p.get("rate") and p.get("rateType") == "CDI":
            g["_taxas"].add(p["rate"])

    # a Pluggy não informa quanto foi aplicado em fundos: vale o último valor conhecido
    aplicado_antes = {x["produto"]: x["aplicado"] for x in inv["posicoes"]}
    aplicado_antes.setdefault("Fundo Fator Macro", aplicado_antes.get("Fundo Fator Macro (multimercado)", 0))
    novas = []
    for g in grupos.values():
        partes = []
        if g["_taxas"]:
            partes.append(" a ".join(f"{t:g}%" for t in sorted(g["_taxas"])) + " do CDI")
        if g["_n"] > 1:
            partes.append(f"{g['_n']} aplicações")
        if g["_venc"]:
            ini, fim = min(g["_venc"]), max(g["_venc"])
            partes.append(f"vence {fim:%d/%m/%Y}" if ini == fim else f"vencimentos de {ini:%m/%Y} a {fim:%m/%Y}")
        aplicado = aplicado_antes.get(g["produto"], g["valor"]) if g["_sem_custo"] else g["aplicado"]
        novas.append({"produto": g["produto"], "classe": g["classe"], "valor": round(g["valor"], 2), "liquido": round(g["liquido"], 2),
                      "aplicado": round(aplicado, 2), "impostos": round(g["impostos"], 2), "info": " · ".join(partes) or "Resgate em D+5"})
    inv["posicoes"] = sorted(novas, key=lambda x: -x["valor"])
    inv["total"] = round(sum(x["valor"] for x in novas), 2)
    inv["atualizado_em"] = date.today().isoformat()
    mes = date.today().strftime("%Y-%m")
    linhas = [m for m in inv["mensal"] if m["mes"] != mes]
    inv["mensal"] = sorted(linhas + [{"mes": mes, "valor": inv["total"]}], key=lambda m: m["mes"])
    gerar_painel.INTER_INV.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  Inter: {len(posicoes)} aplicações · total R$ {inv['total']:.2f}")


def main():
    print(f"\n=== {datetime.now(FUSO):%d/%m/%Y %H:%M} ===")
    # o agendamento e o botão "Sincronizar agora" podem coincidir: só uma sincronização por vez
    trava = open(RAIZ / "dados" / ".sincronizando", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Outra sincronização já está rodando; esta foi cancelada.")
        return
    env = ler_env()
    esperar_rede()
    pluggy = Pluggy(env["PLUGGY_CLIENT_ID"], env["PLUGGY_CLIENT_SECRET"])
    eu = gerar_painel.carregar_regras()[3]
    linhas, investimentos, falhas = [], [], 0
    item_ids = [i.strip() for i in env["PLUGGY_ITEM_IDS"].split(",") if i.strip()]
    for item_id in item_ids:
        # um banco com problema não impede de salvar o outro
        try:
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
            if any(c["type"] == "BANK" and "INTER" in c["name"].upper() for c in contas):
                atualizar_inter([p for p in inv if p.get("status") == "ACTIVE"])
            contas_xp = [c for c in contas if c["type"] == "BANK" and c["name"].upper().startswith("XP")]
            if contas_xp:
                atualizar_xp(pluggy, contas_xp, [p for p in inv if p.get("status") == "ACTIVE"], eu)
        except Exception as e:
            falhas += 1
            print(f"Atenção: item {item_id[:8]} falhou ({e}); os outros seguem")
    if falhas == len(item_ids):
        raise RuntimeError("nenhum banco respondeu; nada foi alterado")

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
    try:
        ind = indices_bcb.atualizar()
        print(f"CDI até {max(ind['cdi'])} · IPCA até {max(ind['ipca'])} (Banco Central)")
    except Exception as e:  # sem o Banco Central o painel usa os índices da última vez
        print(f"Atenção: não deu para atualizar CDI/IPCA ({e})")
    try:
        radar_b3.main([])
    except Exception as e:  # idem para o Radar B3
        print(f"Atenção: não deu para atualizar o Radar B3 ({e})")
    print()
    gerar_painel.main()


if __name__ == "__main__":
    main()
