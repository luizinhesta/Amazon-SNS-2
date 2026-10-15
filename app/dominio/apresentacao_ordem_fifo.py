"""Apresentação da ordem de recebimento FIFO (Tarefa 4.4).

Este módulo implementa, como lógica de domínio **pura** (sem efeitos colaterais e
sem dependência de boto3), a apresentação da ordem de recebimento das mensagens
lidas de uma fila de destino FIFO, agrupadas por ``MessageGroupId``.

Regra fundamental (ver design.md, Property 10, e Req. 11.1, 11.2):

- A fila FIFO entrega as mensagens de um mesmo ``MessageGroupId`` **em ordem**. A
  aplicação apenas **apresenta** a ordem observada na leitura, **sem reconstruir
  nem reordenar** as mensagens. Em outras palavras, dentro de cada
  ``MessageGroupId`` a ordem de recebimento exibida é exatamente a sequência em
  que as mensagens foram lidas (nenhum ``sorted`` é aplicado).

Para que a função seja pura e testável sem AWS, ela recebe a sequência de
mensagens **já lida na ordem exata** (um iterável de :class:`MensagemLidaFifo`)
e devolve o agrupamento por ``MessageGroupId`` preservando essa ordem. A ordem de
aparição dos próprios grupos também segue a ordem em que cada grupo surgiu pela
primeira vez na leitura (ordem de inserção), sem reordenar os grupos.

Referências de requisitos: 11.1, 11.2.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MensagemLidaFifo:
    """Uma mensagem lida de uma fila de destino FIFO, na ordem de leitura.

    Representa uma mensagem já lida (não destrutivamente) de uma fila FIFO. É a
    unidade de entrada da apresentação de ordem: a aplicação não altera estes
    valores, apenas os agrupa por ``message_group_id`` preservando a ordem.

    Campos:
        message_group_id: O ``MessageGroupId`` da mensagem (grupo de ordenação FIFO).
        conteudo: O conteúdo textual da mensagem (ex.: "Pedido criado").
        message_id: O ``MessageId`` retornado pelo SNS/SQS, quando disponível.
        id_pedido: O ID_Pedido correlacionado, quando disponível.
    """

    message_group_id: str
    conteudo: str
    message_id: str | None = None
    id_pedido: str | None = None


@dataclass(frozen=True)
class OrdemRecebimentoGrupo:
    """Ordem de recebimento apresentada para um único ``MessageGroupId``.

    Agrega, para um grupo, a sequência de conteúdos e de ``MessageId`` na mesma
    ordem exata em que as mensagens foram lidas da fila FIFO — sem reordenação.

    Campos:
        message_group_id: O ``MessageGroupId`` do grupo.
        ordem_recebimento: Lista de conteúdos na ordem de leitura (preservada).
        message_ids: Lista de ``MessageId`` na mesma ordem de ``ordem_recebimento``;
            cada posição pode ser ``None`` quando a mensagem não trouxe o id.
    """

    message_group_id: str
    ordem_recebimento: tuple[str, ...]
    message_ids: tuple[str | None, ...]


def agrupar_ordem_recebimento_fifo(
    mensagens_lidas: Iterable[MensagemLidaFifo],
) -> list[OrdemRecebimentoGrupo]:
    """Agrupa as mensagens lidas por ``MessageGroupId`` preservando a ordem.

    A função é **pura**: não realiza E/S, não modifica a entrada e **não reordena
    nem reconstrói** as mensagens. Dentro de cada ``MessageGroupId``, a ordem de
    recebimento apresentada é exatamente a ordem em que as mensagens aparecem no
    iterável de entrada (que corresponde à ordem de leitura da fila FIFO). Os
    grupos são apresentados na ordem em que surgiram pela primeira vez na leitura.

    Args:
        mensagens_lidas: Iterável de :class:`MensagemLidaFifo` **na ordem exata de
            leitura** da(s) fila(s) de destino FIFO.

    Returns:
        Uma lista de :class:`OrdemRecebimentoGrupo`, um por ``MessageGroupId``
        observado, na ordem de primeira aparição; cada grupo preserva a ordem de
        recebimento dos seus conteúdos e ``MessageId``.
    """
    # OrderedDict preserva a ordem de inserção das chaves, isto é, a ordem em que
    # cada MessageGroupId surgiu pela primeira vez na leitura. Nenhuma ordenação
    # é aplicada aqui — apenas acumulação na ordem recebida (Req. 11.1, 11.2).
    acumulador: "OrderedDict[str, _AcumuladorGrupo]" = OrderedDict()

    for mensagem in mensagens_lidas:
        grupo = acumulador.get(mensagem.message_group_id)
        if grupo is None:
            grupo = _AcumuladorGrupo()
            acumulador[mensagem.message_group_id] = grupo
        grupo.conteudos.append(mensagem.conteudo)
        grupo.message_ids.append(mensagem.message_id)

    return [
        OrdemRecebimentoGrupo(
            message_group_id=message_group_id,
            ordem_recebimento=tuple(grupo.conteudos),
            message_ids=tuple(grupo.message_ids),
        )
        for message_group_id, grupo in acumulador.items()
    ]


@dataclass
class _AcumuladorGrupo:
    """Acumulador interno mutável usado durante o agrupamento (ordem preservada)."""

    conteudos: list[str] = field(default_factory=list)
    message_ids: list[str | None] = field(default_factory=list)
