"""Sugere categoria para o que as regras não reconheceram ("Outros"), com um classificador Naive Bayes.

O modelo aprende com os estabelecimentos que as regras já categorizaram e roda inteiro no computador:
nenhum dado sai daqui. Ele nunca muda uma categoria sozinho: as sugestões aparecem em "Revisar Outros"
no painel, e só viram regra quando você confirma. Abaixo de LIMIAR, o campo vem em branco.

Avaliação:  python3 scripts/sugerir_categorias.py
A validação separa por estabelecimento (o mesmo nome nunca está no treino e no teste ao mesmo tempo),
que é o caso real: prever uma loja que o modelo nunca viu.
"""
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

LIMIAR = 0.80
FORA = {"Outros", "Pix para pessoas", "Família", "Estornos e devoluções", "Contas e boletos", "Entre suas contas", "Investimentos"}
RUIDO = set("""ltda eireli epp mei me sa s a bra brasil salvador feira de santbra vera cruz camacari lauro freitas ba da do das dos e em com
comercio servicos pagamentos pagamento gestao estabelecimento""".split())
CONECTIVOS = {"de", "do", "da", "das", "dos"}
INICIO_DE_CIDADE = {"vera", "sao", "santo", "santa", "rio", "belo", "porto", "campo", "nova", "feira", "lauro"}


def sem_localidade(desc):
    """Tira a cidade do fim das compras no cartão, que vêm como "Loja Cidade Bra".

    Sem isso o modelo aprende cidade como se fosse tipo de negócio ("Osasco" parecia comida por causa do iFood).
    O campo da cidade tem 13 letras: quando ele enche, o "Bra" encosta nele ("Feira De Santbra").
    """
    partes = desc.split()
    if len(partes) < 2:
        return desc
    ultima = partes[-1].lower()
    if ultima.endswith("bra") and ultima != "bra" and len(desc) > 16:
        return desc[:-16].strip()
    if ultima not in ("bra", "b"):
        return desc
    resto = partes[:-2]  # a palavra final da cidade e o "Bra"
    if not resto:
        return " ".join(partes[:-1])
    while len(resto) >= 2 and resto[-1].lower() in CONECTIVOS:  # "Cruz Das Alma"
        resto = resto[:-2]
    if len(resto) >= 2 and resto[-1].lower() in INICIO_DE_CIDADE:  # "Vera Cruz"
        resto = resto[:-1]
    return " ".join(resto)


def tokens(desc):
    """Palavras úteis da descrição, sem cidade, acento, número e termos que não dizem nada sobre o negócio."""
    s = unicodedata.normalize("NFKD", sem_localidade(desc).lower()).encode("ascii", "ignore").decode()
    return [p for p in re.findall(r"[a-z]{3,}", s) if p not in RUIDO]


def atributos(desc):
    """Palavras inteiras e os prefixos de 4 letras, para ligar variações como 'lanches' e 'lanchonete'."""
    t = tokens(desc)
    return t + [p[:4] for p in t if len(p) > 4]


def treinar(exemplos):
    """exemplos: lista de (descrição, categoria). Devolve o modelo multinomial com suavização de Laplace."""
    docs, cont, total = Counter(), defaultdict(Counter), Counter()
    vocab = set()
    for desc, cat in exemplos:
        docs[cat] += 1
        for a in atributos(desc):
            cont[cat][a] += 1
            total[cat] += 1
            vocab.add(a)
    return {"docs": docs, "cont": cont, "total": total, "vocab": vocab, "n": sum(docs.values())}


def prever(modelo, desc):
    """(categoria, confiança de 0 a 1). Sem nenhuma palavra conhecida, devolve (None, 0)."""
    attrs = [a for a in atributos(desc) if a in modelo["vocab"]]
    if not attrs:
        return None, 0.0
    v = len(modelo["vocab"])
    log = {}
    for cat, n in modelo["docs"].items():
        log[cat] = math.log(n / modelo["n"]) + sum(math.log((modelo["cont"][cat][a] + 1) / (modelo["total"][cat] + v)) for a in attrs)
    topo = max(log.values())
    prob = {c: math.exp(x - topo) for c, x in log.items()}
    soma = sum(prob.values())
    cat = max(prob, key=prob.get)
    return cat, prob[cat] / soma


def exemplos_de(tx, parece_pessoa):
    """Estabelecimentos (sem repetir) que as regras categorizaram. Pix para pessoas ficam de fora."""
    vistos = {}
    for t in tx:
        desc, cat, tipo, titulo = t[1], t[2], t[3], t[5]
        if tipo == "saida" and cat not in FORA and (titulo != "Pix enviado" or not parece_pessoa(desc)):
            vistos.setdefault(desc, cat)
    return sorted(vistos.items())


def avaliar(exemplos, dobras=5, limiar=LIMIAR):
    """Validação cruzada por estabelecimento. Devolve acurácia geral e, acima do limiar, precisão e cobertura."""
    certos, respondidos, certos_lim = 0, 0, 0
    for i in range(dobras):
        teste = [e for j, e in enumerate(exemplos) if j % dobras == i]
        modelo = treinar([e for j, e in enumerate(exemplos) if j % dobras != i])
        for desc, cat in teste:
            prev, conf = prever(modelo, desc)
            certos += prev == cat
            if conf >= limiar:
                respondidos += 1
                certos_lim += prev == cat
    n = len(exemplos)
    return {"exemplos": n, "acuracia": certos / n, "cobertura": respondidos / n, "precisao": certos_lim / respondidos if respondidos else 0.0}


def revisar(tx, parece_pessoa, limite=30):
    """Maiores gastos em "Outros", por descrição, mais os que têm sugestão confiável mesmo sendo menores."""
    modelo = treinar(exemplos_de(tx, parece_pessoa))
    grupos = defaultdict(lambda: {"n": 0, "total": 0.0, "datas": set()})
    for t in tx:
        if t[2] == "Outros" and t[3] == "saida":
            g = grupos[t[1]]
            g["n"] += 1
            g["total"] += t[4]
            g["datas"].add(t[0])
    itens = []
    for posicao, (desc, g) in enumerate(sorted(grupos.items(), key=lambda x: -x[1]["total"])):
        cat, conf = prever(modelo, desc)
        confiavel = conf >= LIMIAR
        if posicao < limite or confiavel:
            itens.append({"desc": desc, "n": g["n"], "total": round(g["total"], 2), "datas": sorted(g["datas"], reverse=True),
                          "sugestao": cat if confiavel else None, "confianca": round(conf, 2) if confiavel else None})
    return itens


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gerar_painel as gp

    tx = json.loads(gp.SAIDA_JSON.read_text(encoding="utf-8"))
    ex = exemplos_de(tx, gp.parece_pessoa)
    for lim in (0.5, 0.7, 0.8, 0.9, 0.95):
        r = avaliar(ex, limiar=lim)
        print(f"limiar {lim:.2f}: precisão {r['precisao']:.1%} · cobertura {r['cobertura']:.1%} · "
              f"acurácia geral {r['acuracia']:.1%} ({r['exemplos']} estabelecimentos)")
    print()
    for item in revisar(tx, gp.parece_pessoa):
        print(f"{item['n']:3d}× R$ {item['total']:8.2f}  {str(item['sugestao']):18s} {item['desc'][:55]}")


if __name__ == "__main__":
    main()
