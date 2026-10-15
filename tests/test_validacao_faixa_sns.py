"""Testes unitários do validador de faixa do SNS (Tarefa 3.3).

Verificam que o validador aceita um valor se e somente se ele estiver dentro da
faixa fechada [min, max], que ao rejeitar o valor anterior é preservado e que a
mensagem em pt-BR indica a faixa válida.

Faixas cobertas: Timeout_Verificacao_Entrega [5, 120], Timeout_Verificacao_DLQ
[30, 300] e intervalo de atualização [5, 300].

Referências de requisitos: 2.5, 2.8, 13.3.
"""

from __future__ import annotations

import pytest

from app.dominio import constantes_sns as c
from app.dominio.validacao_faixa_sns import (
    FAIXA_INTERVALO_ATUALIZACAO,
    FAIXA_TIMEOUT_VERIFICACAO_DLQ,
    FAIXA_TIMEOUT_VERIFICACAO_ENTREGA,
    Faixa,
    validar_faixa,
    validar_intervalo_atualizacao,
    validar_timeout_verificacao_dlq,
    validar_timeout_verificacao_entrega,
)


# ---------------------------------------------------------------------------
# Comportamento genérico de validar_faixa
# ---------------------------------------------------------------------------

def test_aceita_valor_dentro_da_faixa() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120)
    resultado = validar_faixa(faixa, valor_informado=30, valor_anterior=10)
    assert resultado.aceito is True
    assert resultado.valor_efetivo == 30
    assert resultado.mensagem == ""


def test_aceita_limite_inferior() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120)
    resultado = validar_faixa(faixa, valor_informado=5, valor_anterior=10)
    assert resultado.aceito is True
    assert resultado.valor_efetivo == 5


def test_aceita_limite_superior() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120)
    resultado = validar_faixa(faixa, valor_informado=120, valor_anterior=10)
    assert resultado.aceito is True
    assert resultado.valor_efetivo == 120


def test_rejeita_abaixo_do_minimo_preservando_anterior() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120, unidade="segundos")
    resultado = validar_faixa(faixa, valor_informado=4, valor_anterior=30)
    assert resultado.aceito is False
    assert resultado.valor_efetivo == 30
    assert "de 5 a 120 segundos" in resultado.mensagem
    assert "30" in resultado.mensagem


def test_rejeita_acima_do_maximo_preservando_anterior() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120)
    resultado = validar_faixa(faixa, valor_informado=121, valor_anterior=30)
    assert resultado.aceito is False
    assert resultado.valor_efetivo == 30


def test_rejeita_tipo_nao_inteiro() -> None:
    faixa = Faixa(nome="Teste", minimo=5, maximo=120)
    for invalido in ("30", 30.0, None, True):
        resultado = validar_faixa(faixa, valor_informado=invalido, valor_anterior=15)
        assert resultado.aceito is False
        assert resultado.valor_efetivo == 15


def test_faixa_invalida_min_maior_que_max() -> None:
    with pytest.raises(ValueError):
        Faixa(nome="Inválida", minimo=120, maximo=5)


# ---------------------------------------------------------------------------
# Faixas pré-definidas do laboratório SNS
# ---------------------------------------------------------------------------

def test_faixa_timeout_entrega_usa_constantes() -> None:
    assert FAIXA_TIMEOUT_VERIFICACAO_ENTREGA.minimo == c.TIMEOUT_VERIFICACAO_ENTREGA_MIN
    assert FAIXA_TIMEOUT_VERIFICACAO_ENTREGA.maximo == c.TIMEOUT_VERIFICACAO_ENTREGA_MAX
    assert (c.TIMEOUT_VERIFICACAO_ENTREGA_MIN, c.TIMEOUT_VERIFICACAO_ENTREGA_MAX) == (5, 120)


def test_faixa_timeout_dlq_usa_constantes() -> None:
    assert FAIXA_TIMEOUT_VERIFICACAO_DLQ.minimo == c.TIMEOUT_VERIFICACAO_DLQ_MIN
    assert FAIXA_TIMEOUT_VERIFICACAO_DLQ.maximo == c.TIMEOUT_VERIFICACAO_DLQ_MAX
    assert (c.TIMEOUT_VERIFICACAO_DLQ_MIN, c.TIMEOUT_VERIFICACAO_DLQ_MAX) == (30, 300)


def test_faixa_intervalo_atualizacao_usa_constantes() -> None:
    assert FAIXA_INTERVALO_ATUALIZACAO.minimo == c.INTERVALO_ATUALIZACAO_MIN
    assert FAIXA_INTERVALO_ATUALIZACAO.maximo == c.INTERVALO_ATUALIZACAO_MAX
    assert (c.INTERVALO_ATUALIZACAO_MIN, c.INTERVALO_ATUALIZACAO_MAX) == (5, 300)


def test_validar_timeout_verificacao_entrega() -> None:
    aceito = validar_timeout_verificacao_entrega(60, 30)
    assert aceito.aceito is True and aceito.valor_efetivo == 60

    rejeitado = validar_timeout_verificacao_entrega(200, 30)
    assert rejeitado.aceito is False and rejeitado.valor_efetivo == 30


def test_validar_timeout_verificacao_dlq() -> None:
    aceito = validar_timeout_verificacao_dlq(150, 120)
    assert aceito.aceito is True and aceito.valor_efetivo == 150

    rejeitado = validar_timeout_verificacao_dlq(10, 120)
    assert rejeitado.aceito is False and rejeitado.valor_efetivo == 120


def test_validar_intervalo_atualizacao() -> None:
    aceito = validar_intervalo_atualizacao(30, 10)
    assert aceito.aceito is True and aceito.valor_efetivo == 30

    rejeitado = validar_intervalo_atualizacao(301, 10)
    assert rejeitado.aceito is False and rejeitado.valor_efetivo == 10
