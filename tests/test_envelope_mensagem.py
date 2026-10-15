"""Testes do envelope de mensagem e da extração de ID_Pedido (Tarefa 2.1).

Cobrem a estrutura do payload de aplicação, a montagem dos MessageAttributes da
publicação SNS e a extração do ID_Pedido a partir do envelope SNS recebido na
fila de destino (campo Message e MessageAttributes).

Referências de requisitos: 6.1, 6.3, 10.1.
"""

from __future__ import annotations

import json

from app.dominio.envelope_mensagem import (
    PayloadAplicacao,
    extrair_id_pedido,
)
from app.dominio.tipos_sns import Cenario


def _payload_exemplo() -> PayloadAplicacao:
    return PayloadAplicacao(
        id_pedido="pedido-0001",
        cenario=Cenario.STANDARD,
        destino="destino_1",
        titulo_destino="Confirmação da aprovação da compra",
        conteudo="Seu pedido foi aprovado e está sendo preparado",
        app_time="2024-06-25T12:00:00.123Z",
        sequencia=1,
    )


# ---------------------------------------------------------------------------
# Estrutura do payload de aplicação (Envelope de mensagem)
# ---------------------------------------------------------------------------


def test_payload_para_dict_tem_todos_os_campos_do_envelope() -> None:
    # Req. 6.1: o payload corresponde ao JSON da seção Data Models.
    dados = _payload_exemplo().para_dict()
    assert dados == {
        "id_pedido": "pedido-0001",
        "cenario": "standard",
        "destino": "destino_1",
        "titulo_destino": "Confirmação da aprovação da compra",
        "conteudo": "Seu pedido foi aprovado e está sendo preparado",
        "app_time": "2024-06-25T12:00:00.123Z",
        "sequencia": 1,
    }


def test_payload_cenario_serializado_como_string() -> None:
    assert _payload_exemplo().para_dict()["cenario"] == "standard"

    fifo = PayloadAplicacao(
        id_pedido="pedido-0002",
        cenario=Cenario.FIFO,
        destino="destino_2",
        titulo_destino="Solicitação para a cozinha preparar o alimento",
        conteudo="texto",
        app_time="2024-06-25T12:00:00.123Z",
        sequencia=2,
    )
    assert fifo.para_dict()["cenario"] == "fifo"


def test_payload_para_json_preserva_acentuacao() -> None:
    corpo = _payload_exemplo().para_json()
    # Não deve escapar caracteres não-ASCII (pt-BR).
    assert "está" in corpo
    assert json.loads(corpo)["id_pedido"] == "pedido-0001"


def test_payload_round_trip_de_dict() -> None:
    original = _payload_exemplo()
    reconstruido = PayloadAplicacao.de_dict(original.para_dict())
    assert reconstruido == original


# ---------------------------------------------------------------------------
# MessageAttributes da publicação SNS
# ---------------------------------------------------------------------------


def test_message_attributes_tem_id_pedido_e_cenario() -> None:
    # Req. 6.3, 10.1: atributos permitem correlação pelo ID_Pedido.
    atributos = _payload_exemplo().message_attributes()
    assert atributos == {
        "id_pedido": {"DataType": "String", "StringValue": "pedido-0001"},
        "cenario": {"DataType": "String", "StringValue": "standard"},
    }


# ---------------------------------------------------------------------------
# Extração do ID_Pedido do envelope SNS recebido na fila
# ---------------------------------------------------------------------------


def test_extrai_id_pedido_dos_message_attributes_formato_sqs() -> None:
    # Formato recebido na fila (SNS envelope): atributos com Type/Value.
    envelope = {
        "Type": "Notification",
        "MessageId": "a1b2c3d4-0001",
        "Message": json.dumps({"id_pedido": "pedido-0001", "cenario": "standard"}),
        "MessageAttributes": {
            "id_pedido": {"Type": "String", "Value": "pedido-0001"},
            "cenario": {"Type": "String", "Value": "standard"},
        },
    }
    assert extrair_id_pedido(envelope) == "pedido-0001"


def test_extrai_id_pedido_do_corpo_message_quando_sem_atributos() -> None:
    # Sem MessageAttributes: recorre ao JSON do campo Message.
    envelope = {
        "Type": "Notification",
        "MessageId": "a1b2c3d4-0002",
        "Message": json.dumps(
            {
                "id_pedido": "pedido-0002",
                "cenario": "fifo",
                "destino": "destino_1",
                "conteudo": "texto",
            }
        ),
    }
    assert extrair_id_pedido(envelope) == "pedido-0002"


def test_atributos_tem_precedencia_sobre_o_corpo() -> None:
    # Quando ambos existem, usa o valor dos MessageAttributes.
    envelope = {
        "Message": json.dumps({"id_pedido": "do-corpo"}),
        "MessageAttributes": {
            "id_pedido": {"Type": "String", "Value": "dos-atributos"},
        },
    }
    assert extrair_id_pedido(envelope) == "dos-atributos"


def test_aceita_atributo_no_formato_de_publicacao_string_value() -> None:
    # Robustez: também aceita StringValue (formato da publicação SNS).
    envelope = {
        "MessageAttributes": {
            "id_pedido": {"DataType": "String", "StringValue": "pedido-0003"},
        },
    }
    assert extrair_id_pedido(envelope) == "pedido-0003"


def test_retorna_none_quando_id_pedido_ausente() -> None:
    envelope = {
        "Type": "Notification",
        "Message": json.dumps({"cenario": "standard", "conteudo": "texto"}),
        "MessageAttributes": {"cenario": {"Type": "String", "Value": "standard"}},
    }
    assert extrair_id_pedido(envelope) is None


def test_retorna_none_para_corpo_json_invalido_sem_atributos() -> None:
    envelope = {"Message": "{isto não é json"}
    assert extrair_id_pedido(envelope) is None


def test_retorna_none_para_envelope_nao_dict_ou_vazio() -> None:
    assert extrair_id_pedido({}) is None
    assert extrair_id_pedido(None) is None  # type: ignore[arg-type]
    assert extrair_id_pedido("string") is None  # type: ignore[arg-type]


def test_cai_para_o_corpo_quando_atributo_id_pedido_vazio() -> None:
    # Atributo presente porém vazio não deve impedir o fallback ao corpo.
    envelope = {
        "Message": json.dumps({"id_pedido": "pedido-0004"}),
        "MessageAttributes": {"id_pedido": {"Type": "String", "Value": ""}},
    }
    assert extrair_id_pedido(envelope) == "pedido-0004"
