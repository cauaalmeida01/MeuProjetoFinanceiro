"""Baixa o CDI diário e o IPCA mensal da API pública do Banco Central (SGS) para dados/indices.json.

Uso:  python3 scripts/indices_bcb.py
Também roda dentro de sincronizar_pluggy.py. Não precisa de cadastro nem chave.
Séries: 12 (CDI, % ao dia) e 433 (IPCA, % ao mês).
"""
import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INDICES = RAIZ / "dados" / "indices.json"
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados?formato=json&dataInicial={}&dataFinal={}"
INICIO = date(2021, 1, 1)  # antes da abertura da conta no Inter


def baixar(serie, de, ate):
    url = SGS.format(serie, de.strftime("%d/%m/%Y"), ate.strftime("%d/%m/%Y"))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return [(d["data"][6:] + "-" + d["data"][3:5] + "-" + d["data"][:2], float(d["valor"])) for d in json.loads(r.read())]


def atualizar():
    """Busca só o que falta desde a última data salva (revendo os últimos 40 dias) e grava o arquivo."""
    ind = json.loads(INDICES.read_text(encoding="utf-8")) if INDICES.exists() else {"cdi": {}, "ipca": {}}
    hoje = date.today()
    for chave, serie, mensal in (("cdi", 12, False), ("ipca", 433, True)):
        ultimo = max(ind[chave], default=None)
        de = max(INICIO, date.fromisoformat(ultimo[:7] + "-01" if mensal else ultimo) - timedelta(days=40)) if ultimo else INICIO
        for d, v in baixar(serie, de, hoje):
            ind[chave][d[:7] if mensal else d] = v
    ind["atualizado_em"] = hoje.isoformat()
    INDICES.write_text(json.dumps(ind, indent=0, sort_keys=True), encoding="utf-8")
    return ind


if __name__ == "__main__":
    ind = atualizar()
    print(f"CDI até {max(ind['cdi'])} · IPCA até {max(ind['ipca'])} · salvo em {INDICES.relative_to(RAIZ)}")
