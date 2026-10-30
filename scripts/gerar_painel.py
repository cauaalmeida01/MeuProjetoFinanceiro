"""Lê o extrato do Inter, classifica cada transação e gera o painel local.

Uso:  python3 scripts/gerar_painel.py
Entrada: dados/inter_extrato.psv  (data|titulo|descricao|valor|tipo)
         regras_categorias.json  (estabelecimentos, versionado)
         dados/regras_pessoais.json  (pessoas e seus nomes, opcional, fora do git)
         dados/xp.json  (posição, evolução mensal e conciliação da XP, opcional)
         dados/inter_invest.json  (posição e evolução dos investimentos do Inter, opcional)
Saída:   dados/transacoes.json e painel/index.html
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EXTRATO = RAIZ / "dados" / "inter_extrato.psv"
REGRAS = RAIZ / "regras_categorias.json"
REGRAS_PESSOAIS = RAIZ / "dados" / "regras_pessoais.json"
XP = RAIZ / "dados" / "xp.json"
INTER_INV = RAIZ / "dados" / "inter_invest.json"
PLUGGY = RAIZ / "dados" / "pluggy_investimentos.json"
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
        if any(t in d for t in trechos):
            return nome
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


def ultima_sincronizacao():
    """Data e hora da última sincronização com a Pluggy, gravada por sincronizar_pluggy.py."""
    if not PLUGGY.exists():
        return None
    return json.loads(PLUGGY.read_text(encoding="utf-8")).get("sincronizado_em")


def classificar(data, titulo, desc, valor, cats, destinos, origens, eu, conc):
    """Devolve (tipo, categoria). tipo: entrada | saida | aporte | resgate | transf."""
    d = desc.lower()
    if titulo in APORTE:
        return "aporte", "Inter"
    if titulo in RESGATE:
        return "resgate", "Inter"
    if any(n in d for n in eu):
        # Pix para o próprio CPF: só conta como XP o que foi conciliado com o extrato de lá;
        # o resto foi para outra conta sua e não é gasto nem entrada
        chave = (data, round(abs(valor), 2))
        lado = "envio" if valor < 0 else "retorno"
        if conc[lado][chave] > 0:
            conc[lado][chave] -= 1
            return ("aporte", "XP") if valor < 0 else ("resgate", "XP")
        return "transf", "Entre suas contas"
    if titulo in DEVOLUCAO_ENTRADA:
        return "entrada", "Estornos e devoluções"
    if titulo in DEVOLUCAO_SAIDA:
        return "saida", "Estornos e devoluções"
    if valor > 0:
        cat = next((c for nome, c in origens if nome in d), None)
        return "entrada", cat or ("Banco Inter" if "banco inter" in d else "Pix recebido")
    cat = next((c for nome, c in destinos if nome in d), None) or por_regra(desc, cats)
    if cat:
        return "saida", cat
    if titulo == "Pagamento efetuado":
        return "saida", "Contas e boletos"
    if titulo in ("Pix enviado", "Transferência enviada") and parece_pessoa(desc):
        return "saida", "Pix para pessoas"
    return "saida", "Outros"


def main():
    cats, destinos, origens, eu = carregar_regras()
    xp, conc = carregar_xp()
    linhas = list(csv.DictReader(EXTRATO.open(encoding="utf-8"), delimiter="|"))
    tx = []
    for l in linhas:
        v = float(l["valor"])
        desc = l["descricao"].strip() or l["titulo"]
        tipo, cat = classificar(l["data"], l["titulo"], desc, v, cats, destinos, origens, eu, conc)
        prod = produto(tipo, cat, desc)
        if prod:
            cat = "Investimentos"
        tx.append([l["data"], desc, cat, tipo, round(abs(v), 2), l["titulo"], "Inter", prod])

    SAIDA_JSON.write_text(json.dumps(tx, ensure_ascii=False), encoding="utf-8")
    xp_painel = {k: v for k, v in xp.items() if not k.startswith("_") and k not in ("envios_inter_para_xp", "retornos_xp_para_inter")} if xp else None
    html = (BASE.read_text(encoding="utf-8")
            .replace("/*__DADOS__*/[]", json.dumps(tx, ensure_ascii=False))
            .replace("/*__XP__*/null", json.dumps(xp_painel, ensure_ascii=False))
            .replace("/*__INTERINV__*/null", json.dumps(carregar_inter_inv(tx), ensure_ascii=False))
            .replace("/*__SYNC__*/null", json.dumps(ultima_sincronizacao())))
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
