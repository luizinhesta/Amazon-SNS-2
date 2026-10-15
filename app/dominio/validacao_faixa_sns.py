"""Validador de faixa genérico para parâmetros de Config_Simulacao do SNS.

Implementa a regra de aceitação por faixa fechada: um valor é aceito se e somente
se ``min <= valor <= max``. Ao rejeitar, o valor anterior é preservado e uma
mensagem em pt-BR com a faixa válida é produzida (Req. 2.8, 13.3).

Este módulo é lógica de domínio pura (função pura, sem efeitos colaterais) e
consome apenas as constantes de faixa definidas em
:mod:`app.dominio.constantes_sns`.

Faixas suportadas (Tarefa 3.3):
- Timeout_Verificacao_Entrega [5, 120] segundos (Req. 2.5, 2.8).
- Timeout_Verificacao_DLQ [30, 300] segundos (Req. 2.5, 2.8).
- intervalo de atualização [5, 300] segundos (Req. 13.2, 13.3).

Referências de requisitos: 2.5, 2.8, 13.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.dominio import constantes_sns as c


@dataclass(frozen=True)
class Faixa:
    """Faixa fechada ``[minimo, maximo]`` nomeada para mensagens em pt-BR.

    Attributes:
        nome: rótulo em pt-BR do parâmetro (ex.: "Timeout de verificação de entrega").
        minimo: limite inferior aceito (inclusivo).
        maximo: limite superior aceito (inclusivo).
        unidade: unidade opcional exibida na mensagem (ex.: "segundos").
    """

    nome: str
    minimo: int
    maximo: int
    unidade: str = ""

    def __post_init__(self) -> None:
        if self.minimo > self.maximo:
            raise ValueError(
                "Faixa inválida: o limite mínimo não pode ser maior que o máximo."
            )

    def contem(self, valor: int) -> bool:
        """Retorna ``True`` se e somente se ``minimo <= valor <= maximo``."""
        return self.minimo <= valor <= self.maximo

    def descricao(self) -> str:
        """Descreve a faixa válida em pt-BR, incluindo a unidade quando houver."""
        sufixo = f" {self.unidade}" if self.unidade else ""
        return f"de {self.minimo} a {self.maximo}{sufixo}"


@dataclass(frozen=True)
class ResultadoValidacaoFaixa:
    """Resultado da validação de faixa.

    Attributes:
        aceito: indica se o valor informado foi aceito.
        valor_efetivo: valor que passa a valer — o novo valor se aceito, ou o valor
            anterior preservado se rejeitado.
        mensagem: mensagem em pt-BR; vazia quando aceito, com a faixa válida quando
            rejeitado.
    """

    aceito: bool
    valor_efetivo: int
    mensagem: str


def _eh_inteiro(valor: object) -> bool:
    """Indica se o valor representa um inteiro legítimo.

    ``bool`` é subtipo de ``int`` em Python; aqui tratamos booleanos como inválidos
    para campos numéricos, pois não representam um valor de faixa legítimo.
    """

    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_faixa(
    faixa: Faixa, valor_informado: object, valor_anterior: int
) -> ResultadoValidacaoFaixa:
    """Valida ``valor_informado`` contra ``faixa``, preservando ``valor_anterior``.

    Aceita o valor se e somente se ele for um inteiro dentro da faixa fechada
    ``[faixa.minimo, faixa.maximo]`` (Req. 2.8, 13.3). Ao rejeitar — valor fora da
    faixa ou de tipo não inteiro — o ``valor_anterior`` é preservado como valor
    efetivo e a mensagem em pt-BR indica a faixa válida.

    Args:
        faixa: a faixa fechada nomeada contra a qual validar.
        valor_informado: o valor que o usuário deseja aplicar.
        valor_anterior: o valor atualmente em vigor, preservado em caso de rejeição.

    Returns:
        ResultadoValidacaoFaixa com ``aceito``, ``valor_efetivo`` e ``mensagem``.
    """
    if _eh_inteiro(valor_informado) and faixa.contem(valor_informado):
        return ResultadoValidacaoFaixa(
            aceito=True,
            valor_efetivo=valor_informado,
            mensagem="",
        )

    mensagem = (
        f"Valor inválido para {faixa.nome}: {valor_informado}. "
        f"Informe um valor {faixa.descricao()}. "
        f"O valor anterior ({valor_anterior}) foi preservado."
    )
    return ResultadoValidacaoFaixa(
        aceito=False,
        valor_efetivo=valor_anterior,
        mensagem=mensagem,
    )


# ---------------------------------------------------------------------------
# Faixas pré-definidas do laboratório SNS (usam as constantes de constantes_sns)
# ---------------------------------------------------------------------------

# Timeout_Verificacao_Entrega [5, 120] segundos (Req. 2.5, 2.8).
FAIXA_TIMEOUT_VERIFICACAO_ENTREGA: Final[Faixa] = Faixa(
    nome="Timeout de verificação de entrega",
    minimo=c.TIMEOUT_VERIFICACAO_ENTREGA_MIN,
    maximo=c.TIMEOUT_VERIFICACAO_ENTREGA_MAX,
    unidade="segundos",
)

# Timeout_Verificacao_DLQ [30, 300] segundos (Req. 2.5, 2.8).
FAIXA_TIMEOUT_VERIFICACAO_DLQ: Final[Faixa] = Faixa(
    nome="Timeout de verificação da DLQ",
    minimo=c.TIMEOUT_VERIFICACAO_DLQ_MIN,
    maximo=c.TIMEOUT_VERIFICACAO_DLQ_MAX,
    unidade="segundos",
)

# Intervalo de atualização periódica [5, 300] segundos (Req. 13.2, 13.3).
FAIXA_INTERVALO_ATUALIZACAO: Final[Faixa] = Faixa(
    nome="Intervalo de atualização",
    minimo=c.INTERVALO_ATUALIZACAO_MIN,
    maximo=c.INTERVALO_ATUALIZACAO_MAX,
    unidade="segundos",
)


def validar_timeout_verificacao_entrega(
    valor_informado: object, valor_anterior: int
) -> ResultadoValidacaoFaixa:
    """Valida o Timeout_Verificacao_Entrega [5, 120] (Req. 2.5, 2.8)."""
    return validar_faixa(
        FAIXA_TIMEOUT_VERIFICACAO_ENTREGA, valor_informado, valor_anterior
    )


def validar_timeout_verificacao_dlq(
    valor_informado: object, valor_anterior: int
) -> ResultadoValidacaoFaixa:
    """Valida o Timeout_Verificacao_DLQ [30, 300] (Req. 2.5, 2.8)."""
    return validar_faixa(
        FAIXA_TIMEOUT_VERIFICACAO_DLQ, valor_informado, valor_anterior
    )


def validar_intervalo_atualizacao(
    valor_informado: object, valor_anterior: int
) -> ResultadoValidacaoFaixa:
    """Valida o intervalo de atualização periódica [5, 300] (Req. 13.2, 13.3)."""
    return validar_faixa(
        FAIXA_INTERVALO_ATUALIZACAO, valor_informado, valor_anterior
    )
