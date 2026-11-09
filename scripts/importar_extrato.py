"""Junta um extrato novo ao histórico do banco de dados (ver base_dados.py).

Uso:  python3 scripts/importar_extrato.py caminho/do/novo.psv

O arquivo novo tem o formato data|titulo|descricao|valor|tipo (banco é opcional).
Tudo do histórico a partir da primeira data do arquivo novo passa a refletir esse arquivo: quem continua
mantém o id e o histórico de classificação, então reimportar um período não duplica nada.
Ou entra tudo, ou nada muda. Depois rode scripts/gerar_painel.py.
"""
import csv
import sys

import base_dados


def ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def ler_historico():
    return base_dados.ler_transacoes()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    novo = ler(sys.argv[1])
    if not novo:
        sys.exit("O arquivo novo está vazio.")
    juntar(novo)


def juntar(novo, inicio=None):
    """Atualiza o histórico a partir de `inicio` (padrão: primeira data de `novo`) com as linhas de `novo`."""
    inicio = inicio or min(l["data"] for l in novo)
    novo = sorted((l for l in novo if l["data"] >= inicio), key=lambda l: l["data"])
    r = base_dados.substituir_periodo(novo, inicio)
    print(f"A partir de {inicio}: {r['inseridas']} novas, {r['removidas']} removidas, {r['mantidas']} sem mudança.")
    print(f"Histórico: {r['total']} transações, de {r['primeira']} a {r['ultima']}.")


if __name__ == "__main__":
    main()
