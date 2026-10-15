"""Tipos e enums de domínio do laboratório AWS SNS Delivery Lab.

Define os contratos base de classificação do laboratório de Amazon SNS:

- Cenario: o cenário do teste, STANDARD ou FIFO (Req. 1.1, 1.2).
- EstadoEntrega: o estado derivado de uma mensagem — ENTREGA_PUBLICADA,
  ENTREGA_CONFIRMADA ou NAO_CONFIRMADO (Req. 6.1, 6.2, 6.6, 13.6).
- OrigemEvento: a origem de cada evento, OBSERVADO (ação concreta executada ou
  constatada) ou INFERIDO (deduzido indiretamente) (Req. 4.3, 6.3, 8.6).

Os valores de EstadoEntrega e OrigemEvento usam os rótulos exibidos no Dashboard
em pt-BR. O estado da entrega NUNCA é persistido como campo mutável — é derivado
das observações, exigindo leitura real na fila de destino para
ENTREGA_CONFIRMADA e nunca afirmando entrega apenas pela aceitação da publicação
pelo SNS (Req. 6.1, 6.2).
"""

from __future__ import annotations

from enum import Enum


class Cenario(str, Enum):
    """Cenário de um teste do laboratório (Req. 1.1, 1.2).

    - STANDARD: usa o Topico_Standard e as três Fila_Destino_Standard.
    - FIFO: usa o Topico_FIFO e as três Fila_Destino_FIFO.
    """

    STANDARD = "standard"
    FIFO = "fifo"


class EstadoEntrega(str, Enum):
    """Estado derivado de uma mensagem (indicador textual do Dashboard).

    O conjunto é fechado e corresponde ao modelo de estados do design.md:

    - ENTREGA_PUBLICADA: o SNS aceitou a publicação e retornou um MessageId,
      sem comprovação de recebimento na fila de destino (Evento_Observado).
    - ENTREGA_CONFIRMADA: a mensagem foi lida na fila de destino e correlacionada
      pelo ID_Pedido (Evento_Observado). Nunca derivada apenas da aceitação da
      publicação (Req. 6.1, 6.2).
    - NAO_CONFIRMADO: o Timeout_Verificacao foi atingido sem leitura
      correlacionada; nunca afirma "entregue" (Req. 6.6, 7.9, 8.7).
    """

    ENTREGA_PUBLICADA = "Entrega_Publicada"
    ENTREGA_CONFIRMADA = "Entrega_Confirmada"
    NAO_CONFIRMADO = "Não confirmado"


class OrigemEvento(str, Enum):
    """Origem de um evento registrado pela aplicação (Req. 4.3, 6.3, 8.6).

    - OBSERVADO: registrado a partir de uma ação concreta que a aplicação
      executou ou constatou (ex.: publicação via boto3 com MessageId, leitura
      confirmada de mensagem na fila de destino ou DLQ).
    - INFERIDO: deduzido a partir de condições indiretas, sem confirmação direta
      do serviço AWS.
    """

    OBSERVADO = "Evento_Observado"
    INFERIDO = "Evento_Inferido"


# Conjuntos permitidos (contratos base úteis para validações e testes de
# propriedade que verificam que a derivação retorna exatamente um valor válido).
CENARIOS_PERMITIDOS: frozenset[Cenario] = frozenset(Cenario)
ESTADOS_ENTREGA_PERMITIDOS: frozenset[EstadoEntrega] = frozenset(EstadoEntrega)
ORIGENS_EVENTO_PERMITIDAS: frozenset[OrigemEvento] = frozenset(OrigemEvento)
