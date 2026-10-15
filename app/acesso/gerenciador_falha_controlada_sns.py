"""Gerenciador_Falha_Controlada — acesso ao SQS para o round-trip de Access_Policy_Fila.

Camada de acesso que prepara e reverte a Falha_Entrega_Controlada manipulando a
Access_Policy_Fila da fila de destino da assinatura selecionada, de forma temporária
e reversível (ver ``design.md`` → seção "Gerenciador_Falha_Controlada").

Esta camada concentra o acesso ``boto3`` ao SQS; a lógica pura de montagem do
statement ``Deny`` e do round-trip de policy vive em
:mod:`app.dominio.falha_controlada_sns` (testável sem AWS).

Operações principais (assinaturas lógicas do design):

- ``salvar_policy_original(queue_url) -> dict | None``
- ``aplicar_deny_temporario(queue_url, topic_arn) -> None``
- ``restaurar_policy(queue_url, policy_original) -> ResultadoRestauracao``

Decisões de design relevantes:

- **Credenciais exclusivamente via IAM_Role_EC2.** O cliente ``boto3`` é criado sem
  Access Keys fixas; a resolução de credenciais fica a cargo da cadeia de provedores
  padrão do ``boto3`` (IAM Role da EC2) (Req. 12.1, 12.2).
- **Apenas ajuste reversível de Access_Policy_Fila.** Nunca exclui filas nem
  assinaturas; a única alteração de recurso AWS é o statement ``Deny`` temporário,
  revertido ao final (Req. 8.2, 8.8).
- **Erro original preservado em salvar/aplicar.** ``salvar_policy_original`` e
  ``aplicar_deny_temporario`` repassam o erro original da AWS sem mascarar.
- **Restauração tolerante a falha.** ``restaurar_policy`` captura o erro para
  sinalizar a fila afetada e orientar a restauração manual pelo Console AWS em
  pt-BR, sem relançar, de modo que o fluxo do teste de DLQ possa reportar o estado
  ao usuário (Req. 8.9).

Referências de requisitos: 8.2, 8.8, 8.9, 12.1, 12.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import boto3

from app.dominio import constantes_sns as c
from app.dominio import falha_controlada_sns as fc

# Nome do atributo de fila que carrega a Access_Policy_Fila (string JSON).
ATRIBUTO_POLICY: str = "Policy"


@dataclass(frozen=True)
class ResultadoRestauracao:
    """Resultado da tentativa de restaurar a Access_Policy_Fila original.

    Attributes:
        sucesso: ``True`` se a policy original foi restaurada integralmente.
        mensagem: mensagem em pt-BR; vazia em caso de sucesso, com a orientação de
            restauração manual pelo Console AWS em caso de falha (Req. 8.9).
        fila_afetada: nome/URL da fila afetada quando a restauração falha; vazio no
            sucesso.
    """

    sucesso: bool
    mensagem: str = ""
    fila_afetada: str = ""


class GerenciadorFalhaControlada:
    """Fachada sobre o cliente ``boto3`` do SQS para o round-trip de Access_Policy_Fila."""

    def __init__(
        self,
        cliente_sqs: Optional[Any] = None,
        regiao: str = c.REGIAO_AWS,
    ) -> None:
        """Inicializa o gerenciador.

        Args:
            cliente_sqs: cliente SQS já construído. Use APENAS em testes, para
                injetar um cliente simulado (mock/stub). Em produção, deixe ``None``
                para que o gerenciador crie o cliente ``boto3`` padrão.
            regiao: região AWS do laboratório (padrão ``us-east-1``).
        """
        # NÃO passamos aws_access_key_id/aws_secret_access_key: o boto3 resolve as
        # credenciais temporárias pela IAM Role da EC2 (Req. 12.1, 12.2).
        self._sqs = (
            cliente_sqs
            if cliente_sqs is not None
            else boto3.client("sqs", region_name=regiao)
        )

    # ------------------------------------------------------------------
    # Salvar
    # ------------------------------------------------------------------
    def salvar_policy_original(self, queue_url: str) -> dict[str, Any] | None:
        """Lê e retorna a Access_Policy_Fila original da fila, antes de alterá-la.

        Deve ser chamado **antes** de qualquer alteração (Req. 8.8). Retorna a policy
        já desserializada em dicionário, ou ``None`` quando a fila não possui policy.

        O erro original da AWS é repassado sem encapsulamento.
        """
        resposta = self._sqs.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=[ATRIBUTO_POLICY]
        )
        atributos = resposta.get("Attributes", {}) or {}
        return fc.desserializar_policy(atributos.get(ATRIBUTO_POLICY))

    # ------------------------------------------------------------------
    # Aplicar Deny temporário
    # ------------------------------------------------------------------
    def aplicar_deny_temporario(self, queue_url: str, topic_arn: str) -> None:
        """Aplica o statement ``Deny`` temporário à Access_Policy_Fila da fila.

        Lê a policy atual, adiciona o statement ``Deny`` para ``sns.amazonaws.com``
        com condição por ``SourceArn`` do tópico (sem excluir filas nem assinaturas)
        e grava a nova policy via ``SetQueueAttributes`` (Req. 8.2).

        O erro original da AWS é repassado sem encapsulamento.
        """
        policy_atual = self.salvar_policy_original(queue_url)
        nova_policy = fc.aplicar_deny(policy_atual, topic_arn)
        self._sqs.set_queue_attributes(
            QueueUrl=queue_url,
            Attributes={ATRIBUTO_POLICY: fc.serializar_policy(nova_policy)},
        )

    # ------------------------------------------------------------------
    # Restaurar
    # ------------------------------------------------------------------
    def restaurar_policy(
        self, queue_url: str, policy_original: dict[str, Any] | None
    ) -> ResultadoRestauracao:
        """Restaura integralmente a Access_Policy_Fila original (Req. 8.8).

        Grava novamente a ``policy_original`` salva antes do teste. Quando a fila não
        possuía policy originalmente (``policy_original is None``), remove o atributo
        ``Policy`` definindo-o como string vazia, o que o SQS interpreta como remoção
        da policy.

        Se a restauração falhar, **não relança**: retorna um
        :class:`ResultadoRestauracao` sinalizando a fila afetada e com a mensagem em
        pt-BR orientando a restauração manual pelo Console AWS (Req. 8.9).
        """
        try:
            if policy_original is None:
                # Policy ausente originalmente: remover o atributo (string vazia).
                self._sqs.set_queue_attributes(
                    QueueUrl=queue_url, Attributes={ATRIBUTO_POLICY: ""}
                )
            else:
                self._sqs.set_queue_attributes(
                    QueueUrl=queue_url,
                    Attributes={
                        ATRIBUTO_POLICY: fc.serializar_policy(policy_original)
                    },
                )
        except Exception as erro:  # noqa: BLE001 — queremos tolerar qualquer falha de AWS
            return ResultadoRestauracao(
                sucesso=False,
                mensagem=fc.mensagem_restauracao_manual(queue_url, str(erro)),
                fila_afetada=queue_url,
            )

        return ResultadoRestauracao(sucesso=True)
