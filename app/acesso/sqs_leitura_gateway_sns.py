"""Camada de leitura não destrutiva do Amazon SQS (SqsLeituraGateway).

Encapsula o cliente ``boto3`` do SQS **restrito a operações de leitura**, usado
pelo Verificador_Entrega para confirmar entregas lendo as filas de destino e as
DLQs de forma não destrutiva, correlacionando as mensagens pelo ID_Pedido.

Diferente do :class:`~app.acesso.sqs_gateway.SqsGateway` (que suporta o ciclo
completo de consumo, inclusive ``DeleteMessage``), esta camada expõe
exclusivamente a leitura por visualização: ela **nunca** chama ``DeleteMessage``.
Isso preserva as mensagens de outros testes e usuários nas filas compartilhadas
(leitura não destrutiva — Property 2).

Decisões de design relevantes a esta camada (ver ``design.md``, seção
*Verificador_Entrega e SqsLeituraGateway (leitura somente)*):

- **Leitura não destrutiva (sem DeleteMessage).** O gateway não possui qualquer
  método que exclua mensagens. Usa ``ReceiveMessage`` com ``VisibilityTimeout``
  curto, de modo que a mensagem apenas fique invisível por um breve período e
  volte a ficar disponível a outros testes/usuários (Req. 6.4, 10.4).
- **Long Polling.** ``receber_para_visualizacao`` usa ``WaitTimeSeconds`` entre
  1 e 20 segundos (Req. 10.5, 14.4); valores fora da faixa são rejeitados com
  ``ValueError`` antes de qualquer chamada à AWS.
- **MessageAttributes para correlação.** Sempre solicita todos os
  ``MessageAttributes`` e os expõe em cada mensagem lida, permitindo ao
  Verificador_Entrega correlacionar pelo ID_Pedido (via
  :func:`app.dominio.envelope_mensagem.extrair_id_pedido`) sem precisar
  desserializar o corpo (Req. 6.1, 10.1, 10.2).
- **Credenciais exclusivamente via IAM_Role_EC2.** O cliente ``boto3`` é criado
  sem qualquer Access Key fixa. O ``boto3`` resolve as credenciais temporárias
  pela cadeia de provedores padrão, que, na instância EC2 do laboratório, obtém
  as credenciais da IAM Role anexada (Req. 12.1, 12.2).
- **Repasse do erro original da AWS.** Nenhuma operação captura nem encapsula
  exceções do ``botocore``. Qualquer erro retornado pela AWS propaga intacto ao
  chamador, que decide como registrá-lo e exibi-lo (Req. 10.6, 14.4).

Referências de requisitos: 6.4, 10.4, 10.5, 14.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import boto3

from app.dominio import constantes_sns as c

# Visibility_Timeout curto (em segundos) usado na leitura por visualização.
# Mantém a mensagem invisível apenas pelo tempo mínimo de inspeção e, por nunca
# excluí-la, a devolve rapidamente à visibilidade de outros testes/usuários
# (leitura não destrutiva — Req. 6.4, 10.4).
VISIBILITY_TIMEOUT_CURTO_PADRAO: int = 2

# Limites de MaxNumberOfMessages por chamada ReceiveMessage, conforme o SQS
# (lotes de 1 a 10 mensagens).
MAX_NUMBER_OF_MESSAGES_MIN: int = 1
MAX_NUMBER_OF_MESSAGES_MAX: int = 10


@dataclass(frozen=True)
class MensagemVisualizada:
    """Representa uma mensagem lida de forma não destrutiva para visualização.

    Expõe o corpo (``body``, que carrega o envelope SNS) e os
    ``message_attributes`` necessários para a correlação pelo ID_Pedido. Não
    expõe nem usa ``ReceiptHandle``: como a leitura é não destrutiva, não há
    exclusão e, portanto, não há necessidade do handle de exclusão.
    """

    message_id: str
    body: str
    message_attributes: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def de_resposta_sqs(cls, mensagem: Mapping[str, Any]) -> "MensagemVisualizada":
        """Constrói a partir de um item do campo ``Messages`` do ReceiveMessage."""
        return cls(
            message_id=mensagem.get("MessageId", ""),
            body=mensagem.get("Body", ""),
            message_attributes=dict(mensagem.get("MessageAttributes", {}) or {}),
            attributes=dict(mensagem.get("Attributes", {}) or {}),
        )


class SqsLeituraGateway:
    """Fachada de **leitura somente** sobre o cliente ``boto3`` do SQS.

    Projetada para o Verificador_Entrega: lê as filas de destino e as DLQs de
    forma não destrutiva, nunca excluindo mensagens. O cliente ``boto3`` é
    construído sem Access Keys; a resolução de credenciais fica inteiramente a
    cargo da cadeia padrão do ``boto3`` (IAM Role da EC2), conforme Req. 12.1 e
    12.2.

    Esta classe **não** possui método de exclusão. A ausência de ``DeleteMessage``
    é intencional e faz parte do contrato (leitura não destrutiva — Req. 6.4,
    10.4; Property 2).
    """

    def __init__(
        self,
        cliente_sqs: Optional[Any] = None,
        regiao: str = c.REGIAO_AWS,
    ) -> None:
        """Inicializa o gateway de leitura.

        Args:
            cliente_sqs: cliente SQS já construído. Use APENAS em testes, para
                injetar um cliente simulado (mock/stub). Em produção, deixe
                ``None`` para que o gateway crie o cliente ``boto3`` padrão.
            regiao: região AWS do laboratório (padrão ``us-east-1``).
        """
        # Importante: NÃO passamos aws_access_key_id/aws_secret_access_key.
        # O boto3 resolve as credenciais temporárias pela IAM Role da EC2
        # através da cadeia de provedores padrão (Req. 12.1, 12.2).
        self._sqs = cliente_sqs if cliente_sqs is not None else boto3.client(
            "sqs", region_name=regiao
        )
        self._regiao = regiao

    # ------------------------------------------------------------------
    # Leitura não destrutiva (ReceiveMessage + Long Polling)
    # ------------------------------------------------------------------
    def receber_para_visualizacao(
        self,
        queue_url: str,
        *,
        wait_time_seconds: int = c.LONG_POLLING_MAX,
        visibility_timeout_s: int = VISIBILITY_TIMEOUT_CURTO_PADRAO,
        max_mensagens: int = MAX_NUMBER_OF_MESSAGES_MAX,
    ) -> list[MensagemVisualizada]:
        """Lê mensagens de uma fila para visualização, sem excluí-las.

        Executa ``ReceiveMessage`` com **Long Polling** e ``VisibilityTimeout``
        curto, retornando as mensagens lidas com seus ``MessageAttributes`` para
        correlação pelo ID_Pedido. **Nunca** chama ``DeleteMessage``: as
        mensagens voltam a ficar visíveis a outros testes/usuários assim que o
        ``VisibilityTimeout`` curto expira (leitura não destrutiva — Req. 6.4,
        10.4).

        Args:
            queue_url: URL da fila de destino ou DLQ a inspecionar.
            wait_time_seconds: WaitTimeSeconds do Long Polling, de 1 a 20
                segundos (Req. 10.5, 14.4). Padrão: 20 s (máximo), para o cenário
                padrão de verificação.
            visibility_timeout_s: Visibility_Timeout curto desta leitura, em
                segundos. Mantém a mensagem invisível apenas pelo tempo mínimo de
                inspeção; como não há exclusão, ela volta a ficar disponível.
            max_mensagens: tamanho do lote, de 1 a 10.

        Returns:
            Lista de :class:`MensagemVisualizada`. Um recebimento vazio retorna
            lista vazia, sem erro, para que o chamador repita a tentativa até o
            Timeout_Verificacao (Req. 10.6).

        Raises:
            ValueError: se ``wait_time_seconds`` estiver fora de 1–20 s ou
                ``max_mensagens`` fora de 1–10.
            Exception: qualquer erro da AWS é repassado sem encapsulamento
                (Req. 10.6, 14.4).
        """
        if not (c.LONG_POLLING_MIN <= wait_time_seconds <= c.LONG_POLLING_MAX):
            raise ValueError(
                "WaitTimeSeconds do Long Polling deve estar entre "
                f"{c.LONG_POLLING_MIN} e {c.LONG_POLLING_MAX} segundos "
                f"(valor informado: {wait_time_seconds})."
            )
        if not (MAX_NUMBER_OF_MESSAGES_MIN <= max_mensagens <= MAX_NUMBER_OF_MESSAGES_MAX):
            raise ValueError(
                "O lote (MaxNumberOfMessages) deve estar entre "
                f"{MAX_NUMBER_OF_MESSAGES_MIN} e {MAX_NUMBER_OF_MESSAGES_MAX} "
                f"mensagens (valor informado: {max_mensagens})."
            )

        resposta = self._sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_mensagens,
            WaitTimeSeconds=wait_time_seconds,
            VisibilityTimeout=visibility_timeout_s,
            # Solicita os atributos de sistema e, principalmente, todos os
            # MessageAttributes definidos na publicação (id_pedido, cenario)
            # para a correlação pelo ID_Pedido (Req. 6.1, 10.1, 10.2).
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        mensagens = resposta.get("Messages", []) or []
        return [MensagemVisualizada.de_resposta_sqs(m) for m in mensagens]
