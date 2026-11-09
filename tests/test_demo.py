"""A demonstração pública: dados fictícios e nenhuma ligação com os dados reais."""
import json
from datetime import date, timedelta

import pytest

import gerar_demo as d
import gerar_painel as gp

MESES = [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 13)]
SENTINELA = "NOME-REAL-SENTINELA"


def test_extrato_e_reproduzivel():
    assert d.extrato(MESES) == d.extrato(MESES)


def test_pipeline_classifica_quase_tudo():
    linhas, envios = d.extrato(MESES)
    tx = d.transacoes(linhas, envios)
    saidas = [t for t in tx if t[3] == "saida"]
    assert sum(t[4] for t in saidas if t[2] == "Outros") / sum(t[4] for t in saidas) < 0.02


def test_envios_para_a_xp_viram_investimento():
    linhas, envios = d.extrato(MESES)
    xp = [t for t in d.transacoes(linhas, envios) if t[7] == "XP"]
    assert len(xp) == len(envios) > 0


def test_salario_e_receita():
    linhas, envios = d.extrato(MESES)
    assert {t[2] for t in d.transacoes(linhas, envios) if t[3] == "entrada"} == {"Salário", "Freelas"}


def test_inter_total_bate_com_as_posicoes():
    linhas, envios = d.extrato(MESES)
    r = d.inter_invest(d.transacoes(linhas, envios), MESES)
    assert sum(p["valor"] for p in r["posicoes"]) == pytest.approx(r["total"], abs=0.02)


@pytest.fixture
def demo(monkeypatch):
    """Gera a demo com dados 'reais' plantados em dados/: nada deles pode aparecer na página."""
    gp.REGRAS_PESSOAIS.write_text(json.dumps({"voce_mesmo": [SENTINELA], "destinos": {SENTINELA: "Lazer"}}), encoding="utf-8")
    gp.XP.write_text(json.dumps({"patrimonio": 987654.32, "nome": SENTINELA}), encoding="utf-8")
    gp.INTER_INV.write_text(json.dumps({"total": 987654.32, "nome": SENTINELA}), encoding="utf-8")
    gp.EXTRATO.write_text(f"data|titulo|descricao|valor|tipo\n2026-01-01|Pix enviado|{SENTINELA}|-1|PIX\n", encoding="utf-8")
    gp.RADAR.write_text(json.dumps({"nome": SENTINELA}), encoding="utf-8")
    hoje = date.today()
    ind = {"cdi": {(hoje - timedelta(days=k)).isoformat(): 0.05 for k in range(800)},
           "ipca": {f"{a}-{m:02d}": 0.4 for a in (hoje.year - 2, hoje.year - 1, hoje.year) for m in range(1, 13)}}
    monkeypatch.setattr(d, "indices", lambda: ind)
    monkeypatch.setattr(d, "radar", lambda x, i: None)
    d.main()
    return d.SAIDA.read_text(encoding="utf-8")


def test_demo_nao_contem_dados_reais(demo):
    assert SENTINELA not in demo
    assert "987654" not in demo


def test_demo_se_identifica_como_demonstracao(demo):
    assert "const DEMO=true" in demo
    assert "Ana Exemplo" in demo


def test_demo_sem_marcadores_pendentes(demo):
    assert "/*__" not in demo


def test_demo_nao_tem_futuro(demo):
    dados = json.loads(demo.split("const RAW=")[1].split(";\nconst XP=")[0])
    assert max(t[0] for t in dados) <= date.today().isoformat()


def test_template_nao_tem_tag_que_quebra_o_live_server():
    """O Live Server injeta um script no primeiro </svg>; dentro do JavaScript isso quebrava a página."""
    assert "</svg>" not in gp.BASE.read_text(encoding="utf-8")
