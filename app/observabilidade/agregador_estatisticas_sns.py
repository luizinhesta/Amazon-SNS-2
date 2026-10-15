"""Agregador de estatísticas por cenário do laboratório AWS SNS Delivery Lab.

Este módulo implementa o agregador de estatísticas descrito no design.md
(seção *Observabilidade / estatísticas* e endpoint ``GET /api/estatisticas``).
A partir de um conjunto de **observações** (ações concretas que a aplicação
executou ou constatou), ele deriva, separadamente para cada cenário
(``Standard`` e ``FIFO``), os três contadores exibidos na visão geral do
Dashboard (Req. 3.4, 3.5, 3.6, 3.7, 3.10):

- ``publicadas_por_topico``: total de mensagens publicadas em cada tópico;
- ``confirmadas_por_fila``: mensagens com ``Entrega_Confirmada`` em cada fila
  de destino, identificando cada fila individualmente;
- ``presentes_por_dlq``: mensagens presentes em cada DLQ, identificando cada
  DLQ individualmente.

Princípios de design:

- **Função pura.** :func:`agregar_estatisticas_sns` não realiza E/S e não altera
  a entrada; depende apenas das observações recebidas. Isso permite testes de
  propriedade e de unidade sem depender da AWS (Correctness Properties 8 e 9).
- **Fonte de verdade são as observações.** Cada contador é derivado de uma
  observação concreta (uma publicação aceita com ``MessageId``, uma leitura real
  correlacionada pelo ID_Pedido ou a presença constatada em uma DLQ). O estado
  nunca é inferido apenas da aceitação da publicação pelo SNS (Req. 6.1, 6.2).
- **Particionamento por cenário.** Cada observação pertence a exatamente um
  cenário (``standard`` ou ``fifo``). Uma observação de um cenário nunca é
  contabilizada no outro, de modo que a soma dos contadores dos dois cenários
  iguala o total daquele tipo (Correctness Property 9, Req. 3.7).
- **Invariantes numéricas.** Todos os contadores são inteiros maiores ou iguais
  a 0. A ausência de dados para uma estatística produz o valor 0, e as chaves de
  tópicos, filas e DLQs conhecidos sempre existem no resultado com 0 quando não
  houver observação correspondente (Correctness Property 8, Req. 3.4, 3.5, 3.6,
  3.10).
- **Horário da última atualização.** O agregador registra o horário da última
  atualização bem-sucedida como um ``datetime`` *timezone-aware* (contém data,
  hora com segundos e identificação do fuso), conforme o Req. 3.8.

Referências de requisitos: 3.4, 3.5, 3.6, 3.7, 3.8, 3.10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Iterable, Optional

from app.dominio.constantes_sns import (
    DLQ_POR_TOPICO,
    DLQ_SNS_FIFO,
    DLQ_SNS_STANDARD,
    FILAS_DESTINO_FIFO,
    FILAS_DESTINO_STANDARD,
    TOPICO_FIFO,
    TOPICO_STANDARD,
)
from app.dominio.tipos_sns import Cenario


class TipoObservacao(str, Enum):
    """Tipo de observação concreta contabilizada pelo agregador.

    Cada observação registra uma ação que a aplicação executou ou constatou:

    - ``PUBLICACAO``: o SNS aceitou a publicação em um tópico e retornou um
      ``MessageId`` (contribui para ``publicadas_por_topico``) — Req. 3.4.
    - ``CONFIRMACAO``: uma mensagem foi lida na fila de destino e correlacionada
      pelo ID_Pedido, caracterizando ``Entrega_Confirmada`` (contribui para
      ``confirmadas_por_fila``) — Req. 3.5.
    - ``DLQ``: uma mensagem foi constatada presente em uma DLQ (contribui para
      ``presentes_por_dlq``) — Req. 3.6.
    """

    PUBLICACAO = "publicacao"
    CONFIRMACAO = "confirmacao"
    DLQ = "dlq"


@dataclass(frozen=True)
class ObservacaoSns:
    """Uma observação concreta usada na agregação de estatísticas.

    A observação é a unidade de entrada da função pura
    :func:`agregar_estatisticas_sns`. Dependendo do ``tipo``, os campos de
    recurso relevantes são:

    - ``PUBLICACAO`` → ``topico`` (nome do tópico publicado);
    - ``CONFIRMACAO`` → ``fila_destino`` (fila de destino lida);
    - ``DLQ`` → ``dlq`` (nome da DLQ onde a mensagem foi constatada).

    Campos:
        cenario: cenário da observação (:class:`Cenario`), ``standard`` ou
            ``fifo``. Determina em qual partição o contador é incrementado.
        tipo: :class:`TipoObservacao` da ação observada.
        topico: nome do tópico (apenas em observações de ``PUBLICACAO``).
        fila_destino: nome da fila de destino (apenas em ``CONFIRMACAO``).
        dlq: nome da DLQ (apenas em observações de ``DLQ``).
        id_pedido: ID_Pedido correlacionado, quando disponível (opcional; não
            afeta a contagem, mas documenta a origem da observação).
    """

    cenario: Cenario
    tipo: TipoObservacao
    topico: Optional[str] = None
    fila_destino: Optional[str] = None
    dlq: Optional[str] = None
    id_pedido: Optional[str] = None


@dataclass
class EstatisticasCenario:
    """Contadores agregados de um único cenário (Standard ou FIFO).

    Todos os valores são inteiros maiores ou iguais a 0. As chaves conhecidas
    (o tópico do cenário, as três filas de destino e a DLQ do cenário) sempre
    aparecem nos dicionários; a ausência de dados mantém o valor 0 (Req. 3.4,
    3.5, 3.6, 3.10).

    Campos:
        publicadas_por_topico: total publicado por nome de tópico (Req. 3.4).
        confirmadas_por_fila: ``Entrega_Confirmada`` por fila de destino,
            identificando cada fila individualmente (Req. 3.5).
        presentes_por_dlq: mensagens presentes por DLQ, identificando cada DLQ
            individualmente (Req. 3.6).
    """

    publicadas_por_topico: dict[str, int] = field(default_factory=dict)
    confirmadas_por_fila: dict[str, int] = field(default_factory=dict)
    presentes_por_dlq: dict[str, int] = field(default_factory=dict)

    @property
    def total_publicadas(self) -> int:
        """Soma das publicações do cenário (todos os tópicos do cenário)."""
        return sum(self.publicadas_por_topico.values())

    @property
    def total_confirmadas(self) -> int:
        """Soma das Entrega_Confirmada do cenário (todas as filas de destino)."""
        return sum(self.confirmadas_por_fila.values())

    @property
    def total_dlq(self) -> int:
        """Soma das mensagens presentes nas DLQs do cenário."""
        return sum(self.presentes_por_dlq.values())


@dataclass
class EstatisticasSns:
    """Estatísticas separadas em dois conjuntos distintos por cenário (Req. 3.7).

    Mantém um :class:`EstatisticasCenario` para o cenário Standard e outro para o
    FIFO. Um conjunto vazio de observações produz dois cenários com todos os
    contadores em 0 (Req. 3.10) e um horário de última atualização bem-sucedida
    (Req. 3.8).

    Campos:
        standard: contadores do cenário Standard.
        fifo: contadores do cenário FIFO.
        ultima_atualizacao: horário da última atualização bem-sucedida, como um
            ``datetime`` *timezone-aware* (data, hora com segundos e fuso).
    """

    standard: EstatisticasCenario = field(default_factory=EstatisticasCenario)
    fifo: EstatisticasCenario = field(default_factory=EstatisticasCenario)
    ultima_atualizacao: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Mapeamento dos recursos conhecidos por cenário
# ---------------------------------------------------------------------------
# As chaves conhecidas são pré-populadas com 0 para que a ausência de dados
# produza explicitamente o valor 0 (Req. 3.10) e para que cada tópico, fila e
# DLQ seja identificado individualmente no resultado (Req. 3.4, 3.5, 3.6).
_TOPICO_POR_CENARIO: dict[Cenario, str] = {
    Cenario.STANDARD: TOPICO_STANDARD,
    Cenario.FIFO: TOPICO_FIFO,
}
_FILAS_POR_CENARIO: dict[Cenario, tuple[str, ...]] = {
    Cenario.STANDARD: FILAS_DESTINO_STANDARD,
    Cenario.FIFO: FILAS_DESTINO_FIFO,
}
_DLQ_POR_CENARIO: dict[Cenario, str] = {
    Cenario.STANDARD: DLQ_SNS_STANDARD,
    Cenario.FIFO: DLQ_SNS_FIFO,
}


def _normalizar_cenario(valor: object) -> Optional[Cenario]:
    """Normaliza o cenário de uma observação para :class:`Cenario`.

    Aceita um :class:`Cenario` ou a string correspondente (``"standard"`` ou
    ``"fifo"``). Retorna ``None`` quando o valor não corresponde a um cenário
    conhecido, caso em que a observação é ignorada (não contabilizada em nenhum
    cenário, preservando o particionamento do Req. 3.7).
    """
    if isinstance(valor, Cenario):
        return valor
    if isinstance(valor, str):
        try:
            return Cenario(valor)
        except ValueError:
            return None
    return None


def _normalizar_tipo(valor: object) -> Optional[TipoObservacao]:
    """Normaliza o tipo de uma observação para :class:`TipoObservacao`."""
    if isinstance(valor, TipoObservacao):
        return valor
    if isinstance(valor, str):
        try:
            return TipoObservacao(valor)
        except ValueError:
            return None
    return None


def _cenario_vazio(cenario: Cenario) -> EstatisticasCenario:
    """Cria um :class:`EstatisticasCenario` com as chaves conhecidas zeradas.

    Pré-popular as chaves garante que cada tópico, fila de destino e DLQ do
    cenário apareça no resultado com 0 quando não houver observação (Req. 3.4,
    3.5, 3.6, 3.10).
    """
    return EstatisticasCenario(
        publicadas_por_topico={_TOPICO_POR_CENARIO[cenario]: 0},
        confirmadas_por_fila={fila: 0 for fila in _FILAS_POR_CENARIO[cenario]},
        presentes_por_dlq={_DLQ_POR_CENARIO[cenario]: 0},
    )


def agregar_estatisticas_sns(
    observacoes: Iterable[object],
    *,
    agora: Optional[Callable[[], datetime]] = None,
) -> EstatisticasSns:
    """Agrega as estatísticas por cenário a partir das observações.

    Função pura: não realiza E/S e não altera a entrada. Produz um
    :class:`EstatisticasSns` com um :class:`EstatisticasCenario` por cenário, cada
    um com os três contadores (publicadas por tópico, Entrega_Confirmada por fila
    de destino e presentes em cada DLQ).

    Algoritmo:

    1. Pré-popula as chaves conhecidas de cada cenário com 0 (Req. 3.10).
    2. Para cada observação, normaliza o cenário e o tipo; observações sem
       cenário ou tipo reconhecido são ignoradas.
    3. Incrementa o contador correspondente **apenas na partição do cenário da
       observação**, sem contabilizar um cenário no outro (Req. 3.7):
       - ``PUBLICACAO`` incrementa ``publicadas_por_topico`` (tópico informado ou,
         na ausência, o tópico padrão do cenário);
       - ``CONFIRMACAO`` incrementa ``confirmadas_por_fila`` para a ``fila_destino``;
       - ``DLQ`` incrementa ``presentes_por_dlq`` para a ``dlq`` (ou a DLQ padrão
         do cenário).
    4. Registra o horário da última atualização bem-sucedida (Req. 3.8).

    Args:
        observacoes: iterável de observações. Cada item deve expor os atributos
            ``cenario`` e ``tipo`` e, conforme o tipo, ``topico``,
            ``fila_destino`` ou ``dlq`` (ver :class:`ObservacaoSns`). Objetos
            compatíveis por atributos (duck typing) também são aceitos, o que
            facilita os testes.
        agora: fábrica opcional do horário atual (injeção para testes
            determinísticos). Quando omitida, usa ``datetime.now`` em UTC.

    Returns:
        :class:`EstatisticasSns` com todos os contadores inteiros ≥ 0, dois
        cenários distintos e o horário da última atualização bem-sucedida como um
        ``datetime`` *timezone-aware*. Um iterável vazio retorna os dois cenários
        com todos os contadores em 0 (Req. 3.10).
    """
    resultado = EstatisticasSns(
        standard=_cenario_vazio(Cenario.STANDARD),
        fifo=_cenario_vazio(Cenario.FIFO),
    )
    por_cenario: dict[Cenario, EstatisticasCenario] = {
        Cenario.STANDARD: resultado.standard,
        Cenario.FIFO: resultado.fifo,
    }

    for observacao in observacoes:
        cenario = _normalizar_cenario(getattr(observacao, "cenario", None))
        if cenario is None:
            continue

        tipo = _normalizar_tipo(getattr(observacao, "tipo", None))
        if tipo is None:
            continue

        destino = por_cenario[cenario]

        if tipo is TipoObservacao.PUBLICACAO:
            topico = getattr(observacao, "topico", None) or _TOPICO_POR_CENARIO[cenario]
            destino.publicadas_por_topico[topico] = (
                destino.publicadas_por_topico.get(topico, 0) + 1
            )
        elif tipo is TipoObservacao.CONFIRMACAO:
            fila = getattr(observacao, "fila_destino", None)
            if fila:
                destino.confirmadas_por_fila[fila] = (
                    destino.confirmadas_por_fila.get(fila, 0) + 1
                )
        elif tipo is TipoObservacao.DLQ:
            dlq = getattr(observacao, "dlq", None) or _DLQ_POR_CENARIO[cenario]
            destino.presentes_por_dlq[dlq] = (
                destino.presentes_por_dlq.get(dlq, 0) + 1
            )

    relogio = agora if agora is not None else (lambda: datetime.now(timezone.utc))
    marca = relogio()
    # Garante um horário timezone-aware (data, hora com segundos e fuso) — Req. 3.8.
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=timezone.utc)
    resultado.ultima_atualizacao = marca

    return resultado


# Reexportado por conveniência: a DLQ compatível com cada tópico já é conhecida
# nas constantes do laboratório e pode ser útil a quem monta observações de DLQ.
__all__ = [
    "TipoObservacao",
    "ObservacaoSns",
    "EstatisticasCenario",
    "EstatisticasSns",
    "agregar_estatisticas_sns",
    "DLQ_POR_TOPICO",
]
