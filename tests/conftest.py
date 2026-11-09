"""Isolamento dos testes: nenhum teste lê dados/ de verdade nem acessa a internet."""
import urllib.request

import pytest

import gerar_demo
import gerar_painel
import importar_extrato
import indices_bcb
import radar_b3
import servidor
import sincronizar_pluggy


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    """Aponta todos os caminhos de dados para uma pasta temporária e bloqueia a internet."""
    dados = tmp_path / "dados"
    dados.mkdir()
    (tmp_path / "painel").mkdir()

    for nome, arquivo in {
        "RAIZ": tmp_path,
        "EXTRATO": dados / "inter_extrato.psv",
        "REGRAS_PESSOAIS": dados / "regras_pessoais.json",
        "XP": dados / "xp.json",
        "INTER_INV": dados / "inter_invest.json",
        "PLUGGY": dados / "pluggy_investimentos.json",
        "INDICES": dados / "indices.json",
        "RADAR": dados / "radar_b3.json",
        "SAIDA_JSON": dados / "transacoes.json",
        "SAIDA_HTML": tmp_path / "painel" / "index.html",
    }.items():
        monkeypatch.setattr(gerar_painel, nome, arquivo)

    monkeypatch.setattr(importar_extrato, "HISTORICO", dados / "inter_extrato.psv")
    monkeypatch.setattr(indices_bcb, "INDICES", dados / "indices.json")
    monkeypatch.setattr(sincronizar_pluggy, "RAIZ", tmp_path)
    monkeypatch.setattr(sincronizar_pluggy, "ENV", tmp_path / ".env")
    monkeypatch.setattr(sincronizar_pluggy, "INVESTIMENTOS", dados / "pluggy_investimentos.json")
    monkeypatch.setattr(radar_b3, "LISTA", dados / "radar_lista.json")
    monkeypatch.setattr(radar_b3, "SAIDA", dados / "radar_b3.json")
    monkeypatch.setattr(radar_b3, "XP", dados / "xp.json")
    monkeypatch.setattr(radar_b3, "INDICES", dados / "indices.json")
    monkeypatch.setattr(radar_b3, "ENV", tmp_path / ".env")
    monkeypatch.setattr(servidor, "PAINEL", tmp_path / "painel" / "index.html")
    monkeypatch.setattr(servidor, "RELATORIOS", dados / "relatorios")
    monkeypatch.setattr(gerar_demo, "RAIZ", tmp_path)
    monkeypatch.setattr(gerar_demo, "SAIDA", tmp_path / "docs" / "index.html")

    def sem_internet(*a, **k):
        raise AssertionError("teste tentou acessar a internet")

    monkeypatch.setattr(urllib.request, "urlopen", sem_internet)
    return tmp_path


class Resposta:
    """Imita o objeto devolvido por urllib.request.urlopen."""

    def __init__(self, corpo):
        self.corpo = corpo

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def resposta():
    return Resposta
