"""Registro de observações em memória do laboratório AWS SNS Delivery Lab (Tarefa 13.1).

O agregador de estatísticas (:func:`app.observabilidade.agregador_estatisticas_sns.
agregar_estatisticas_sns`) é uma **função pura** que recebe um iterável de
observações. O endpoint ``GET /api/estatisticas`` (Tarefa 12.2) consome essas
observações por meio de um **provedor** injetável (``provedor_observacoes``). Até a
Tarefa 13.1, o laboratório injetava um provedor vazio, de modo que todas as
estatísticas apareciam zeradas.

Este módulo fornece o elo que faltava: um **registro de observações** em memória,
*append-only* e thread-safe, no qual os endpoints de disparo (Tarefa 13.x)
acumulam cada Evento_Observado concreto:

- uma **publicação aceita** pelo SNS (``TipoObservacao.PUBLICACAO``), registrada
  com o MessageId retornado — Evento_Observado de Entrega_Publicada (Req. 4.3, 5.6);
- uma **Entrega_Confirmada** por leitura real correlacionada pelo ID_Pedido em uma
  fila de destino (``TipoObservacao.CONFIRMACAO``) — Req. 6.3;
- a **presença constatada em uma DLQ** (``TipoObservacao.DLQ``) — Req. 3.6.

O registro é a origem concreta das observações: o provedor passado à fábrica da
aplicação (:func:`app.api.rotas_sns.criar_app_sns`) é simplesmente
:meth:`RegistroObservacoesSns.observacoes`, de modo que o agregador puro continua
desacoplado da origem (um registro em memória agora, um repositório no futuro).

Decisões de design:

- **Append-only e thread-safe.** A API_Backend (FastAPI) atende requisições
  concorrentes; o acesso à lista interna é protegido por um ``threading.Lock``.
  As observações nunca são removidas nem mutadas — refletem ações concretas já
  ocorridas (Evento_Observado), coerentes com o log append-only do design.
- **Snapshot imutável na leitura.** :meth:`observacoes` devolve uma **tupla**
  (cópia rasa) do estado atual, para que a agregação itere sobre um retrato
  estável mesmo que novas observações cheguem em paralelo.
- **Sem I/O.** O registro apenas acumula objetos :class:`ObservacaoSns` em memória;
  qualquer persistência futura fica a cargo de outra camada.

Referências de requisitos: 3.4, 3.5, 3.6, 4.3, 5.6, 6.3.
"""

from __future__ import annotations

import threading
from typing import Optional

from app.dominio.tipos_sns import Cenario
from app.observabilidade.agregador_estatisticas_sns import (
    ObservacaoSns,
    TipoObservacao,
)


class RegistroObservacoesSns:
    """Acumula Evento_Observado em memória para alimentar o agregador de estatísticas.

    Instância única por aplicação (criada na fábrica e injetada em ``app.state``),
    compartilhada entre os endpoints de disparo (produtores) e o endpoint de
    estatísticas (consumidor, via provedor de observações).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._observacoes: list[ObservacaoSns] = []

    # ------------------------------------------------------------------
    # Registro (produtores: endpoints de disparo)
    # ------------------------------------------------------------------
    def registrar(self, observacao: ObservacaoSns) -> None:
        """Acrescenta uma observação ao registro (append-only)."""
        with self._lock:
            self._observacoes.append(observacao)

    def registrar_publicacao(
        self,
        cenario: Cenario,
        topico: str,
        *,
        id_pedido: Optional[str] = None,
    ) -> None:
        """Registra uma publicação aceita pelo SNS (Entrega_Publicada) — Req. 3.4, 4.3, 5.6.

        Args:
            cenario: cenário do disparo (STANDARD ou FIFO).
            topico: nome do tópico onde a publicação foi aceita.
            id_pedido: ID_Pedido correlacionado, para documentar a origem.
        """
        self.registrar(
            ObservacaoSns(
                cenario=cenario,
                tipo=TipoObservacao.PUBLICACAO,
                topico=topico,
                id_pedido=id_pedido,
            )
        )

    def registrar_confirmacao(
        self,
        cenario: Cenario,
        fila_destino: str,
        *,
        id_pedido: Optional[str] = None,
    ) -> None:
        """Registra uma Entrega_Confirmada por leitura real correlacionada — Req. 3.5, 6.3.

        Args:
            cenario: cenário do disparo (STANDARD ou FIFO).
            fila_destino: nome da fila de destino lida e correlacionada.
            id_pedido: ID_Pedido correlacionado na leitura.
        """
        self.registrar(
            ObservacaoSns(
                cenario=cenario,
                tipo=TipoObservacao.CONFIRMACAO,
                fila_destino=fila_destino,
                id_pedido=id_pedido,
            )
        )

    def registrar_dlq(
        self,
        cenario: Cenario,
        dlq: str,
        *,
        id_pedido: Optional[str] = None,
    ) -> None:
        """Registra a presença constatada de uma mensagem em uma DLQ — Req. 3.6.

        Args:
            cenario: cenário do disparo (STANDARD ou FIFO).
            dlq: nome da DLQ onde a mensagem foi constatada.
            id_pedido: ID_Pedido correlacionado, para documentar a origem.
        """
        self.registrar(
            ObservacaoSns(
                cenario=cenario,
                tipo=TipoObservacao.DLQ,
                dlq=dlq,
                id_pedido=id_pedido,
            )
        )

    # ------------------------------------------------------------------
    # Leitura (consumidor: provedor de observações do agregador)
    # ------------------------------------------------------------------
    def observacoes(self) -> tuple[ObservacaoSns, ...]:
        """Devolve um snapshot imutável das observações acumuladas.

        Retorna uma tupla (cópia rasa) para que o agregador itere sobre um retrato
        estável, mesmo que novas observações cheguem concorrentemente.
        """
        with self._lock:
            return tuple(self._observacoes)

    def __len__(self) -> int:
        with self._lock:
            return len(self._observacoes)
