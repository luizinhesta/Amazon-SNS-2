"""Testes de integração de ``/api/estatisticas`` e ``/api/arquitetura`` (Tarefa 12.2).

Exercitam, via :class:`fastapi.testclient.TestClient`, os dois endpoints da visão
geral do laboratório AWS SNS Delivery Lab, injetando um provedor de observações em
memória (sem AWS real):

- ``GET /api/estatisticas``: agrega por cenário (publicadas por tópico,
  Entrega_Confirmada por fila, presentes por DLQ), todos inteiros ≥ 0 com 0 quando
  ausente, separados em dois conjuntos distintos e com o horário da última
  atualização bem-sucedida; sob timeout, retorna a indicação de timeout e preserva
  os últimos dados válidos sem avançar o horário (Req. 3.4-3.10, 14.1, 14.3, 3.9);
- ``GET /api/arquitetura``: devolve os dois tópicos com tipo, as seis assinaturas,
  as seis filas de destino e as duas DLQs (Req. 3.1, 3.2).

Referências de requisitos: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 14.1, 14.3.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.api.estado_estatisticas_sns import (
    EstadoEstatisticasSns,
    MENSAGEM_TIMEOUT_ESTATISTICAS,
)
from app.api.rotas_sns import criar_app_sns
from app.dominio import constantes_sns as c
from app.observabilidade.agregador_estatisticas_sns import (
    ObservacaoSns,
    TipoObservacao,
)
from app.dominio.tipos_sns import Cenario


def _cliente(estado_estatisticas=None, provedor_observacoes=None) -> TestClient:
    """Cria o TestClient do app SNS com o estado/provedor de estatísticas injetado."""
    app = criar_app_sns(
        estado_estatisticas_sns=estado_estatisticas,
        provedor_observacoes=provedor_observacoes,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/arquitetura (Req. 3.1, 3.2)
# ---------------------------------------------------------------------------
def test_arquitetura_tem_2_topicos_6_assinaturas_6_filas_2_dlqs() -> None:
    corpo = _cliente().get("/api/arquitetura").json()

    assert len(corpo["topicos"]) == 2
    assert len(corpo["assinaturas"]) == 6
    assert len(corpo["filas_destino"]) == 6
    assert len(corpo["dlqs"]) == 2


def test_arquitetura_identifica_tipo_de_cada_topico() -> None:
    topicos = {t["nome"]: t for t in _cliente().get("/api/arquitetura").json()["topicos"]}

    assert topicos[c.TOPICO_STANDARD]["tipo"] == "Standard"
    assert topicos[c.TOPICO_FIFO]["tipo"] == "FIFO"
    # A DLQ compatível (Redrive_Policy_SNS) acompanha o tipo do tópico.
    assert topicos[c.TOPICO_STANDARD]["dlq_compativel"] == c.DLQ_SNS_STANDARD
    assert topicos[c.TOPICO_FIFO]["dlq_compativel"] == c.DLQ_SNS_FIFO


def test_arquitetura_assinaturas_cobrem_fan_out_dos_dois_topicos() -> None:
    assinaturas = _cliente().get("/api/arquitetura").json()["assinaturas"]

    por_topico: dict[str, set[str]] = {}
    for a in assinaturas:
        por_topico.setdefault(a["topico"], set()).add(a["fila_destino"])

    assert por_topico[c.TOPICO_STANDARD] == set(c.FILAS_DESTINO_STANDARD)
    assert por_topico[c.TOPICO_FIFO] == set(c.FILAS_DESTINO_FIFO)


def test_arquitetura_lista_as_duas_dlqs_com_tipo() -> None:
    dlqs = {d["nome"]: d["tipo"] for d in _cliente().get("/api/arquitetura").json()["dlqs"]}

    assert dlqs == {c.DLQ_SNS_STANDARD: "Standard", c.DLQ_SNS_FIFO: "FIFO"}


# ---------------------------------------------------------------------------
# GET /api/estatisticas — agregação por cenário (Req. 3.4-3.10)
# ---------------------------------------------------------------------------
def test_estatisticas_sem_observacoes_retorna_zeros_e_dois_cenarios() -> None:
    # Provedor vazio: ausência de dados produz 0 em todas as estatísticas (Req. 3.10).
    corpo = _cliente(provedor_observacoes=lambda: []).get("/api/estatisticas").json()

    assert corpo["timeout"] is False
    assert corpo["mensagem"] == ""
    # Dois conjuntos distintos e rotulados (Req. 3.7).
    assert corpo["standard"]["cenario"] == "standard"
    assert corpo["fifo"]["cenario"] == "fifo"
    assert corpo["standard"]["rotulo"] != corpo["fifo"]["rotulo"]

    # Todos os contadores conhecidos aparecem com 0 (Req. 3.4, 3.5, 3.6, 3.10).
    std = corpo["standard"]
    assert {co["nome"] for co in std["publicadas_por_topico"]} == {c.TOPICO_STANDARD}
    assert {co["nome"] for co in std["confirmadas_por_fila"]} == set(
        c.FILAS_DESTINO_STANDARD
    )
    assert all(co["valor"] == 0 for co in std["publicadas_por_topico"])
    assert all(co["valor"] == 0 for co in std["confirmadas_por_fila"])
    assert all(co["valor"] == 0 for co in std["presentes_por_dlq"])

    # Horário da última atualização bem-sucedida presente, com fuso (Req. 3.8).
    assert corpo["ultima_atualizacao"]
    assert ("+" in corpo["ultima_atualizacao"]) or corpo["ultima_atualizacao"].endswith(
        "Z"
    )


def test_estatisticas_contabiliza_por_cenario_sem_misturar() -> None:
    observacoes = [
        ObservacaoSns(cenario=Cenario.STANDARD, tipo=TipoObservacao.PUBLICACAO),
        ObservacaoSns(cenario=Cenario.STANDARD, tipo=TipoObservacao.PUBLICACAO),
        ObservacaoSns(
            cenario=Cenario.STANDARD,
            tipo=TipoObservacao.CONFIRMACAO,
            fila_destino=c.FILA_DESTINO1_STANDARD,
        ),
        ObservacaoSns(cenario=Cenario.FIFO, tipo=TipoObservacao.PUBLICACAO),
        ObservacaoSns(
            cenario=Cenario.FIFO,
            tipo=TipoObservacao.DLQ,
            dlq=c.DLQ_SNS_FIFO,
        ),
    ]
    corpo = _cliente(provedor_observacoes=lambda: observacoes).get(
        "/api/estatisticas"
    ).json()

    std_pub = {co["nome"]: co["valor"] for co in corpo["standard"]["publicadas_por_topico"]}
    std_conf = {co["nome"]: co["valor"] for co in corpo["standard"]["confirmadas_por_fila"]}
    fifo_pub = {co["nome"]: co["valor"] for co in corpo["fifo"]["publicadas_por_topico"]}
    fifo_dlq = {co["nome"]: co["valor"] for co in corpo["fifo"]["presentes_por_dlq"]}

    assert std_pub[c.TOPICO_STANDARD] == 2
    assert std_conf[c.FILA_DESTINO1_STANDARD] == 1
    assert fifo_pub[c.TOPICO_FIFO] == 1
    assert fifo_dlq[c.DLQ_SNS_FIFO] == 1
    # O cenário FIFO não é contabilizado no Standard e vice-versa (Req. 3.7).
    assert sum(co["valor"] for co in corpo["fifo"]["confirmadas_por_fila"]) == 0
    assert sum(co["valor"] for co in corpo["standard"]["presentes_por_dlq"]) == 0


# ---------------------------------------------------------------------------
# GET /api/estatisticas — timeout preservando os últimos dados válidos (Req. 14.3, 3.9)
# ---------------------------------------------------------------------------
def test_estatisticas_timeout_preserva_ultimos_dados_validos() -> None:
    # Provedor que alterna: primeira coleta é rápida (um sucesso), as seguintes
    # excedem o timeout curto. Assim validamos que o último dado válido é preservado.
    chamadas = {"n": 0}

    def provedor():
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return [
                ObservacaoSns(cenario=Cenario.STANDARD, tipo=TipoObservacao.PUBLICACAO)
            ]
        time.sleep(0.5)  # excede o timeout curto configurado abaixo
        return [
            ObservacaoSns(cenario=Cenario.STANDARD, tipo=TipoObservacao.PUBLICACAO),
            ObservacaoSns(cenario=Cenario.STANDARD, tipo=TipoObservacao.PUBLICACAO),
        ]

    estado = EstadoEstatisticasSns(provedor, timeout_segundos=0.1)
    cliente = _cliente(estado_estatisticas=estado)

    # 1ª chamada: sucesso, estabelece o último dado válido.
    primeira = cliente.get("/api/estatisticas").json()
    assert primeira["timeout"] is False
    horario_sucesso = primeira["ultima_atualizacao"]
    std_pub_primeira = {
        co["nome"]: co["valor"] for co in primeira["standard"]["publicadas_por_topico"]
    }
    assert std_pub_primeira[c.TOPICO_STANDARD] == 1

    # 2ª chamada: estoura o timeout → indica timeout e preserva os dados anteriores.
    segunda = cliente.get("/api/estatisticas").json()
    assert segunda["timeout"] is True
    assert segunda["mensagem"] == MENSAGEM_TIMEOUT_ESTATISTICAS
    # Preserva o conteúdo e o horário do último sucesso (Req. 3.9).
    std_pub_segunda = {
        co["nome"]: co["valor"] for co in segunda["standard"]["publicadas_por_topico"]
    }
    assert std_pub_segunda[c.TOPICO_STANDARD] == 1
    assert segunda["ultima_atualizacao"] == horario_sucesso

    estado.encerrar()


def test_estatisticas_timeout_na_primeira_coleta_sem_cache() -> None:
    # Sem nenhum sucesso prévio, o timeout retorna indicação de timeout e corpo sem
    # dados (standard/fifo nulos), ainda assim respondendo (sem erro HTTP).
    def provedor():
        time.sleep(0.5)
        return []

    estado = EstadoEstatisticasSns(provedor, timeout_segundos=0.1)
    corpo = _cliente(estado_estatisticas=estado).get("/api/estatisticas").json()

    assert corpo["timeout"] is True
    assert corpo["standard"] is None
    assert corpo["fifo"] is None
    assert corpo["ultima_atualizacao"] is None
    assert corpo["mensagem"] == MENSAGEM_TIMEOUT_ESTATISTICAS

    estado.encerrar()
