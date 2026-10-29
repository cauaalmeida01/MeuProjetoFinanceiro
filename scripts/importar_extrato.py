"""Junta um extrato novo ao histórico em dados/inter_extrato.psv.

Uso:  python3 scripts/importar_extrato.py caminho/do/novo.psv

O arquivo novo tem o mesmo formato (data|titulo|descricao|valor|tipo).
Tudo do histórico a partir da primeira data do arquivo novo é substituído
por ele, então reimportar um período não duplica nada. Depois rode
scripts/gerar_painel.py.
"""
import csv
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HISTORICO = RAIZ / "dados" / "inter_extrato.psv"
CAMPOS = ["data", "titulo", "descricao", "valor", "tipo"]


def ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    novo = ler(sys.argv[1])
    if not novo:
        sys.exit("O arquivo novo está vazio.")
    inicio = min(l["data"] for l in novo)
    antigo = ler(HISTORICO) if HISTORICO.exists() else []
    mantidos = [l for l in antigo if l["data"] < inicio]
    linhas = sorted(mantidos + novo, key=lambda l: l["data"])

    if HISTORICO.exists():
        shutil.copy(HISTORICO, HISTORICO.with_suffix(".psv.bak"))
    with open(HISTORICO, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter="|", lineterminator="\n")
        w.writeheader()
        w.writerows({k: l[k] for k in CAMPOS} for l in linhas)

    print(f"A partir de {inicio}: {len(antigo) - len(mantidos)} linhas antigas trocadas por {len(novo)} novas.")
    print(f"Histórico: {len(linhas)} transações, de {linhas[0]['data']} a {linhas[-1]['data']}.")


if __name__ == "__main__":
    main()
