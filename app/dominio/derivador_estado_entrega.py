"""Derivador puro do estado de entrega de uma mensagem do AWS SNS Delivery Lab.

Este módulo implementa o **derivador de estado de entrega** descrito no
design.md (seção "Modelo de estados da entrega") e validado pelas Correctness
Properties 1 e 4. É uma **função pura**: não realiza E/S, não acessa a AWS, não
altera a entrada e sempre retorna exatamente um valor do conjunto fechado
:class:`EstadoEntrega`.

Modelo de estados (design.md e Req. 6.1, 6.2, 6.6, 4.3)
------------------------------------------------------

- ``ENTREGA_PUBLICADA``: o SNS aceitou a publicação e retornou um ``MessageId``,
  sem comprovação de recebimento na fila de destino (Evento_Observado).
- ``ENTREGA_CONFIRMADA``: a mensagem foi **efetivamente lida** na fila de destino
  e **correlacionada pelo ID_Pedido** (Evento_Observado).
- ``NAO_CONFIRMADO``: o Timeout_Verificacao foi atingido sem leitura
  correlacionada; o estado nunca afirma "entregue".

Regra fundamental (Req. 6.1, 6.2; Property 1)
---------------------------------------------
Nunca se deriva ``ENTREGA_CONFIRMADA`` apenas da aceitação da publicação pelo SNS
(``MessageId`` retornado). A confirmação exige uma **leitura real** na fila de
destino correlacionada pelo **ID_Pedido** do teste em execução. Leituras de
mensagens de outros ID_Pedido (testes/usuários de terceiros) são ignoradas e
jamais confirmam a entrega (Property 3, exercitada aqui de forma pura).

Timeout (Req. 6.6, 7.9, 8.7; Property 4)
----------------------------------------
Quando o Timeout_Verificacao é atingido sem leitura correlacionada, o estado
derivado é exatamente ``NAO_CONFIRMADO`` — nunca ``ENTREGA_CONFIRMADA``. Note que
uma leitura correlacionada **sempre** prevalece: se a mensagem foi lida na fila
de destino, o estado é ``ENTREGA_CONFIRMADA`` mesmo que o timeout também tenha
sido sinalizado (a confirmação é um fato observado e tem precedência).

O módulo é intencionalmente independente da camada de acesso (SNS/SQS): recebe um
conjunto de **observações** já coletadas (ver :class:`ObservacoesEntrega`), de
modo que possa ser testado sem AWS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.dominio.tipos_sns import EstadoEntrega


@dataclass(frozen=True)
class LeituraFilaDestino:
    """Observação de uma mensagem lida (não destrutivamente) numa fila de destino.

    Representa um Evento_Observado de leitura: o Verificador_Entrega leu uma
    mensagem presente numa fila de destino e extraiu o ``id_pedido`` do envelope
    SNS. A correlação com o teste em execução é feita comparando este
    ``id_pedido`` com o ID_Pedido observado em :class:`ObservacoesEntrega`.

    Atributos:
        id_pedido: ID_Pedido extraído do envelope da mensagem lida. Pode divergir
            do teste em execução quando a mensagem pertence a terceiros.
        fila_destino: Nome da fila de destino onde a mensagem foi lida.
        message_id: MessageId do SNS presente no envelope lido, quando disponível.
    """

    id_pedido: Optional[str]
    fila_destino: Optional[str] = None
    message_id: Optional[str] = None


@dataclass(frozen=True)
class ObservacoesEntrega:
    """Conjunto de observações de uma mensagem usadas para derivar o estado.

    Agrega apenas **fatos observados** pela aplicação, sem embutir nenhum estado
    já calculado. O ``id_pedido`` é a chave de correlação do teste em execução.

    Atributos:
        id_pedido: ID_Pedido do teste em execução (chave de correlação). Quando
            ``None`` ou vazio, nenhuma leitura pode ser correlacionada e o estado
            jamais será ``ENTREGA_CONFIRMADA``.
        publicacao_aceita: ``True`` quando o SNS aceitou a publicação e retornou um
            MessageId (Entrega_Publicada). Por si só NUNCA confirma a entrega.
        leituras: Leituras não destrutivas observadas nas filas de destino. Uma
            leitura correlacionada pelo ID_Pedido confirma a entrega.
        timeout_atingido: ``True`` quando o Timeout_Verificacao foi atingido sem
            leitura correlacionada.
    """

    id_pedido: Optional[str]
    publicacao_aceita: bool = False
    leituras: Iterable[LeituraFilaDestino] = field(default_factory=tuple)
    timeout_atingido: bool = False


def _ha_leitura_correlacionada(
    id_pedido: Optional[str],
    leituras: Iterable[LeituraFilaDestino],
) -> bool:
    """Indica se há ao menos uma leitura correlacionada pelo ID_Pedido.

    A correlação exige um ``id_pedido`` do teste não vazio e uma leitura cujo
    ``id_pedido`` seja exatamente igual. Leituras sem id_pedido ou de outros
    pedidos (terceiros) nunca correlacionam (Req. 6.1, 10.1, 10.2; Property 3).
    """
    if not id_pedido:
        return False
    for leitura in leituras:
        if leitura.id_pedido is not None and leitura.id_pedido == id_pedido:
            return True
    return False


def derivar_estado_entrega(observacoes: ObservacoesEntrega) -> EstadoEntrega:
    """Deriva exatamente um :class:`EstadoEntrega` a partir das observações.

    Função pura: não realiza E/S, não altera a entrada e sempre retorna um valor
    pertencente ao conjunto fechado :class:`EstadoEntrega`.

    Ordem de avaliação (precedência):

    1. ``ENTREGA_CONFIRMADA`` — existe uma leitura na fila de destino
       correlacionada pelo ID_Pedido. Esta é a **única** forma de confirmar a
       entrega e tem precedência sobre o timeout, pois a confirmação é um fato
       observado (Req. 6.1, 6.2; Properties 1 e 4).
    2. ``NAO_CONFIRMADO`` — não há leitura correlacionada e o Timeout_Verificacao
       foi atingido; nunca afirma "entregue" (Req. 6.6, 7.9, 8.7; Property 4).
    3. ``ENTREGA_PUBLICADA`` — o SNS aceitou a publicação (MessageId retornado),
       mas ainda não houve leitura correlacionada nem timeout. A aceitação da
       publicação, por si só, nunca produz ``ENTREGA_CONFIRMADA`` (Req. 6.2;
       Property 1).

    Observação: na ausência de qualquer sinal (sem publicação aceita, sem leitura,
    sem timeout) o estado é ``ENTREGA_PUBLICADA`` como ponto de partida do modelo
    de estados; ``ENTREGA_CONFIRMADA`` jamais é retornado sem leitura real.

    Args:
        observacoes: As observações coletadas para a mensagem.

    Returns:
        Um único valor de :class:`EstadoEntrega`.
    """
    # 1) Confirmação exige leitura real correlacionada pelo ID_Pedido. A aceitação
    #    da publicação pelo SNS, isoladamente, nunca basta (Req. 6.1, 6.2).
    if _ha_leitura_correlacionada(observacoes.id_pedido, observacoes.leituras):
        return EstadoEntrega.ENTREGA_CONFIRMADA

    # 2) Sem leitura correlacionada: timeout produz "Não confirmado", nunca
    #    "entregue" (Req. 6.6, 7.9, 8.7).
    if observacoes.timeout_atingido:
        return EstadoEntrega.NAO_CONFIRMADO

    # 3) Publicação aceita (ou estado inicial): aguardando confirmação por leitura.
    return EstadoEntrega.ENTREGA_PUBLICADA
