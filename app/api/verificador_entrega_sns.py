"""Verificador_Entrega do AWS SNS Delivery Lab (Tarefa 7.3).

O **Verificador_Entrega** confirma entregas lendo as filas de destino (e as DLQs)
de forma **não destrutiva**, correlacionando cada mensagem lida pelo **ID_Pedido**.
Ele orquestra a :class:`~app.acesso.sqs_leitura_gateway_sns.SqsLeituraGateway`
(leitura somente, nunca ``DeleteMessage``) e reusa a extração de ID_Pedido do
envelope SNS (:func:`app.dominio.envelope_mensagem.extrair_id_pedido`) e o
derivador de estado puro (:func:`app.dominio.derivador_estado_entrega.derivar_estado_entrega`).

Regras implementadas (design.md, seção "Verificador_Entrega e SqsLeituraGateway";
Req. 6.1, 6.3, 6.5, 6.6, 10.1, 10.2, 10.6, 8.5, 8.7):

- **Correlação por ID_Pedido.** Cada mensagem lida tem o ID_Pedido extraído do
  envelope SNS. Apenas as mensagens cujo ID_Pedido é exatamente igual ao do teste
  em execução confirmam a entrega; as demais (de outros testes/usuários) são
  **ignoradas e preservadas** — a leitura é não destrutiva (Req. 6.1, 10.1, 10.2).
- **Repetição até o Timeout_Verificacao, sem erro em retorno vazio.** O verificador
  lê repetidamente a fila até correlacionar o ID_Pedido ou atingir o
  Timeout_Verificacao. Um recebimento vazio **não** é erro: apenas provoca nova
  tentativa até o limite (Req. 10.6).
- **"Não confirmado" ao atingir o timeout.** Esgotado o Timeout_Verificacao sem
  leitura correlacionada, o estado retornado é ``NAO_CONFIRMADO`` ("Não
  confirmado"), nunca "entregue" (Req. 6.6, 7.9, 8.7).
- **Evento_Observado de Entrega_Confirmada.** Ao correlacionar o ID_Pedido, o
  resultado carrega a fila, o ID_Pedido e o MessageId da mensagem lida, para que
  o chamador registre o Evento_Observado de Entrega_Confirmada (Req. 6.3).
- **Dois timeouts distintos.** ``verificar_entrega`` usa o
  Timeout_Verificacao_Entrega (filas de destino, mais rápido) e ``verificar_dlq``
  usa o Timeout_Verificacao_DLQ (DLQs, mais lento) (Req. 2.5, 6.5, 8.5).

**Determinismo em testes.** O relógio (``relogio``) e a espera entre tentativas
(``dormir``) são injetáveis. Em produção usam ``time.monotonic`` e ``time.sleep``;
em testes injete um relógio simulado e um ``dormir`` que não durma de fato, de
modo que o laço de verificação seja determinístico e não gaste tempo real.

Referências de requisitos: 6.1, 6.3, 6.5, 6.6, 10.1, 10.2, 10.6, 8.5, 8.7.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.acesso.sqs_leitura_gateway_sns import (
    MensagemVisualizada,
    SqsLeituraGateway,
    VISIBILITY_TIMEOUT_CURTO_PADRAO,
)
from app.dominio import constantes_sns as c
from app.dominio.derivador_estado_entrega import (
    LeituraFilaDestino,
    ObservacoesEntrega,
    derivar_estado_entrega,
)
from app.dominio.envelope_mensagem import extrair_id_pedido
from app.dominio.tipos_sns import EstadoEntrega

# Pausa (em segundos) entre tentativas de leitura quando o recebimento vem vazio e
# ainda há orçamento de tempo. Mantida curta: o Long Polling do ReceiveMessage já
# aguarda no servidor; esta pausa só evita um laço apertado quando o Long Polling
# retorna de imediato (p.ex. com um cliente simulado em testes).
PAUSA_ENTRE_TENTATIVAS_PADRAO: float = 0.0


@dataclass(frozen=True)
class ResultadoVerificacao:
    """Resultado da verificação de entrega de um ID_Pedido numa fila.

    Carrega o estado derivado e, quando confirmado, os dados do Evento_Observado
    de Entrega_Confirmada (fila, ID_Pedido e MessageId da mensagem lida), para que
    o chamador os registre (Req. 6.3).

    Atributos:
        estado: estado derivado — ``ENTREGA_CONFIRMADA`` quando o ID_Pedido foi
            correlacionado na fila, ou ``NAO_CONFIRMADO`` ao atingir o timeout sem
            correlação.
        confirmada: ``True`` se e somente se ``estado`` é ``ENTREGA_CONFIRMADA``.
        queue_url: URL da fila/DLQ verificada.
        id_pedido: ID_Pedido do teste em execução (chave de correlação).
        message_id: MessageId da mensagem correlacionada, quando confirmada;
            ``None`` quando "Não confirmado".
        tentativas: número de chamadas de leitura realizadas (observabilidade).
    """

    estado: EstadoEntrega
    confirmada: bool
    queue_url: str
    id_pedido: str
    message_id: Optional[str] = None
    tentativas: int = 0

    def observacao_entrega_confirmada(self) -> Optional[LeituraFilaDestino]:
        """Devolve a leitura correlacionada (Evento_Observado) quando confirmada.

        Útil para o chamador alimentar o agregador de estatísticas / histórico com
        o Evento_Observado de Entrega_Confirmada. Retorna ``None`` quando não houve
        confirmação.
        """
        if not self.confirmada:
            return None
        return LeituraFilaDestino(
            id_pedido=self.id_pedido,
            fila_destino=self.queue_url,
            message_id=self.message_id,
        )


class VerificadorEntrega:
    """Orquestra a confirmação de entrega por leitura não destrutiva (Req. 6.x, 10.x).

    Usa a :class:`SqsLeituraGateway` para ler repetidamente a fila até correlacionar
    o ID_Pedido ou esgotar o Timeout_Verificacao. Não exclui mensagens e preserva as
    não correlacionadas.
    """

    def __init__(
        self,
        gateway: SqsLeituraGateway,
        *,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        wait_time_seconds: int = c.LONG_POLLING_MAX,
        visibility_timeout_s: int = VISIBILITY_TIMEOUT_CURTO_PADRAO,
        pausa_entre_tentativas_s: float = PAUSA_ENTRE_TENTATIVAS_PADRAO,
    ) -> None:
        """Inicializa o verificador.

        Args:
            gateway: :class:`SqsLeituraGateway` de leitura somente usado para ler
                as filas de destino e DLQs.
            relogio: função que devolve um instante monotônico em segundos. Em
                testes, injete um relógio simulado para controle determinístico do
                tempo decorrido (sem depender do relógio real).
            dormir: função chamada para pausar entre tentativas quando o
                recebimento vem vazio. Em testes, injete um ``dormir`` que não
                durma de fato (p.ex. que apenas avance o relógio simulado).
            wait_time_seconds: WaitTimeSeconds do Long Polling (1–20 s), repassado
                ao gateway em cada leitura (Req. 10.5, 14.4).
            visibility_timeout_s: Visibility_Timeout curto da leitura não
                destrutiva, repassado ao gateway (Req. 6.4, 10.4).
            pausa_entre_tentativas_s: pausa, em segundos, entre tentativas quando o
                recebimento vem vazio e ainda há orçamento de tempo.
        """
        self._gateway = gateway
        self._relogio = relogio
        self._dormir = dormir
        self._wait_time_seconds = wait_time_seconds
        self._visibility_timeout_s = visibility_timeout_s
        self._pausa_entre_tentativas_s = pausa_entre_tentativas_s

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def verificar_entrega(
        self,
        queue_url: str,
        id_pedido: str,
        timeout_s: int = c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO,
    ) -> ResultadoVerificacao:
        """Verifica a entrega de ``id_pedido`` numa fila de destino.

        Lê a fila de destino de forma não destrutiva, repetidamente, até
        correlacionar o ID_Pedido ou atingir o Timeout_Verificacao_Entrega. Aplica,
        por padrão, o Timeout_Verificacao_Entrega (filas de destino, mais rápido —
        Req. 2.5, 6.5).

        Args:
            queue_url: URL da fila de destino a inspecionar.
            id_pedido: ID_Pedido do teste em execução (chave de correlação).
            timeout_s: Timeout_Verificacao_Entrega em segundos (padrão 30 s).

        Returns:
            :class:`ResultadoVerificacao` com ``ENTREGA_CONFIRMADA`` (e o MessageId
            da mensagem correlacionada) ou ``NAO_CONFIRMADO`` ao esgotar o timeout.
        """
        return self._verificar(queue_url, id_pedido, timeout_s)

    def verificar_dlq(
        self,
        dlq_url: str,
        id_pedido: str,
        timeout_s: int = c.TIMEOUT_VERIFICACAO_DLQ_PADRAO,
    ) -> ResultadoVerificacao:
        """Verifica a presença de ``id_pedido`` numa DLQ do SNS.

        Idêntico a :meth:`verificar_entrega`, porém aplicando por padrão o
        Timeout_Verificacao_DLQ (DLQs, mais lento, pois o encaminhamento depende da
        política de retry do SNS — Req. 2.5, 6.5, 8.5).

        Args:
            dlq_url: URL da DLQ compatível a inspecionar.
            id_pedido: ID_Pedido do teste em execução (chave de correlação).
            timeout_s: Timeout_Verificacao_DLQ em segundos (padrão 120 s).

        Returns:
            :class:`ResultadoVerificacao` com ``ENTREGA_CONFIRMADA`` (presença na
            DLQ correlacionada) ou ``NAO_CONFIRMADO`` ao esgotar o timeout.
        """
        return self._verificar(dlq_url, id_pedido, timeout_s)

    # ------------------------------------------------------------------
    # Laço de verificação (comum a filas de destino e DLQs)
    # ------------------------------------------------------------------
    def _verificar(
        self,
        queue_url: str,
        id_pedido: str,
        timeout_s: int,
    ) -> ResultadoVerificacao:
        """Lê repetidamente a fila até correlacionar o ID_Pedido ou esgotar o timeout.

        O laço respeita o orçamento de tempo medido pelo ``relogio`` injetável:
        enquanto o tempo decorrido não exceder ``timeout_s`` e não houver
        correlação, realiza novas leituras. Um recebimento vazio não é erro — apenas
        provoca nova tentativa (Req. 10.6). Qualquer erro da AWS propaga intacto
        (o gateway não encapsula exceções).
        """
        inicio = self._relogio()
        tentativas = 0

        while True:
            tentativas += 1
            mensagens = self._gateway.receber_para_visualizacao(
                queue_url,
                wait_time_seconds=self._wait_time_seconds,
                visibility_timeout_s=self._visibility_timeout_s,
            )

            correlacionada = self._primeira_correlacionada(mensagens, id_pedido)
            if correlacionada is not None:
                return self._resultado_confirmado(
                    queue_url, id_pedido, correlacionada, tentativas
                )

            # Sem correlação nesta leitura: decidir se ainda há orçamento de tempo
            # para uma nova tentativa. O timeout é verificado APÓS ao menos uma
            # leitura, garantindo que uma confirmação imediata nunca seja perdida.
            if self._tempo_esgotado(inicio, timeout_s):
                return self._resultado_nao_confirmado(queue_url, id_pedido, tentativas)

            if self._pausa_entre_tentativas_s > 0:
                self._dormir(self._pausa_entre_tentativas_s)

    @staticmethod
    def _primeira_correlacionada(
        mensagens: list[MensagemVisualizada],
        id_pedido: str,
    ) -> Optional[MensagemVisualizada]:
        """Retorna a primeira mensagem cujo ID_Pedido correlaciona com ``id_pedido``.

        Correlaciona cada mensagem lida pelo ID_Pedido extraído do envelope SNS
        (atributos ou corpo). Mensagens sem ID_Pedido ou de outros pedidos são
        ignoradas e preservadas (leitura não destrutiva — Req. 6.1, 10.1, 10.2).
        """
        if not id_pedido:
            return None
        for mensagem in mensagens:
            envelope = {
                "Message": mensagem.body,
                "MessageAttributes": dict(mensagem.message_attributes),
            }
            if extrair_id_pedido(envelope) == id_pedido:
                return mensagem
        return None

    def _tempo_esgotado(self, inicio: float, timeout_s: int) -> bool:
        """Indica se o Timeout_Verificacao foi atingido desde ``inicio``."""
        return (self._relogio() - inicio) >= timeout_s

    @staticmethod
    def _resultado_confirmado(
        queue_url: str,
        id_pedido: str,
        mensagem: MensagemVisualizada,
        tentativas: int,
    ) -> ResultadoVerificacao:
        """Monta o resultado de Entrega_Confirmada a partir da mensagem correlacionada."""
        estado = derivar_estado_entrega(
            ObservacoesEntrega(
                id_pedido=id_pedido,
                publicacao_aceita=True,
                leituras=(
                    LeituraFilaDestino(
                        id_pedido=id_pedido,
                        fila_destino=queue_url,
                        message_id=mensagem.message_id or None,
                    ),
                ),
            )
        )
        return ResultadoVerificacao(
            estado=estado,
            confirmada=estado is EstadoEntrega.ENTREGA_CONFIRMADA,
            queue_url=queue_url,
            id_pedido=id_pedido,
            message_id=mensagem.message_id or None,
            tentativas=tentativas,
        )

    @staticmethod
    def _resultado_nao_confirmado(
        queue_url: str,
        id_pedido: str,
        tentativas: int,
    ) -> ResultadoVerificacao:
        """Monta o resultado "Não confirmado" ao esgotar o Timeout_Verificacao."""
        estado = derivar_estado_entrega(
            ObservacoesEntrega(
                id_pedido=id_pedido,
                publicacao_aceita=True,
                leituras=(),
                timeout_atingido=True,
            )
        )
        return ResultadoVerificacao(
            estado=estado,
            confirmada=False,
            queue_url=queue_url,
            id_pedido=id_pedido,
            message_id=None,
            tentativas=tentativas,
        )
