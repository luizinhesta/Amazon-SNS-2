"""Testes unitários do validador de payload de disparo (Tarefa 3.1).

Verificam que a validação aceita se e somente se os campos aplicáveis são
válidos: ID_Pedido com 1 a 80 caracteres em ambos os cenários e, no FIFO,
MessageGroupId presente com 1 a 128 caracteres. Cobrem também a rejeição sempre
que uma publicação FIFO é feita sem MessageGroupId, a identificação de ao menos
um campo inválido e a preservação dos valores informados, com mensagens em pt-BR.

Referências de requisitos: 4.1, 4.7, 5.1, 5.2, 5.9, 11.5.
"""

from __future__ import annotations

import pytest

from app.dominio import constantes_sns as c
from app.dominio.tipos_sns import Cenario
from app.dominio.validacao_disparo import (
    CAMPO_ID_PEDIDO,
    CAMPO_MESSAGE_GROUP_ID,
    PayloadDisparo,
    ResultadoValidacaoDisparo,
    validar_disparo,
)


# ---------------------------------------------------------------------------
# Cenário Standard — apenas o ID_Pedido é validado
# ---------------------------------------------------------------------------

def test_standard_aceita_id_pedido_valido() -> None:
    payload = PayloadDisparo(cenario=Cenario.STANDARD, id_pedido="pedido-123")
    resultado = validar_disparo(payload)
    assert resultado.aceito is True
    assert resultado.campos_invalidos == ()
    assert resultado.mensagens == {}
    # Payload preservado integralmente (Req. 4.7).
    assert resultado.payload is payload


def test_standard_aceita_id_pedido_no_limite_minimo() -> None:
    payload = PayloadDisparo(cenario=Cenario.STANDARD, id_pedido="x")
    resultado = validar_disparo(payload)
    assert resultado.aceito is True


def test_standard_aceita_id_pedido_no_limite_maximo() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.STANDARD,
        id_pedido="x" * c.ID_PEDIDO_TAMANHO_MAX,
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is True


def test_standard_rejeita_id_pedido_vazio() -> None:
    payload = PayloadDisparo(cenario=Cenario.STANDARD, id_pedido="")
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert CAMPO_ID_PEDIDO in resultado.campos_invalidos
    assert CAMPO_ID_PEDIDO in resultado.mensagens
    # Valor informado preservado mesmo quando inválido (Req. 4.7).
    assert resultado.payload.id_pedido == ""


def test_standard_rejeita_id_pedido_acima_do_maximo() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.STANDARD,
        id_pedido="x" * (c.ID_PEDIDO_TAMANHO_MAX + 1),
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert resultado.campos_invalidos == (CAMPO_ID_PEDIDO,)


def test_standard_ignora_message_group_id() -> None:
    # No Standard o MessageGroupId é irrelevante; sua ausência não rejeita.
    payload = PayloadDisparo(
        cenario=Cenario.STANDARD,
        id_pedido="pedido-1",
        message_group_id=None,
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is True


# ---------------------------------------------------------------------------
# Cenário FIFO — ID_Pedido e MessageGroupId são validados
# ---------------------------------------------------------------------------

def test_fifo_aceita_campos_validos() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="pedido-123",
        message_group_id="grupo-A",
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is True
    assert resultado.campos_invalidos == ()
    assert resultado.mensagens == {}


def test_fifo_aceita_message_group_id_no_limite_maximo() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="pedido-1",
        message_group_id="g" * c.MESSAGE_GROUP_ID_TAMANHO_MAX,
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is True


def test_fifo_rejeita_sem_message_group_id() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="pedido-1",
        message_group_id=None,
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert CAMPO_MESSAGE_GROUP_ID in resultado.campos_invalidos
    assert "obrigatório" in resultado.mensagens[CAMPO_MESSAGE_GROUP_ID]


def test_fifo_rejeita_message_group_id_vazio() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="pedido-1",
        message_group_id="",
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert CAMPO_MESSAGE_GROUP_ID in resultado.campos_invalidos


def test_fifo_rejeita_message_group_id_acima_do_maximo() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="pedido-1",
        message_group_id="g" * (c.MESSAGE_GROUP_ID_TAMANHO_MAX + 1),
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert resultado.campos_invalidos == (CAMPO_MESSAGE_GROUP_ID,)


def test_fifo_rejeita_ambos_os_campos_invalidos() -> None:
    payload = PayloadDisparo(
        cenario=Cenario.FIFO,
        id_pedido="",
        message_group_id=None,
    )
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    # Identifica ao menos um campo inválido; aqui identifica os dois (Req. 4.7, 5.9).
    assert CAMPO_ID_PEDIDO in resultado.campos_invalidos
    assert CAMPO_MESSAGE_GROUP_ID in resultado.campos_invalidos
    # Valores informados preservados (Req. 5.9).
    assert resultado.payload.id_pedido == ""
    assert resultado.payload.message_group_id is None


def test_rejeicao_identifica_ao_menos_um_campo_invalido() -> None:
    payload = PayloadDisparo(cenario=Cenario.FIFO, id_pedido="", message_group_id="g")
    resultado = validar_disparo(payload)
    assert resultado.aceito is False
    assert len(resultado.campos_invalidos) >= 1


def test_mensagens_em_portugues() -> None:
    payload = PayloadDisparo(cenario=Cenario.FIFO, id_pedido="", message_group_id=None)
    resultado = validar_disparo(payload)
    assert resultado.mensagens[CAMPO_ID_PEDIDO].startswith("ID_Pedido inválido")
    assert resultado.mensagens[CAMPO_MESSAGE_GROUP_ID].startswith("MessageGroupId")
