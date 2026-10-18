"""Envelope de mensagem publicada e extração de ID_Pedido (Tarefa 2.1).

Este módulo define, como lógica de domínio pura (sem efeitos colaterais nem
dependência de boto3):

- :class:`PayloadAplicacao`: a estrutura do payload de aplicação que acompanha
  toda publicação (``id_pedido``, ``cenario``, ``destino``, ``titulo_destino``,
  ``conteudo``, ``app_time``, ``sequencia``), conforme a seção *Data Models*
  (Envelope de mensagem publicada) do design.md.
- A montagem dos ``MessageAttributes`` da publicação SNS (``id_pedido`` e
  ``cenario``), no formato ``{"DataType": "String", "StringValue": ...}``.
- :func:`extrair_id_pedido`: a extração do ID_Pedido a partir do envelope SNS
  recebido na fila de destino (campo ``Message`` e ``MessageAttributes``),
  usada pelo Verificador_Entrega para correlacionar as mensagens lidas.

O ID_Pedido é a chave de correlação da confirmação de entrega: uma mensagem só
é derivada como Entrega_Confirmada após ser lida na fila de destino e
correlacionada pelo ID_Pedido (Req. 6.1, 6.3, 10.1). Nunca se afirma entrega
apenas pela aceitação da publicação pelo SNS.

Formato recebido na fila (SNS envelope, sem raw message delivery): o SNS
encapsula o payload no campo ``Message`` (uma string JSON) e replica alguns
atributos em ``MessageAttributes`` (formato SQS, com chaves ``Type``/``Value``).
A extração tenta primeiro os ``MessageAttributes`` (mais barato, sem precisar
desserializar o corpo) e, se ausente, recorre ao JSON do campo ``Message``.

Referências de requisitos: 6.1, 6.3, 10.1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.dominio.tipos_sns import Cenario

# ---------------------------------------------------------------------------
# Nomes dos campos do payload de aplicação e dos atributos SNS
# ---------------------------------------------------------------------------
# Mantidos como constantes para evitar divergência entre a montagem (publicação)
# e a extração (leitura na fila de destino).
CAMPO_ID_PEDIDO: str = "id_pedido"
CAMPO_CENARIO: str = "cenario"
CAMPO_DESTINO: str = "destino"
CAMPO_TITULO_DESTINO: str = "titulo_destino"
CAMPO_CONTEUDO: str = "conteudo"
CAMPO_APP_TIME: str = "app_time"
CAMPO_SEQUENCIA: str = "sequencia"

# Chaves do envelope padrão do SNS recebido na fila SQS (sem raw delivery).
CHAVE_MESSAGE: str = "Message"
CHAVE_MESSAGE_ATTRIBUTES: str = "MessageAttributes"

# Nos MessageAttributes da *publicação* (SNS Publish) o valor fica em
# "StringValue"; no envelope *recebido* na fila (SQS) o valor fica em "Value".
# A extração aceita ambos para ser robusta aos dois formatos.
CHAVE_STRING_VALUE: str = "StringValue"
CHAVE_VALUE: str = "Value"


@dataclass(frozen=True)
class PayloadAplicacao:
    """Payload de aplicação carregado em toda publicação (Envelope de mensagem).

    Corresponde ao JSON da seção *Data Models* do design.md. O ``id_pedido`` é a
    chave de correlação usada na confirmação de entrega (Req. 6.1, 10.1).

    Campos:
        id_pedido: Identificador do pedido (1–80 caracteres), chave de correlação.
        cenario: Cenário do teste (:class:`Cenario`), STANDARD ou FIFO.
        destino: Destino do fan-out (``destino_1``, ``destino_2`` ou ``destino_3``).
        titulo_destino: Título descritivo do destino, exibido no Dashboard (pt-BR).
        conteudo: Conteúdo da notificação (texto visual).
        app_time: Horário real da aplicação em ISO-8601 UTC com milissegundos.
        sequencia: Ordem da mensagem dentro do teste (inteiro ≥ 1).
    """

    id_pedido: str
    cenario: Cenario
    destino: str
    titulo_destino: str
    conteudo: str
    app_time: str
    sequencia: int

    def para_dict(self) -> dict[str, Any]:
        """Serializa o payload no formato JSON do envelope de mensagem.

        O ``cenario`` é gravado como string (o ``.value`` do enum, ``"standard"``
        ou ``"fifo"``), reproduzindo o exemplo do design.md. Esse dicionário é o
        que vai, serializado como string, no campo ``Message`` da publicação SNS.
        """
        return {
            CAMPO_ID_PEDIDO: self.id_pedido,
            CAMPO_CENARIO: self.cenario.value,
            CAMPO_DESTINO: self.destino,
            CAMPO_TITULO_DESTINO: self.titulo_destino,
            CAMPO_CONTEUDO: self.conteudo,
            CAMPO_APP_TIME: self.app_time,
            CAMPO_SEQUENCIA: self.sequencia,
        }

    def para_json(self) -> str:
        """Serializa o payload como string JSON (campo ``Message`` do Publish).

        Usa ``ensure_ascii=False`` para preservar acentuação pt-BR do conteúdo.
        """
        return json.dumps(self.para_dict(), ensure_ascii=False)

    def message_attributes(self) -> dict[str, dict[str, str]]:
        """Monta os ``MessageAttributes`` da publicação SNS (``id_pedido``, ``cenario``).

        Formato de atributos do SNS ``Publish`` (boto3):
        ``{"id_pedido": {"DataType": "String", "StringValue": "..."}, ...}``.
        Esses atributos permitem a correlação pelo ID_Pedido mesmo quando a
        leitura inspeciona apenas os atributos (Req. 6.3, 10.1).
        """
        return {
            CAMPO_ID_PEDIDO: {"DataType": "String", "StringValue": self.id_pedido},
            CAMPO_CENARIO: {"DataType": "String", "StringValue": self.cenario.value},
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "PayloadAplicacao":
        """Reconstrói um :class:`PayloadAplicacao` a partir de um dicionário.

        Args:
            dados: Dicionário com as chaves do envelope de mensagem.

        Returns:
            A instância equivalente.

        Raises:
            KeyError: se faltar um campo obrigatório.
            ValueError: se ``cenario`` não for um valor válido de :class:`Cenario`.
        """
        return cls(
            id_pedido=str(dados[CAMPO_ID_PEDIDO]),
            cenario=Cenario(dados[CAMPO_CENARIO]),
            destino=str(dados[CAMPO_DESTINO]),
            titulo_destino=str(dados[CAMPO_TITULO_DESTINO]),
            conteudo=str(dados[CAMPO_CONTEUDO]),
            app_time=str(dados[CAMPO_APP_TIME]),
            sequencia=int(dados[CAMPO_SEQUENCIA]),
        )


def _valor_de_atributo(atributo: Any) -> str | None:
    """Extrai o valor textual de um atributo de mensagem.

    Aceita tanto o formato da publicação SNS (``StringValue``) quanto o formato
    recebido na fila SQS (``Value``). Retorna ``None`` quando o atributo não é um
    dicionário ou não contém um valor textual não vazio.
    """
    if not isinstance(atributo, dict):
        return None

    # Preferir "Value" (formato recebido na fila) e, se ausente, "StringValue".
    for chave in (CHAVE_VALUE, CHAVE_STRING_VALUE):
        valor = atributo.get(chave)
        if isinstance(valor, str) and valor != "":
            return valor

    return None


def _id_pedido_dos_atributos(mensagem: dict[str, Any]) -> str | None:
    """Tenta extrair o ID_Pedido dos ``MessageAttributes`` do envelope."""
    atributos = mensagem.get(CHAVE_MESSAGE_ATTRIBUTES)
    if not isinstance(atributos, dict):
        return None

    atributo_id = atributos.get(CAMPO_ID_PEDIDO)
    return _valor_de_atributo(atributo_id)


def _id_pedido_de_payload(payload: Any) -> str | None:
    """Extrai o ID_Pedido de um dicionário de payload de aplicação já desserializado."""
    if not isinstance(payload, dict):
        return None
    valor = payload.get(CAMPO_ID_PEDIDO)
    if isinstance(valor, str) and valor != "":
        return valor
    return None


def _id_pedido_do_corpo(mensagem: dict[str, Any]) -> str | None:
    """Tenta extrair o ID_Pedido do campo ``Message`` (JSON) do envelope.

    Trata dois formatos:

    1. **Payload direto:** ``Message`` é o JSON do payload de aplicação, com
       ``id_pedido`` no nível raiz.
    2. **Envelope SNS (sem raw delivery):** ``Message`` é o envelope do SNS
       (``{"Type":"Notification","Message":"{...payload...}", ...}``), onde o
       payload de aplicação está **aninhado** como string JSON no campo
       ``Message`` interno. É o formato real recebido na fila de destino quando a
       assinatura não usa *raw message delivery* (o caso do laboratório).
    """
    corpo = mensagem.get(CHAVE_MESSAGE)
    if not isinstance(corpo, str) or corpo == "":
        return None

    try:
        desserializado = json.loads(corpo)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(desserializado, dict):
        return None

    # Caso 1: o próprio corpo já é o payload de aplicação.
    direto = _id_pedido_de_payload(desserializado)
    if direto is not None:
        return direto

    # Caso 2: envelope SNS — o payload está aninhado na string ``Message``.
    interno = desserializado.get(CHAVE_MESSAGE)
    if isinstance(interno, str) and interno != "":
        try:
            payload_interno = json.loads(interno)
        except (json.JSONDecodeError, ValueError):
            return None
        return _id_pedido_de_payload(payload_interno)

    return None


def extrair_id_pedido(mensagem: dict[str, Any]) -> str | None:
    """Extrai o ID_Pedido do envelope SNS recebido na fila de destino.

    O envelope padrão do SNS (sem raw message delivery) carrega o payload de
    aplicação no campo ``Message`` (string JSON) e replica atributos em
    ``MessageAttributes`` (formato SQS, chaves ``Type``/``Value``). Esta função
    busca o ID_Pedido primeiro nos ``MessageAttributes`` (sem precisar
    desserializar o corpo) e, se ausente, recorre ao JSON do campo ``Message``
    (Req. 6.3, 10.1).

    A extração é tolerante a envelopes malformados: retorna ``None`` quando o
    ID_Pedido não pode ser determinado, para que o Verificador_Entrega apenas
    ignore e preserve a mensagem não correlacionada, sem registrar erro.

    Args:
        mensagem: O envelope SNS recebido (dicionário já desserializado da fila).

    Returns:
        O ID_Pedido como string, ou ``None`` se não for possível extraí-lo.
    """
    if not isinstance(mensagem, dict):
        return None

    # 1) MessageAttributes (mais barato e disponível mesmo sem ler o corpo).
    id_pedido = _id_pedido_dos_atributos(mensagem)
    if id_pedido is not None:
        return id_pedido

    # 2) Corpo JSON do campo Message (payload de aplicação).
    return _id_pedido_do_corpo(mensagem)
