"""Rentabilidade contra o CDI, resumo dos índices e rendimento mensal do Inter."""
import json

import pytest

import gerar_painel as gp


def linha(data, rent, rend=10.0, aportes=0.0, final=100.0, **kw):
    return {"data": data, "rent_pct": rent, "rendimento": rend, "aportes_liquidos": aportes, "final": final, "pct_cdi": None, **kw}


IND = {"cdi": {"2025-01-15": 1.0, "2025-02-15": 1.0}, "ipca": {"2025-01": 0.5}}
OFICIAL = {"desde_inicio": {"pct_cdi": 116.02}}


def xp(*linhas):
    return {"abertura": "2025-01-01", "mensal": list(linhas), "performance": OFICIAL, "por_ano": ["oficial"]}


def test_cdi_do_periodo_e_percentual_do_mes():
    r = gp.recalcular_xp(xp(linha("2025-01-31", 2.0)), IND)["mensal"][0]
    assert r["cdi_pct"] == pytest.approx(1.0)
    assert r["pct_cdi"] == pytest.approx(200.0)
    assert r["ipca_pct"] == 0.5


def test_mantem_percentual_oficial_do_portal():
    r = gp.recalcular_xp(xp(linha("2025-01-31", 2.0, pct_cdi=None) | {"pct_cdi": 198.5}), IND)["mensal"][0]
    assert r["pct_cdi"] == 198.5


def test_data_inicial_fica_de_fora_e_a_final_entra():
    """O período é (desde, data]: o CDI do dia da foto anterior já foi contado no mês anterior."""
    ind = {"cdi": {"2025-01-10": 1.0, "2025-01-20": 2.0}, "ipca": {}}
    r = gp.recalcular_xp(xp(linha("2025-01-20", 1.0, desde="2025-01-10")), ind)["mensal"][0]
    assert r["cdi_pct"] == pytest.approx(2.0)


def test_sem_meses_novos_ficam_os_numeros_oficiais():
    r = gp.recalcular_xp(xp(linha("2025-01-31", 2.0)), IND)
    assert r["performance"] is OFICIAL
    assert r["por_ano"] == ["oficial"]


def test_com_meses_novos_a_performance_e_recalculada():
    r = gp.recalcular_xp(xp(linha("2025-01-31", 2.0, aportes=50, final=60), linha("2025-02-28", 1.0, aportes=25, final=90, fonte="pluggy")), IND)
    d = r["performance"]["desde_inicio"]
    assert d["rent_pct"] == pytest.approx(3.02)
    assert d["pct_cdi"] == pytest.approx(150.25, abs=0.01)
    assert d["aportes_liquidos"] == 75
    assert d["rendimento"] == 20
    assert r["performance_em"] == "2025-02-28"


def test_contagem_de_meses_e_por_ano():
    linhas = [linha("2024-12-31", 0.0, rend=-0.01, final=10), linha("2025-01-31", 2.0, final=20), linha("2025-02-28", -1.0, rend=-5, final=30, fonte="pluggy")]
    ind = {"cdi": {"2024-12-15": 1.0, "2025-01-15": 1.0, "2025-02-15": 1.0}, "ipca": {}}
    dados = xp(*linhas) | {"abertura": "2024-12-01"}
    r = gp.recalcular_xp(dados, ind)
    p = r["performance"]
    assert (p["meses_positivos"], p["meses_negativos"]) == (1, 2)  # rendimento de -R$ 0,01 conta como negativo
    assert (p["meses_acima_cdi"], p["meses_abaixo_cdi"]) == (1, 2)
    assert (p["melhor_mes_pct"], p["pior_mes_pct"]) == (2.0, -1.0)
    assert [(a["ano"], a["final"]) for a in r["por_ano"]] == [(2024, 10), (2025, 30)]


def test_doze_meses_usa_so_as_ultimas_linhas():
    linhas = [linha(f"2025-{m:02d}-28", 1.0, rend=1, fonte="pluggy") for m in range(1, 13)] + [linha("2026-01-28", 1.0, rend=1, fonte="pluggy")]
    ind = {"cdi": {"2025-01-15": 1.0}, "ipca": {}}
    assert gp.recalcular_xp(xp(*linhas), ind)["performance"]["doze_meses"]["rendimento"] == 12


def test_sem_indices_nao_altera():
    dados = xp(linha("2025-01-31", 2.0))
    assert gp.recalcular_xp(dados, None) is dados
    assert gp.recalcular_xp(None, IND) is None


def test_resumo_indices():
    ind = {"cdi": {"2024-01-10": 5.0, "2025-06-10": 1.0, "2025-06-11": 1.0}, "ipca": {f"2025-{m:02d}": 1.0 for m in range(1, 13)} | {"2024-12": 9.0}}
    r = gp.resumo_indices(ind)
    assert r["cdi_12m"] == pytest.approx(2.01)  # 2024-01-10 está a mais de 365 dias do último dado
    assert r["ipca_12m"] == pytest.approx(12.68)  # só os últimos 12 meses
    assert r["cdi_mensal"]["2025-06"] == pytest.approx(2.01)
    assert (r["cdi_ate"], r["ipca_ate"]) == ("2025-06-11", "2025-12")


def test_resumo_sem_indices():
    assert gp.resumo_indices(None) is None


def test_rendimento_mensal_do_inter_desconta_aplicacoes():
    gp.INTER_INV.write_text(json.dumps({"_fonte": "x", "total": 1100, "posicoes": [],
                                        "mensal": [{"mes": "2026-01", "valor": 1000}, {"mes": "2026-02", "valor": 1110}]}), encoding="utf-8")
    tx = [["2026-02-05", "CDB", "Investimentos", "aporte", 150, "Aplicação", "Inter", "CDB"],
          ["2026-02-20", "CDB", "Investimentos", "resgate", 50, "Resgate", "Inter", "CDB"],
          ["2026-02-06", "Ana", "Investimentos", "aporte", 999, "Pix enviado", "Inter", "XP"]]
    r = gp.carregar_inter_inv(tx)
    assert r["mensal"][0]["rendimento"] is None
    assert r["mensal"][1]["aportes_liquidos"] == 100
    assert r["mensal"][1]["rendimento"] == 10  # 1110 - 1000 - 100; o envio para a XP não entra
    assert "_fonte" not in r
