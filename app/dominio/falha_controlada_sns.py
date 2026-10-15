"""Lógica pura da Falha_Entrega_Controlada (round-trip de Access_Policy_Fila).

Este módulo concentra a parte **testável sem AWS** do Gerenciador_Falha_Controlada
(ver ``design.md`` → seção "Gerenciador_Falha_Controlada"):

- montagem do statement ``Deny`` temporário para o principal ``sns.amazonaws.com``,
  com condição por ``SourceArn`` do tópico correspondente (Req. 8.2);
- aplicação desse statement sobre uma Access_Policy_Fila existente, produzindo uma
  nova policy, **sem** excluir filas nem assinaturas (Req. 8.2);
- round-trip (aplicar o ``Deny`` e, em seguida, restaurar a policy original)
  preservando estruturalmente a policy original (Correctness Property 5, Req. 8.2,
  8.8);
- a mensagem em pt-BR de orientação para restauração manual pelo Console AWS quando
  a restauração automática falha (Req. 8.9).

Nenhuma função aqui chama a AWS: elas operam sobre dicionários Python que
representam a Access_Policy_Fila (o conteúdo do atributo ``Policy`` da fila, já
desserializado de JSON). A camada de acesso (:mod:`app.acesso.gerenciador_falha_controlada_sns`)
é quem lê/grava a policy via ``boto3``.

Referências de requisitos: 8.2, 8.8, 8.9.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Final, Mapping

# Prefixo do Sid (Statement ID) do statement Deny temporário. O Sid é determinístico
# e inclui o nome lógico do tópico para permitir localizar e remover exatamente o
# statement inserido durante a restauração, sem afetar os demais statements da policy.
PREFIXO_SID_DENY: Final[str] = "DenyFalhaControlada"

# Principal do serviço SNS que publica nas filas de destino (Req. 8.2).
PRINCIPAL_SNS: Final[str] = "sns.amazonaws.com"

# Ação negada: entrega de mensagem do SNS na fila de destino.
ACAO_SQS_SEND_MESSAGE: Final[str] = "SQS:SendMessage"

# Versão padrão de uma Access_Policy_Fila recém-criada quando a fila ainda não
# possui policy alguma (o SQS aceita a data de versão "2012-10-17").
VERSAO_POLICY_PADRAO: Final[str] = "2012-10-17"


def _sid_deny(topic_arn: str) -> str:
    """Monta o Sid determinístico do statement Deny para um tópico.

    O Sid combina o prefixo fixo com um sufixo derivado do ``topic_arn`` para que o
    statement inserido seja localizável de forma inequívoca na restauração. Mantém
    apenas caracteres alfanuméricos (exigência de Sid do IAM/SQS).
    """
    sufixo = "".join(ch for ch in topic_arn if ch.isalnum())
    return f"{PREFIXO_SID_DENY}{sufixo}"


def montar_statement_deny(topic_arn: str) -> dict[str, Any]:
    """Monta o statement ``Deny`` temporário da Falha_Entrega_Controlada.

    Produz um statement que **nega** ao principal ``sns.amazonaws.com`` a ação
    ``SQS:SendMessage``, condicionado ao ``SourceArn`` do tópico informado. Assim, o
    SNS daquele tópico específico deixa de conseguir entregar na fila de destino,
    forçando o encaminhamento para a DLQ da assinatura — sem excluir filas nem
    assinaturas (Req. 8.2).

    Args:
        topic_arn: ARN do tópico SNS correspondente à assinatura sob teste.

    Returns:
        O statement ``Deny`` como dicionário, pronto para ser inserido na lista
        ``Statement`` da Access_Policy_Fila.

    Raises:
        ValueError: se ``topic_arn`` for vazio ou apenas espaços.
    """
    if not topic_arn or not topic_arn.strip():
        raise ValueError(
            "O ARN do tópico é obrigatório para montar o statement Deny."
        )

    return {
        "Sid": _sid_deny(topic_arn),
        "Effect": "Deny",
        "Principal": {"Service": PRINCIPAL_SNS},
        "Action": ACAO_SQS_SEND_MESSAGE,
        "Resource": "*",
        "Condition": {"ArnEquals": {"aws:SourceArn": topic_arn}},
    }


def aplicar_deny(
    policy_original: Mapping[str, Any] | None, topic_arn: str
) -> dict[str, Any]:
    """Aplica o statement ``Deny`` temporário sobre a Access_Policy_Fila.

    Retorna uma **nova** policy (sem mutar a original) contendo todos os statements
    originais mais o statement ``Deny`` da Falha_Entrega_Controlada. Se a fila não
    possuía policy (``None`` ou vazia), cria uma policy mínima apenas com o ``Deny``.

    Se já existir um statement ``Deny`` com o mesmo ``Sid`` (reaplicação), ele é
    substituído para manter a operação idempotente, sem duplicar statements.

    Args:
        policy_original: a Access_Policy_Fila atual, já desserializada de JSON, ou
            ``None`` quando a fila não possui policy.
        topic_arn: ARN do tópico SNS correspondente.

    Returns:
        A nova Access_Policy_Fila com o statement ``Deny`` aplicado.
    """
    statement_deny = montar_statement_deny(topic_arn)

    if not policy_original:
        return {
            "Version": VERSAO_POLICY_PADRAO,
            "Statement": [statement_deny],
        }

    nova_policy = copy.deepcopy(dict(policy_original))

    statements_brutos = nova_policy.get("Statement", [])
    # O campo Statement pode vir como um único objeto ou uma lista; normaliza em lista.
    if isinstance(statements_brutos, list):
        statements = list(statements_brutos)
    else:
        statements = [statements_brutos]

    sid_deny = statement_deny["Sid"]
    # Remove qualquer statement anterior com o mesmo Sid (idempotência de reaplicação).
    statements = [
        s for s in statements if not (isinstance(s, dict) and s.get("Sid") == sid_deny)
    ]
    statements.append(statement_deny)

    nova_policy["Statement"] = statements
    # Garante a presença de Version mesmo quando a policy original não a trazia.
    nova_policy.setdefault("Version", VERSAO_POLICY_PADRAO)
    return nova_policy


def serializar_policy(policy: Mapping[str, Any]) -> str:
    """Serializa uma Access_Policy_Fila para a string JSON esperada pelo SQS.

    O atributo ``Policy`` de uma fila é uma string JSON. As chaves são ordenadas de
    forma determinística para facilitar comparações estruturais em testes.
    """
    return json.dumps(dict(policy), sort_keys=True, separators=(",", ":"))


def desserializar_policy(policy_json: str | None) -> dict[str, Any] | None:
    """Desserializa a string JSON do atributo ``Policy`` em um dicionário.

    Retorna ``None`` quando a fila não possui policy (``None`` ou string vazia), o
    que representa uma Access_Policy_Fila ausente.
    """
    if policy_json is None or not policy_json.strip():
        return None
    return json.loads(policy_json)


def mensagem_restauracao_manual(nome_fila: str, erro: str) -> str:
    """Monta a mensagem em pt-BR de orientação à restauração manual (Req. 8.9).

    Quando a restauração automática da Access_Policy_Fila falha, o Dashboard deve
    identificar a fila afetada e orientar o usuário a restaurar a policy manualmente
    pelo Console AWS, para que o statement ``Deny`` temporário não permaneça ativo.

    Args:
        nome_fila: nome (ou URL) da fila de destino afetada.
        erro: descrição do erro original ocorrido na restauração.

    Returns:
        Mensagem em português do Brasil pronta para exibição no Dashboard.
    """
    return (
        "Falha ao restaurar automaticamente a Access_Policy_Fila da fila "
        f"'{nome_fila}'. O statement Deny temporário da falha de entrega controlada "
        "pode continuar ativo. Restaure a policy original manualmente pelo Console "
        "AWS (Amazon SQS → selecione a fila → aba 'Política de acesso' → edite a "
        "policy removendo o statement de Deny ou colando a policy original). "
        f"Detalhe do erro: {erro}"
    )
