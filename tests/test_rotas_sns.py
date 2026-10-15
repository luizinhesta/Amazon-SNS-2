"""Testes de integração dos endpoints de saúde e configuração do SNS (Tarefa 12.1).

Exercitam, via :class:`fastapi.testclient.TestClient` (httpx), os três endpoints do
roteador dedicado ao laboratório AWS SNS Delivery Lab, injetando um verificador de
inicialização com clientes boto3 simulados (SNS, SQS, IAM, EC2), sem AWS real:

- ``GET /api/saude``: sucesso quando todos os recursos estão disponíveis e
  ``saudavel=False`` com o recurso indisponível identificado por nome e tipo em
  pt-BR quando algum falta (Req. 1.9, 1.11);
- ``GET /api/config``: Config_Aplicada e Config_Simulacao com rótulos **distintos**,
  faixas da Config_Simulacao e orientação em pt-BR de que a Config_Aplicada só muda
  no Console AWS (Req. 2.1-2.6, 2.9);
- ``PUT /api/config/simulacao``: aceita valores dentro das faixas e os persiste;
  rejeita valores fora das faixas preservando o valor anterior e informando a faixa
  válida em pt-BR (Req. 2.5, 2.7, 2.8).

Referências de requisitos: 1.9, 1.11, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.estado_simulacao_sns import EstadoConfigSimulacaoSns
from app.api.rotas_sns import (
    ORIENTACAO_CONFIG_APLICADA,
    ROTULO_CONFIG_APLICADA,
    ROTULO_CONFIG_SIMULACAO,
    criar_app_sns,
)
from app.dominio import constantes_sns as c
from app.verificacao_inicializacao_sns import VerificacaoInicializacaoSns

NOME_IAM_ROLE = "delivery-sns-lab-role"
ID_INSTANCIA_EC2 = "i-0abc123def456"
REGIAO = c.REGIAO_AWS
CONTA = "123456789012"


# ---------------------------------------------------------------------------
# Clientes boto3 simulados (recursos presentes)
# ---------------------------------------------------------------------------
def _arn_topico(nome: str) -> str:
    return f"arn:aws:sns:{REGIAO}:{CONTA}:{nome}"


def _cliente_sns_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.list_topics.return_value = {
        "Topics": [{"TopicArn": _arn_topico(nome)} for nome in c.TOPICOS]
    }
    cliente.get_topic_attributes.return_value = {"Attributes": {"TopicArn": "x"}}

    def _subs(TopicArn: str, **_kw):
        nome = TopicArn.rsplit(":", 1)[-1]
        filas = c.FILAS_DESTINO_POR_TOPICO.get(nome, ())
        return {
            "Subscriptions": [
                {
                    "SubscriptionArn": f"arn:aws:sns:{REGIAO}:{CONTA}:{nome}:sub-{i}",
                    "Protocol": "sqs",
                    "Endpoint": f"arn:aws:sqs:{REGIAO}:{CONTA}:{fila}",
                }
                for i, fila in enumerate(filas)
            ]
        }

    cliente.list_subscriptions_by_topic.side_effect = _subs
    return cliente


def _cliente_sqs_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.get_queue_url.side_effect = lambda QueueName: {
        "QueueUrl": f"https://sqs.{REGIAO}.amazonaws.com/{CONTA}/{QueueName}"
    }
    cliente.get_queue_attributes.return_value = {
        "Attributes": {"QueueArn": "arn:aws:sqs:...:fila"}
    }
    return cliente


def _cliente_iam_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.get_role.return_value = {"Role": {"RoleName": NOME_IAM_ROLE}}
    return cliente


def _cliente_ec2_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": ID_INSTANCIA_EC2}]}]
    }
    return cliente


def _verificador_ok() -> VerificacaoInicializacaoSns:
    return VerificacaoInicializacaoSns(
        cliente_sns=_cliente_sns_ok(),
        cliente_sqs=_cliente_sqs_ok(),
        cliente_iam=_cliente_iam_ok(),
        cliente_ec2=_cliente_ec2_ok(),
        nome_iam_role=NOME_IAM_ROLE,
        id_instancia_ec2=ID_INSTANCIA_EC2,
    )


def _verificador_sem_ec2() -> VerificacaoInicializacaoSns:
    """Todos os recursos presentes, exceto a instância EC2 (nenhuma reserva)."""
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": []}
    return VerificacaoInicializacaoSns(
        cliente_sns=_cliente_sns_ok(),
        cliente_sqs=_cliente_sqs_ok(),
        cliente_iam=_cliente_iam_ok(),
        cliente_ec2=ec2,
        nome_iam_role=NOME_IAM_ROLE,
        id_instancia_ec2=ID_INSTANCIA_EC2,
    )


def _cliente(verificador: VerificacaoInicializacaoSns, estado=None) -> TestClient:
    app = criar_app_sns(
        estado_simulacao_sns=estado,
        verificador_inicializacao_sns=verificador,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/saude
# ---------------------------------------------------------------------------
def test_saude_sucesso_quando_todos_recursos_disponiveis() -> None:
    cliente = _cliente(_verificador_ok())

    resposta = cliente.get("/api/saude")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["saudavel"] is True
    # Todos os recursos checados devem estar disponíveis.
    assert corpo["recursos"], "esperava a lista de recursos verificados"
    assert all(r["disponivel"] for r in corpo["recursos"])
    assert all(r["detalhe_erro"] is None for r in corpo["recursos"])


def test_saude_falha_identifica_recurso_por_nome_e_tipo() -> None:
    cliente = _cliente(_verificador_sem_ec2())

    resposta = cliente.get("/api/saude")

    assert resposta.status_code == 200  # sempre responde (modo não interruptivo)
    corpo = resposta.json()
    assert corpo["saudavel"] is False
    # O último recurso checado é a instância EC2 indisponível.
    indisponiveis = [r for r in corpo["recursos"] if not r["disponivel"]]
    assert len(indisponiveis) == 1
    recurso = indisponiveis[0]
    assert recurso["tipo"] == "instância EC2"
    assert recurso["nome"] == ID_INSTANCIA_EC2
    assert recurso["detalhe_erro"]  # erro original preservado
    # Mensagem em pt-BR identifica o recurso por tipo e nome.
    assert "instância EC2" in corpo["mensagem"]
    assert ID_INSTANCIA_EC2 in corpo["mensagem"]


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------
def test_config_separa_aplicada_e_simulacao_com_rotulos_distintos() -> None:
    cliente = _cliente(_verificador_ok())

    corpo = cliente.get("/api/config").json()

    aplicada = corpo["config_aplicada"]
    simulacao = corpo["config_simulacao"]
    assert aplicada and simulacao

    # Rótulos distintos e consistentes com a classificação.
    assert all(p["rotulo"] == ROTULO_CONFIG_APLICADA for p in aplicada)
    assert all(p["rotulo"] == ROTULO_CONFIG_SIMULACAO for p in simulacao)
    assert ROTULO_CONFIG_APLICADA != ROTULO_CONFIG_SIMULACAO

    # Config_Aplicada não é ajustável; Config_Simulacao é.
    assert all(p["ajustavel"] is False for p in aplicada)
    assert all(p["ajustavel"] is True for p in simulacao)

    # Orientação de que a Config_Aplicada só muda no Console AWS (Req. 2.9).
    assert corpo["orientacao_config_aplicada"] == ORIENTACAO_CONFIG_APLICADA
    assert "Console AWS" in corpo["orientacao_config_aplicada"]
    assert all(p["orientacao"] for p in aplicada)


def test_config_aplicada_cobre_tipos_dedup_e_policies() -> None:
    cliente = _cliente(_verificador_ok())

    aplicada = cliente.get("/api/config").json()["config_aplicada"]
    texto = " | ".join(f"{p['nome']}={p['valor']}" for p in aplicada)

    # Tipos de tópico (Req. 2.1).
    assert "Standard" in texto and "FIFO" in texto
    # Redrive_Policy_SNS aponta para as DLQs compatíveis (Req. 2.2).
    assert c.DLQ_SNS_STANDARD in texto and c.DLQ_SNS_FIFO in texto
    # Deduplicacao_Por_Conteudo do Topico_FIFO (Req. 2.3).
    assert any("Deduplicacao_Por_Conteudo" in p["nome"] for p in aplicada)
    # Access_Policy_Fila (Req. 2.4).
    assert any("Access_Policy_Fila" in p["nome"] for p in aplicada)


def test_config_simulacao_expoe_faixas_dos_timeouts() -> None:
    cliente = _cliente(_verificador_ok())

    simulacao = cliente.get("/api/config").json()["config_simulacao"]
    por_nome = {p["nome"]: p for p in simulacao}

    entrega = por_nome["Timeout_Verificacao_Entrega"]
    assert entrega["valor"] == c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO
    assert entrega["faixa_minima"] == c.TIMEOUT_VERIFICACAO_ENTREGA_MIN
    assert entrega["faixa_maxima"] == c.TIMEOUT_VERIFICACAO_ENTREGA_MAX

    dlq = por_nome["Timeout_Verificacao_DLQ"]
    assert dlq["valor"] == c.TIMEOUT_VERIFICACAO_DLQ_PADRAO
    assert dlq["faixa_minima"] == c.TIMEOUT_VERIFICACAO_DLQ_MIN
    assert dlq["faixa_maxima"] == c.TIMEOUT_VERIFICACAO_DLQ_MAX


# ---------------------------------------------------------------------------
# PUT /api/config/simulacao
# ---------------------------------------------------------------------------
def test_ajuste_dentro_das_faixas_e_aceito_e_persistido() -> None:
    estado = EstadoConfigSimulacaoSns()
    cliente = _cliente(_verificador_ok(), estado=estado)

    resposta = cliente.put(
        "/api/config/simulacao",
        json={
            "timeout_verificacao_entrega_segundos": 60,
            "timeout_verificacao_dlq_segundos": 200,
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert all(a["aceito"] for a in corpo["ajustes"])
    por_nome = {a["parametro"]: a for a in corpo["ajustes"]}
    assert por_nome["Timeout_Verificacao_Entrega"]["valor_efetivo"] == 60
    assert por_nome["Timeout_Verificacao_DLQ"]["valor_efetivo"] == 200

    # Persistência: uma nova leitura reflete os valores aceitos.
    valores = estado.valores()
    assert valores.timeout_verificacao_entrega_segundos == 60
    assert valores.timeout_verificacao_dlq_segundos == 200


def test_ajuste_fora_da_faixa_e_rejeitado_e_preserva_valor_anterior() -> None:
    estado = EstadoConfigSimulacaoSns()
    cliente = _cliente(_verificador_ok(), estado=estado)

    # 4 está abaixo do mínimo (5) do Timeout_Verificacao_Entrega.
    resposta = cliente.put(
        "/api/config/simulacao",
        json={"timeout_verificacao_entrega_segundos": 4},
    )

    assert resposta.status_code == 200
    ajuste = resposta.json()["ajustes"][0]
    assert ajuste["aceito"] is False
    # Valor anterior preservado (padrão do laboratório).
    assert ajuste["valor_efetivo"] == c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO
    # Mensagem em pt-BR com a faixa válida.
    assert str(c.TIMEOUT_VERIFICACAO_ENTREGA_MIN) in ajuste["mensagem"]
    assert str(c.TIMEOUT_VERIFICACAO_ENTREGA_MAX) in ajuste["mensagem"]

    # Estado inalterado após a rejeição.
    assert (
        estado.valores().timeout_verificacao_entrega_segundos
        == c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO
    )


def test_ajuste_dlq_fora_da_faixa_informa_faixa_valida() -> None:
    cliente = _cliente(_verificador_ok())

    # 10 está abaixo do mínimo (30) do Timeout_Verificacao_DLQ.
    corpo = cliente.put(
        "/api/config/simulacao",
        json={"timeout_verificacao_dlq_segundos": 10},
    ).json()

    ajuste = corpo["ajustes"][0]
    assert ajuste["parametro"] == "Timeout_Verificacao_DLQ"
    assert ajuste["aceito"] is False
    assert ajuste["valor_efetivo"] == c.TIMEOUT_VERIFICACAO_DLQ_PADRAO
    assert str(c.TIMEOUT_VERIFICACAO_DLQ_MIN) in ajuste["mensagem"]
    assert str(c.TIMEOUT_VERIFICACAO_DLQ_MAX) in ajuste["mensagem"]
