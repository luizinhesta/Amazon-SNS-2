"""Estado em memória da Config_Simulacao do laboratório SNS (Tarefa 12.1).

A **Config_Simulacao** reúne os parâmetros que existem apenas na lógica de
simulação da aplicação e que o usuário pode ajustar pelo Dashboard, dentro de
faixas definidas, sem alterar o código-fonte (Req. 2.5, 2.7, 2.8). Diferente da
**Config_Aplicada** — que reflete o que foi configurado manualmente nos recursos
SNS/SQS e só muda no Console AWS (Req. 2.9) — a Config_Simulacao é mutável em
tempo de execução.

Este módulo é o análogo SNS de :mod:`app.api.estado_simulacao` (laboratório SQS):
mantém o estado em memória, protegido por um ``threading.Lock``, pois a
API_Backend (FastAPI) pode atender requisições concorrentes. Os valores iniciais
vêm das constantes do laboratório (:mod:`app.dominio.constantes_sns`) e todo
ajuste passa pelo validador de faixa (:mod:`app.dominio.validacao_faixa_sns`),
que aceita o valor se e somente se estiver dentro da faixa e, ao rejeitar,
preserva o valor anterior (Req. 2.8).

Para não colidir com o laboratório SQS existente, este módulo recebe o sufixo
``_sns`` e consome exclusivamente as constantes e o validador de faixa do SNS.

Referências de requisitos: 2.5, 2.7, 2.8.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.dominio import constantes_sns as c
from app.dominio.validacao_faixa_sns import (
    ResultadoValidacaoFaixa,
    validar_intervalo_atualizacao,
    validar_timeout_verificacao_dlq,
    validar_timeout_verificacao_entrega,
)


@dataclass(frozen=True)
class ValoresConfigSimulacaoSns:
    """Snapshot imutável dos parâmetros de Config_Simulacao do laboratório SNS.

    Attributes:
        timeout_verificacao_entrega_segundos: Timeout_Verificacao_Entrega em
            segundos, ajustável em [5, 120] (Req. 2.5).
        timeout_verificacao_dlq_segundos: Timeout_Verificacao_DLQ em segundos,
            ajustável em [30, 300] (Req. 2.5).
        intervalo_atualizacao_segundos: Intervalo de atualização periódica em
            segundos, ajustável em [5, 300] (Req. 13.2).
    """

    timeout_verificacao_entrega_segundos: int
    timeout_verificacao_dlq_segundos: int
    intervalo_atualizacao_segundos: int


class EstadoConfigSimulacaoSns:
    """Guarda e ajusta a Config_Simulacao do SNS de forma thread-safe.

    Cada ajuste é validado pela faixa correspondente: aceito somente se dentro do
    intervalo; ao rejeitar, o valor anterior é preservado e uma mensagem em pt-BR
    com a faixa válida é retornada (Req. 2.8). Os valores iniciais vêm das
    constantes do laboratório SNS.
    """

    def __init__(
        self,
        *,
        timeout_verificacao_entrega_segundos: int = (
            c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO
        ),
        timeout_verificacao_dlq_segundos: int = c.TIMEOUT_VERIFICACAO_DLQ_PADRAO,
        intervalo_atualizacao_segundos: int = c.INTERVALO_ATUALIZACAO_PADRAO,
    ) -> None:
        self._lock = threading.Lock()
        self._timeout_entrega = timeout_verificacao_entrega_segundos
        self._timeout_dlq = timeout_verificacao_dlq_segundos
        self._intervalo_atualizacao = intervalo_atualizacao_segundos

    def valores(self) -> ValoresConfigSimulacaoSns:
        """Retorna um snapshot imutável dos valores atuais."""
        with self._lock:
            return ValoresConfigSimulacaoSns(
                timeout_verificacao_entrega_segundos=self._timeout_entrega,
                timeout_verificacao_dlq_segundos=self._timeout_dlq,
                intervalo_atualizacao_segundos=self._intervalo_atualizacao,
            )

    def ajustar_timeout_verificacao_entrega(
        self, valor_informado: object
    ) -> ResultadoValidacaoFaixa:
        """Ajusta o Timeout_Verificacao_Entrega dentro de [5, 120] (Req. 2.5, 2.8)."""
        with self._lock:
            resultado = validar_timeout_verificacao_entrega(
                valor_informado, self._timeout_entrega
            )
            self._timeout_entrega = resultado.valor_efetivo
            return resultado

    def ajustar_timeout_verificacao_dlq(
        self, valor_informado: object
    ) -> ResultadoValidacaoFaixa:
        """Ajusta o Timeout_Verificacao_DLQ dentro de [30, 300] (Req. 2.5, 2.8)."""
        with self._lock:
            resultado = validar_timeout_verificacao_dlq(
                valor_informado, self._timeout_dlq
            )
            self._timeout_dlq = resultado.valor_efetivo
            return resultado

    def ajustar_intervalo_atualizacao(
        self, valor_informado: object
    ) -> ResultadoValidacaoFaixa:
        """Ajusta o intervalo de atualização dentro de [5, 300] (Req. 13.2, 13.3)."""
        with self._lock:
            resultado = validar_intervalo_atualizacao(
                valor_informado, self._intervalo_atualizacao
            )
            self._intervalo_atualizacao = resultado.valor_efetivo
            return resultado
