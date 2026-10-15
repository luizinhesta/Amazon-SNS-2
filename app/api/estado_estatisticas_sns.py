"""Estado e provedor de estatísticas da visão geral do laboratório SNS (Tarefa 12.2).

Este módulo sustenta o endpoint ``GET /api/estatisticas`` com duas
responsabilidades que o ``design.md`` exige e que o agregador puro
(:func:`app.observabilidade.agregador_estatisticas_sns.agregar_estatisticas_sns`)
não cobre sozinho:

- **Fonte das observações.** O agregador é uma função pura que recebe um iterável
  de observações. Em produção, essas observações virão do registro de eventos que
  os endpoints de disparo (Tarefa 13.x) alimentarão a cada publicação aceita,
  Entrega_Confirmada e presença constatada em DLQ. Até lá, o laboratório injeta um
  **provedor de observações** — qualquer callable que devolve o iterável atual —,
  mantendo este módulo desacoplado da origem concreta e fácil de testar.

- **Timeout de 3s preservando os últimos dados válidos.** O Req. 14.1/14.3 pede
  que ``/api/estatisticas`` responda em até 3s (p95 sob 10 requisições
  simultâneas) e que, ao exceder, retorne uma **indicação de timeout** enquanto o
  Dashboard **preserva os últimos dados válidos** (Req. 3.9). Para isso, a
  agregação roda em um worker com limite de tempo: se concluir dentro do prazo, o
  resultado vira o novo "último dado válido" e é devolvido; se estourar, devolve-se
  o último snapshot bem-sucedido com a marcação ``timeout=True``, **sem** avançar o
  horário da última atualização bem-sucedida (Req. 3.9).

Decisões de design:

- **Thread-safe.** O cache do último resultado válido é protegido por um
  ``threading.Lock`` porque a API_Backend atende requisições concorrentes.
- **Sem I/O no agregador.** O worker apenas coleta as observações do provedor e
  chama o agregador puro; qualquer I/O (ex.: futura leitura de um repositório) fica
  no provedor injetado, que o chamador controla.
- **Timeout configurável.** O limite padrão é de 3s (Req. 14.1), ajustável para
  facilitar os testes determinísticos.

Referências de requisitos: 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 14.1, 14.3.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from app.observabilidade.agregador_estatisticas_sns import (
    EstatisticasSns,
    agregar_estatisticas_sns,
)

# Timeout padrão de resposta de ``/api/estatisticas`` em segundos (Req. 14.1).
TIMEOUT_ESTATISTICAS_PADRAO_SEGUNDOS: float = 3.0

# Provedor de observações: callable sem argumentos que devolve o iterável atual de
# observações a agregar. Injetável para desacoplar o estado da origem concreta.
ProvedorObservacoes = Callable[[], Iterable[object]]


@dataclass(frozen=True)
class ResultadoEstatisticasSns:
    """Resultado de uma solicitação de estatísticas, com indicação de timeout.

    Attributes:
        estatisticas: o snapshot de :class:`EstatisticasSns` devolvido — o recém
            agregado quando a coleta terminou a tempo, ou o último snapshot válido
            preservado quando houve timeout (Req. 3.9, 14.3). É ``None`` apenas no
            caso extremo de timeout logo na primeira coleta, quando ainda não há
            nenhum snapshot válido em cache.
        timeout: ``True`` se a agregação excedeu o limite de tempo e, portanto, os
            dados devolvidos são os últimos válidos preservados (Req. 14.3).
        mensagem: mensagem em pt-BR descrevendo o desfecho; vazia em sucesso e, em
            timeout, informando que os dados podem estar desatualizados (Req. 3.9).
    """

    estatisticas: Optional[EstatisticasSns]
    timeout: bool
    mensagem: str


# Mensagem exibida quando a coleta excede o timeout e preservamos os últimos dados
# válidos — o Dashboard a usa como indicação visível de atualização falha (Req. 3.9).
MENSAGEM_TIMEOUT_ESTATISTICAS: str = (
    "A atualização das estatísticas excedeu o tempo limite de resposta. Os dados "
    "exibidos são os últimos obtidos com sucesso e podem estar desatualizados."
)


class EstadoEstatisticasSns:
    """Coordena a agregação com timeout e o cache do último resultado válido.

    Mantém, de forma thread-safe, o último :class:`EstatisticasSns` agregado com
    sucesso. A cada chamada de :meth:`obter`, dispara a coleta das observações e a
    agregação em um worker com limite de tempo:

    - **Dentro do prazo:** o resultado vira o novo último dado válido e é devolvido
      com ``timeout=False``.
    - **Excedeu o prazo:** devolve o último dado válido preservado com
      ``timeout=True`` e a mensagem de desatualização, **sem** atualizar o horário
      da última atualização bem-sucedida (Req. 3.9).
    """

    def __init__(
        self,
        provedor_observacoes: ProvedorObservacoes,
        *,
        timeout_segundos: float = TIMEOUT_ESTATISTICAS_PADRAO_SEGUNDOS,
        agora: Optional[Callable[[], object]] = None,
    ) -> None:
        """Inicializa o estado de estatísticas.

        Args:
            provedor_observacoes: callable que devolve o iterável atual de
                observações a agregar. Permite desacoplar da origem concreta (um
                registro de eventos em memória, um repositório, etc.).
            timeout_segundos: limite de tempo da coleta/agregação (padrão 3s,
                Req. 14.1). Ajustável para testes determinísticos.
            agora: fábrica opcional do horário atual, repassada ao agregador para
                o horário da última atualização bem-sucedida (injeção para testes).
        """
        self._provedor = provedor_observacoes
        self._timeout_segundos = timeout_segundos
        self._agora = agora
        self._lock = threading.Lock()
        self._ultimo_valido: Optional[EstatisticasSns] = None
        # Executor de thread única: a agregação é curta e sem I/O próprio; o worker
        # existe apenas para impor o limite de tempo sem bloquear o event loop.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="estatisticas-sns"
        )

    def _agregar(self) -> EstatisticasSns:
        """Coleta as observações do provedor e agrega (executado no worker)."""
        observacoes = self._provedor()
        return agregar_estatisticas_sns(observacoes, agora=self._agora)

    def obter(self) -> ResultadoEstatisticasSns:
        """Devolve as estatísticas respeitando o timeout e preservando o cache.

        Returns:
            :class:`ResultadoEstatisticasSns` com o snapshot (novo ou preservado),
            a indicação de timeout e a mensagem em pt-BR correspondente.
        """
        futuro = self._executor.submit(self._agregar)
        try:
            estatisticas = futuro.result(timeout=self._timeout_segundos)
        except FutureTimeoutError:
            # Timeout: preserva os últimos dados válidos e sinaliza a falha de
            # atualização, sem avançar o horário bem-sucedido (Req. 3.9, 14.3).
            # O futuro segue em segundo plano; ao concluir, seu resultado é
            # descartado (não atualiza o cache), mantendo o horário preservado.
            with self._lock:
                ultimo = self._ultimo_valido
            return ResultadoEstatisticasSns(
                estatisticas=ultimo,
                timeout=True,
                mensagem=MENSAGEM_TIMEOUT_ESTATISTICAS,
            )

        with self._lock:
            self._ultimo_valido = estatisticas
        return ResultadoEstatisticasSns(
            estatisticas=estatisticas, timeout=False, mensagem=""
        )

    def ultimo_valido(self) -> Optional[EstatisticasSns]:
        """Retorna o último snapshot agregado com sucesso (ou ``None``)."""
        with self._lock:
            return self._ultimo_valido

    def encerrar(self) -> None:
        """Encerra o executor de apoio (liberação de recursos)."""
        self._executor.shutdown(wait=False)
