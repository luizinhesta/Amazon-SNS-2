"""Camada de acesso ao Amazon SNS (SnsGateway).

Encapsula o cliente ``boto3`` do SNS e centraliza a publicação em tópicos
Standard e FIFO e a consulta das assinaturas de um tópico, usadas pela
API_Backend e pelo Gerenciador_Falha_Controlada.

O módulo recebe o sufixo ``_sns`` (``sns_gateway.py``) para conviver, sem
colisão, com a camada de acesso ao SQS do laboratório (``sqs_gateway.py``).

Decisões de design relevantes a esta camada (ver ``design.md``, seção
"SnsGateway"):

- **Credenciais exclusivamente via IAM_Role_EC2.** O cliente ``boto3`` é criado
  sem qualquer Access Key fixa (``aws_access_key_id``/``aws_secret_access_key``).
  O ``boto3`` resolve as credenciais temporárias automaticamente pela cadeia de
  provedores padrão, que, na instância EC2 do laboratório, obtém as credenciais
  da IAM Role anexada via metadata service (IMDSv2). Nenhuma Access Key é lida de
  código, configuração ou variável de ambiente (Req. 12.1, 12.2).
- **FIFO sempre com MessageGroupId.** Toda publicação no Topico_FIFO informa o
  ``MessageGroupId``; uma publicação FIFO sem ``MessageGroupId`` é rejeitada com
  ``ValueError`` ANTES de qualquer chamada ao SNS (Req. 5.5, 11.5).
- **MessageDeduplicationId condicionado à Deduplicacao_Por_Conteudo.** O
  ``MessageDeduplicationId`` só é enviado quando a Deduplicacao_Por_Conteudo do
  Topico_FIFO está DESABILITADA. Como no laboratório ela está habilitada por
  padrão (``DEDUPLICACAO_POR_CONTEUDO_FIFO = True``), o id não é solicitado nem
  repassado; se habilitada, um ``MessageDeduplicationId`` informado é ignorado
  para respeitar a Config_Aplicada (Req. 5.3, 5.4, 11.3).
- **Retorno do MessageId.** As publicações retornam o ``MessageId`` que o SNS
  devolve, para registro como Evento_Observado de Entrega_Publicada
  (Req. 4.2, 4.3, 5.5, 5.6).
- **Repasse do erro original da AWS.** Nenhuma operação captura nem encapsula
  exceções do ``botocore`` (por exemplo, ``ClientError``). Qualquer erro retornado
  pela AWS propaga intacto ao chamador, que decide como registrá-lo e exibi-lo
  (Req. 4.8, 5.10).

Referências de requisitos: 4.2, 4.8, 5.3, 5.4, 5.5, 5.6, 5.10, 11.3, 11.5,
12.1, 12.2.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import boto3

from app.dominio import constantes_sns as c
from app.dominio.envelope_mensagem import PayloadAplicacao


class SnsGateway:
    """Fachada sobre o cliente ``boto3`` do SNS.

    O gateway é criado uma única vez e reutilizado pela aplicação. O cliente
    ``boto3`` é construído sem Access Keys: a resolução de credenciais fica
    inteiramente a cargo da cadeia padrão do ``boto3`` (IAM Role da EC2),
    conforme Req. 12.1 e 12.2.
    """

    def __init__(
        self,
        cliente_sns: Optional[Any] = None,
        regiao: str = c.REGIAO_AWS,
        *,
        deduplicacao_por_conteudo_fifo: bool = c.DEDUPLICACAO_POR_CONTEUDO_FIFO,
    ) -> None:
        """Inicializa o gateway.

        Args:
            cliente_sns: cliente SNS já construído. Use APENAS em testes, para
                injetar um cliente simulado (mock/stub). Em produção, deixe
                ``None`` para que o gateway crie o cliente ``boto3`` padrão.
            regiao: região AWS do laboratório (padrão ``us-east-1``).
            deduplicacao_por_conteudo_fifo: reflete a Config_Aplicada da
                Deduplicacao_Por_Conteudo do Topico_FIFO. Quando ``True`` (padrão
                do laboratório), o ``MessageDeduplicationId`` NÃO é enviado nas
                publicações FIFO, pois o SNS o deriva do conteúdo; quando
                ``False``, o id informado é repassado ao SNS (Req. 5.3, 5.4,
                11.3).
        """
        # Importante: NÃO passamos aws_access_key_id/aws_secret_access_key.
        # O boto3 resolve as credenciais temporárias pela IAM Role da EC2
        # através da cadeia de provedores padrão (Req. 12.1, 12.2).
        self._sns = cliente_sns if cliente_sns is not None else boto3.client(
            "sns", region_name=regiao
        )
        self._regiao = regiao
        self._deduplicacao_por_conteudo_fifo = deduplicacao_por_conteudo_fifo

    # ------------------------------------------------------------------
    # Publicação Standard
    # ------------------------------------------------------------------
    def publicar_standard(
        self,
        topic_arn: str,
        payload: PayloadAplicacao,
    ) -> str:
        """Publica uma mensagem no Topico_Standard (Publish) e retorna o MessageId.

        O corpo da publicação é o envelope de aplicação serializado em JSON e os
        ``MessageAttributes`` carregam ``id_pedido`` e ``cenario`` para a
        correlação pelo ID_Pedido (Req. 4.2, 4.3, 6.3).

        O erro original da AWS é repassado sem encapsulamento (Req. 4.8).

        Args:
            topic_arn: ARN do Topico_Standard de destino.
            payload: envelope de aplicação a publicar.

        Returns:
            O ``MessageId`` retornado pelo SNS.
        """
        resposta = self._sns.publish(
            TopicArn=topic_arn,
            Message=payload.para_json(),
            MessageAttributes=payload.message_attributes(),
        )
        return resposta["MessageId"]

    # ------------------------------------------------------------------
    # Publicação FIFO
    # ------------------------------------------------------------------
    def publicar_fifo(
        self,
        topic_arn: str,
        payload: PayloadAplicacao,
        message_group_id: Optional[str],
        message_deduplication_id: Optional[str] = None,
    ) -> str:
        """Publica uma mensagem no Topico_FIFO (Publish) e retorna o MessageId.

        Regras FIFO (ver ``design.md``):

        - ``message_group_id`` é obrigatório: uma publicação FIFO sem
          ``MessageGroupId`` é rejeitada com ``ValueError`` ANTES de qualquer
          chamada ao SNS (Req. 5.5, 11.5).
        - ``message_deduplication_id`` só é enviado quando a
          Deduplicacao_Por_Conteudo está DESABILITADA. Com ela habilitada
          (padrão do laboratório), o id é ignorado, pois o SNS o deriva do
          conteúdo (Req. 5.3, 5.4, 11.3).

        O erro original da AWS é repassado sem encapsulamento (Req. 5.10).

        Args:
            topic_arn: ARN do Topico_FIFO de destino.
            payload: envelope de aplicação a publicar.
            message_group_id: identificador do grupo FIFO (obrigatório,
                1–128 caracteres).
            message_deduplication_id: identificador de deduplicação; usado
                apenas quando a Deduplicacao_Por_Conteudo está desabilitada.

        Returns:
            O ``MessageId`` retornado pelo SNS.

        Raises:
            ValueError: se ``message_group_id`` for ``None`` ou vazio.
        """
        # Rejeição ANTES da chamada ao SNS (Req. 11.5): FIFO sem MessageGroupId.
        if message_group_id is None or message_group_id == "":
            raise ValueError(
                "Publicação FIFO exige MessageGroupId: o campo é obrigatório "
                "para o Topico_FIFO e não pode ser ausente ou vazio."
            )

        parametros: dict[str, Any] = {
            "TopicArn": topic_arn,
            "Message": payload.para_json(),
            "MessageAttributes": payload.message_attributes(),
            "MessageGroupId": message_group_id,
        }
        # MessageDeduplicationId apenas quando a dedup por conteúdo está
        # DESABILITADA e um id foi informado (Req. 5.3, 5.4, 11.3).
        if not self._deduplicacao_por_conteudo_fifo and message_deduplication_id:
            parametros["MessageDeduplicationId"] = message_deduplication_id

        resposta = self._sns.publish(**parametros)
        return resposta["MessageId"]

    # ------------------------------------------------------------------
    # Consulta de assinaturas
    # ------------------------------------------------------------------
    def obter_assinaturas(self, topic_arn: str) -> list[Mapping[str, Any]]:
        """Lista as assinaturas de um tópico (ListSubscriptionsByTopic).

        Pagina automaticamente via ``NextToken`` e retorna a lista completa de
        assinaturas (cada item no formato bruto do SNS, com ``SubscriptionArn``,
        ``Protocol``, ``Endpoint``, etc.), usada pelo Gerenciador_Falha_Controlada
        para selecionar a Assinatura_SNS e identificar a fila de destino.

        O erro original da AWS é repassado sem encapsulamento (Req. 4.8, 5.10).

        Args:
            topic_arn: ARN do tópico cujas assinaturas serão listadas.

        Returns:
            A lista de assinaturas do tópico.
        """
        assinaturas: list[Mapping[str, Any]] = []
        next_token: Optional[str] = None
        while True:
            if next_token is None:
                resposta = self._sns.list_subscriptions_by_topic(TopicArn=topic_arn)
            else:
                resposta = self._sns.list_subscriptions_by_topic(
                    TopicArn=topic_arn, NextToken=next_token
                )
            assinaturas.extend(resposta.get("Subscriptions", []) or [])
            next_token = resposta.get("NextToken")
            if not next_token:
                break
        return assinaturas
