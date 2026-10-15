"""Testes unitários da verificação de inicialização do laboratório SNS (Tarefa 9.1).

Validam, com clientes boto3 simulados injetados (SNS, SQS, IAM, EC2), sem AWS real:

- recursos presentes: dois tópicos, seis assinaturas, seis filas de destino, duas
  DLQs, IAM Role e instância EC2 disponíveis → sucesso (Req. 1.9);
- recursos ausentes/inacessíveis: cada tipo faltando → falha identificando o recurso
  por nome e tipo em pt-BR e preservando o erro original (Req. 1.11);
- interrupção *fail-fast* sem alterar recursos: para no primeiro indisponível e não
  executa operações de escrita/criação/exclusão (Req. 1.10);
- timeout por recurso: uma leitura que excede o prazo marca o recurso como
  indisponível com TimeoutError (Req. 1.9);
- modo sem interrupção: devolve o relatório com sucesso=False sem levantar exceção.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.dominio import constantes_sns as c
from app.verificacao_inicializacao_sns import (
    FalhaVerificacaoInicializacaoSns,
    TipoRecurso,
    VerificacaoInicializacaoSns,
)

NOME_IAM_ROLE = "delivery-sns-lab-role"
ID_INSTANCIA_EC2 = "i-0abc123def456"
REGIAO = c.REGIAO_AWS
CONTA = "123456789012"


class _ErroAwsSimulado(Exception):
    """Erro que imita uma exceção do botocore (ex.: ClientError)."""


def _arn_topico(nome: str) -> str:
    return f"arn:aws:sns:{REGIAO}:{CONTA}:{nome}"


def _cliente_sns_ok() -> MagicMock:
    """Cliente SNS simulado: dois tópicos existentes, cada um com 3 assinaturas."""
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
    """Cliente SQS simulado: todas as filas e DLQs existem e são acessíveis."""
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


def _verificador(**overrides) -> VerificacaoInicializacaoSns:
    """Monta o verificador com clientes OK, aceitando substituições por teste."""
    clientes = {
        "cliente_sns": _cliente_sns_ok(),
        "cliente_sqs": _cliente_sqs_ok(),
        "cliente_iam": _cliente_iam_ok(),
        "cliente_ec2": _cliente_ec2_ok(),
    }
    clientes.update(overrides)
    return VerificacaoInicializacaoSns(
        nome_iam_role=NOME_IAM_ROLE,
        id_instancia_ec2=ID_INSTANCIA_EC2,
        **clientes,
    )


# --- Recursos presentes ------------------------------------------------------


def test_todos_os_recursos_presentes_retorna_sucesso() -> None:
    relatorio = _verificador().verificar_recursos()

    assert relatorio.sucesso is True
    assert relatorio.recurso_indisponivel is None
    assert relatorio.erro_original is None
    # 2 tópicos + 2 assinaturas (uma checagem por tópico) + 6 filas + 2 DLQs
    # + 1 IAM Role + 1 EC2 = 14 recursos verificados.
    esperado = len(c.TOPICOS) * 2 + len(c.FILAS_DESTINO) + len(c.DLQS) + 2
    assert len(relatorio.recursos) == esperado
    assert all(r.disponivel for r in relatorio.recursos)


def test_verifica_os_tipos_esperados_na_ordem() -> None:
    relatorio = _verificador().verificar_recursos()
    tipos = [r.tipo for r in relatorio.recursos]

    assert tipos[: len(c.TOPICOS)] == [TipoRecurso.TOPICO] * len(c.TOPICOS)
    assert relatorio.recursos[-2].tipo is TipoRecurso.IAM_ROLE
    assert relatorio.recursos[-1].tipo is TipoRecurso.INSTANCIA_EC2
    assert relatorio.recursos[-2].nome == NOME_IAM_ROLE
    assert relatorio.recursos[-1].nome == ID_INSTANCIA_EC2


def test_verificacao_e_somente_leitura_nao_altera_recursos() -> None:
    cliente_sns = _cliente_sns_ok()
    cliente_sqs = _cliente_sqs_ok()
    cliente_iam = _cliente_iam_ok()
    cliente_ec2 = _cliente_ec2_ok()

    _verificador(
        cliente_sns=cliente_sns,
        cliente_sqs=cliente_sqs,
        cliente_iam=cliente_iam,
        cliente_ec2=cliente_ec2,
    ).verificar_recursos()

    # Nenhuma operação de escrita/criação/exclusão foi chamada (Req. 1.10).
    cliente_sns.create_topic.assert_not_called()
    cliente_sns.delete_topic.assert_not_called()
    cliente_sns.publish.assert_not_called()
    cliente_sqs.send_message.assert_not_called()
    cliente_sqs.delete_message.assert_not_called()
    cliente_sqs.create_queue.assert_not_called()
    cliente_sqs.delete_queue.assert_not_called()
    cliente_sqs.set_queue_attributes.assert_not_called()
    cliente_ec2.terminate_instances.assert_not_called()


# --- Tópico ausente ----------------------------------------------------------


def test_topico_ausente_levanta_falha_identificando_nome_e_tipo() -> None:
    cliente_sns = _cliente_sns_ok()
    # Nenhum tópico listado → o primeiro tópico esperado não é encontrado.
    cliente_sns.list_topics.return_value = {"Topics": []}

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_sns=cliente_sns).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.TOPICO
    assert recurso.nome == c.TOPICO_STANDARD
    assert "tópico SNS" in exc.value.relatorio.mensagem_pt_br
    assert c.TOPICO_STANDARD in exc.value.relatorio.mensagem_pt_br


def test_topico_inacessivel_preserva_erro_original_da_aws() -> None:
    cliente_sns = _cliente_sns_ok()
    erro = _ErroAwsSimulado("AuthorizationError")
    cliente_sns.get_topic_attributes.side_effect = erro

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_sns=cliente_sns).verificar_recursos()

    assert exc.value.erro_original is erro
    assert exc.value.__cause__ is erro


# --- Assinaturas incompletas -------------------------------------------------


def test_assinaturas_incompletas_falha_no_tipo_assinatura() -> None:
    cliente_sns = _cliente_sns_ok()
    # Topicos existem (get_topic_attributes ok), mas sem assinaturas confirmadas.
    cliente_sns.list_subscriptions_by_topic.side_effect = None
    cliente_sns.list_subscriptions_by_topic.return_value = {"Subscriptions": []}

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_sns=cliente_sns).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.ASSINATURA
    assert "assinatura SNS" in exc.value.relatorio.mensagem_pt_br


# --- Fila de destino / DLQ ausente -------------------------------------------


def test_fila_destino_ausente_levanta_falha_identificando_tipo() -> None:
    cliente_sqs = _cliente_sqs_ok()
    erro = _ErroAwsSimulado("AWS.SimpleQueueService.NonExistentQueue")
    cliente_sqs.get_queue_url.side_effect = erro

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_sqs=cliente_sqs).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.FILA_DESTINO
    assert recurso.nome == c.FILAS_DESTINO[0]
    assert recurso.erro_original is erro
    assert "fila de destino" in exc.value.relatorio.mensagem_pt_br


def test_dlq_ausente_so_e_verificada_apos_filas_de_destino() -> None:
    cliente_sqs = _cliente_sqs_ok()
    # Falha apenas na primeira DLQ; filas de destino continuam acessíveis.
    def _get_url(QueueName: str):
        if QueueName in c.DLQS:
            raise _ErroAwsSimulado("DLQ inexistente")
        return {"QueueUrl": f"https://sqs.{REGIAO}.amazonaws.com/{CONTA}/{QueueName}"}

    cliente_sqs.get_queue_url.side_effect = _get_url

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_sqs=cliente_sqs).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.DLQ
    assert recurso.nome == c.DLQS[0]
    # As seis filas de destino foram verificadas (disponíveis) antes das DLQs.
    filas_ok = [
        r for r in exc.value.relatorio.recursos if r.tipo is TipoRecurso.FILA_DESTINO
    ]
    assert len(filas_ok) == len(c.FILAS_DESTINO)
    assert all(r.disponivel for r in filas_ok)


# --- IAM Role / EC2 ausente --------------------------------------------------


def test_iam_role_ausente_levanta_falha_identificando_tipo() -> None:
    cliente_iam = _cliente_iam_ok()
    erro = _ErroAwsSimulado("NoSuchEntity")
    cliente_iam.get_role.side_effect = erro

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_iam=cliente_iam).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.IAM_ROLE
    assert recurso.nome == NOME_IAM_ROLE
    assert recurso.erro_original is erro
    assert "IAM Role" in exc.value.relatorio.mensagem_pt_br


def test_instancia_ec2_ausente_levanta_falha_identificando_tipo() -> None:
    cliente_ec2 = _cliente_ec2_ok()
    cliente_ec2.describe_instances.return_value = {"Reservations": []}

    with pytest.raises(FalhaVerificacaoInicializacaoSns) as exc:
        _verificador(cliente_ec2=cliente_ec2).verificar_recursos()

    recurso = exc.value.relatorio.recurso_indisponivel
    assert recurso is not None
    assert recurso.tipo is TipoRecurso.INSTANCIA_EC2
    assert recurso.nome == ID_INSTANCIA_EC2
    assert "instância EC2" in exc.value.relatorio.mensagem_pt_br


# --- Timeout por recurso -----------------------------------------------------


def test_timeout_por_recurso_marca_indisponivel_com_timeout_error() -> None:
    verificador = _verificador()

    def _demorado(_nome: str):
        time.sleep(0.3)

    # Força a leitura do tópico a demorar além do prazo de 0,05s.
    verificador._ler_topico = _demorado  # type: ignore[assignment]
    status = verificador.verificar_recurso(
        TipoRecurso.TOPICO, c.TOPICO_STANDARD, timeout_s=0  # 0 → timeout imediato
    )

    assert status.disponivel is False
    assert isinstance(status.erro_original, TimeoutError)


# --- Modo sem interrupção ----------------------------------------------------


def test_sem_interromper_em_falha_retorna_relatorio_sem_excecao() -> None:
    cliente_iam = _cliente_iam_ok()
    erro = _ErroAwsSimulado("acesso negado")
    cliente_iam.get_role.side_effect = erro

    relatorio = _verificador(cliente_iam=cliente_iam).verificar_recursos(
        interromper_em_falha=False
    )

    assert relatorio.sucesso is False
    assert relatorio.recurso_indisponivel is not None
    assert relatorio.recurso_indisponivel.tipo is TipoRecurso.IAM_ROLE
    assert relatorio.erro_original is erro
