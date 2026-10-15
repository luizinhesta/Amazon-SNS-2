"""Testes de integração dos endpoints de disparo Standard/FIFO do SNS (Tarefa 13.1).

Exercitam, via :class:`fastapi.testclient.TestClient`, os endpoints
``POST /api/disparar/standard``, ``POST /api/disparar/fifo`` e
``GET /api/testes/estado``, injetando um SnsGateway e um Verificador_Entrega
simulados (sem AWS real), de modo a validar:

- publicação aceita → MessageId retornado e registrado como Entrega_Publicada
  (Req. 4.2, 4.3, 5.5, 5.6);
- fan-out verificado nas três filas de destino (Destino_1/2/3) por leitura real
  correlacionada pelo ID_Pedido, com Entrega_Confirmada (Req. 4.3, 4.4, 6.1, 6.3);
- notificação apenas visual, sem SMS/e-mail reais (Req. 4.5, 4.6, 5.8);
- rejeição de validação preservando os valores e indicando o campo em pt-BR
  (Req. 4.7, 5.9, 11.5);
- falha de publicação registrando o erro original e indicando a falha em pt-BR
  (Req. 4.8, 5.10);
- estado "teste ativo" exposto do lado servidor (Req. 9.3, 9.4);
- alimentação das estatísticas por cenário (Req. 3.4, 3.5).

Referências de requisitos: 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 5.5, 5.6, 5.7, 5.8,
5.10, 9.3, 9.4, 11.5.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.acesso.sns_gateway import SnsGateway
from app.acesso.sqs_leitura_gateway_sns import MensagemVisualizada
from app.api.estado_testes_sns import (
    TESTE_DISPARAR_FIFO,
    TESTE_DISPARAR_STANDARD,
    EstadoTestesSns,
)
from app.api.rotas_sns import criar_app_sns
from app.api.verificador_entrega_sns import VerificadorEntrega
from app.dominio import constantes_sns as c
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns

MESSAGE_ID_STANDARD = "11111111-1111-1111-1111-111111111111"
MESSAGE_ID_FIFO = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# Clientes boto3 simulados
# ---------------------------------------------------------------------------
def _cliente_sns_publica_ok(message_id: str) -> MagicMock:
    cliente = MagicMock()
    cliente.publish.return_value = {"MessageId": message_id}
    return cliente


def _cliente_sns_falha(erro: Exception) -> MagicMock:
    cliente = MagicMock()
    cliente.publish.side_effect = erro
    return cliente


class _SqsLeituraFake:
    """SQS de leitura simulado: devolve, por fila, a mensagem correlacionada ou nada.

    Mapeia ``queue_url`` para uma lista de :class:`MensagemVisualizada`. O
    Verificador_Entrega correlaciona pelo ID_Pedido via os MessageAttributes.
    """

    def __init__(self, por_fila: dict[str, list[MensagemVisualizada]]) -> None:
        self._por_fila = por_fila

    def receber_para_visualizacao(
        self, queue_url: str, **_kw
    ) -> list[MensagemVisualizada]:
        return list(self._por_fila.get(queue_url, []))


def _url(nome: str) -> str:
    return f"https://sqs.local/{nome}"


def _arn(nome: str) -> str:
    return f"arn:aws:sns:us-east-1:123456789012:{nome}"


def _mensagem(id_pedido: str, message_id: str) -> MensagemVisualizada:
    return MensagemVisualizada(
        message_id=message_id,
        body="{}",
        message_attributes={
            "id_pedido": {"DataType": "String", "StringValue": id_pedido}
        },
    )


def _montar_cliente(
    *,
    cliente_sns: MagicMock,
    mensagens_por_fila: Optional[dict[str, list[MensagemVisualizada]]] = None,
    registro: Optional[RegistroObservacoesSns] = None,
    estado_testes: Optional[EstadoTestesSns] = None,
) -> TestClient:
    """Monta o app com SnsGateway e Verificador_Entrega simulados."""
    gateway = SnsGateway(cliente_sns=cliente_sns)
    leitura = _SqsLeituraFake(mensagens_por_fila or {})
    # relogio/dormir controlados: cada chamada avança 1000s, de modo que a primeira
    # leitura sem correlação já atinja o timeout e o verificador retorne "Não
    # confirmado" após uma única tentativa, sem gastar tempo real nos testes.
    estado_relogio = {"t": 0.0}

    def _relogio() -> float:
        atual = estado_relogio["t"]
        estado_relogio["t"] += 1000.0
        return atual

    verificador = VerificadorEntrega(
        leitura,  # type: ignore[arg-type]
        relogio=_relogio,
        dormir=lambda _s: None,
        pausa_entre_tentativas_s=0.0,
    )
    app = criar_app_sns(
        verificador_inicializacao_sns=MagicMock(),
        registro_observacoes_sns=registro,
        estado_testes_sns=estado_testes,
        sns_gateway=gateway,
        verificador_entrega_sns=verificador,
        resolver_arn_topico=_arn,
        resolver_url_fila=_url,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/disparar/standard
# ---------------------------------------------------------------------------
def test_standard_publica_confirma_tres_destinos_e_notificacao_visual() -> None:
    id_pedido = "pedido-123"
    mensagens = {
        _url(fila): [_mensagem(id_pedido, MESSAGE_ID_STANDARD)]
        for fila in c.FILAS_DESTINO_STANDARD
    }
    cliente = _montar_cliente(
        cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_STANDARD),
        mensagens_por_fila=mensagens,
    )

    corpo = cliente.post(
        "/api/disparar/standard", json={"id_pedido": id_pedido}
    ).json()

    assert corpo["aceito"] is True
    assert corpo["cenario"] == "standard"
    assert corpo["tipo"] == "Standard"
    assert corpo["topico"] == c.TOPICO_STANDARD
    assert corpo["message_id"] == MESSAGE_ID_STANDARD
    # Fan-out: três destinos, todos Entrega_Confirmada (Req. 4.4, 6.1, 6.3).
    assert len(corpo["destinos"]) == 3
    assert all(d["confirmada"] for d in corpo["destinos"])
    assert all(d["estado"] == "Entrega_Confirmada" for d in corpo["destinos"])
    assert {d["destino"] for d in corpo["destinos"]} == set(c.DESTINOS)
    # Notificação apenas visual (Req. 4.5).
    assert corpo["notificacao_visual"] == c.TEXTO_NOTIFICACAO_VISUAL


def test_standard_nao_envia_sms_nem_email_reais() -> None:
    # O cliente SNS só é usado para Publish; nenhuma API de SMS/e-mail é chamada.
    cliente_sns = _cliente_sns_publica_ok(MESSAGE_ID_STANDARD)
    cliente = _montar_cliente(cliente_sns=cliente_sns)

    cliente.post("/api/disparar/standard", json={"id_pedido": "p-1"})

    assert cliente_sns.publish.called
    # Nenhuma chamada de envio direto de SMS/e-mail (Req. 4.6, 5.8).
    assert not cliente_sns.set_sms_attributes.called
    assert not cliente_sns.subscribe.called


def test_standard_rejeita_id_pedido_vazio_preservando_valor() -> None:
    cliente = _montar_cliente(cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_STANDARD))

    corpo = cliente.post("/api/disparar/standard", json={"id_pedido": ""}).json()

    assert corpo["aceito"] is False
    assert "id_pedido" in corpo["campos_invalidos"]
    assert corpo["id_pedido"] == ""  # valor preservado (Req. 4.7)
    assert "id_pedido" in corpo["mensagens"]
    assert corpo["message_id"] is None  # não publicou


def test_standard_falha_publicacao_registra_erro_original_pt_br() -> None:
    erro = RuntimeError("AuthorizationError: acesso negado pelo SNS")
    cliente = _montar_cliente(cliente_sns=_cliente_sns_falha(erro))

    corpo = cliente.post(
        "/api/disparar/standard", json={"id_pedido": "p-err"}
    ).json()

    assert corpo["aceito"] is False
    assert corpo["falha_publicacao"] is True
    assert corpo["erro_original"] and "AuthorizationError" in corpo["erro_original"]
    assert "Falha ao publicar" in corpo["mensagem"]


# ---------------------------------------------------------------------------
# POST /api/disparar/fifo
# ---------------------------------------------------------------------------
def test_fifo_publica_com_message_group_id_e_confirma_destinos() -> None:
    id_pedido = "pedido-fifo"
    mgid = "grupo-A"
    mensagens = {
        _url(fila): [_mensagem(id_pedido, MESSAGE_ID_FIFO)]
        for fila in c.FILAS_DESTINO_FIFO
    }
    cliente_sns = _cliente_sns_publica_ok(MESSAGE_ID_FIFO)
    cliente = _montar_cliente(cliente_sns=cliente_sns, mensagens_por_fila=mensagens)

    corpo = cliente.post(
        "/api/disparar/fifo",
        json={"id_pedido": id_pedido, "message_group_id": mgid},
    ).json()

    assert corpo["aceito"] is True
    assert corpo["cenario"] == "fifo"
    assert corpo["tipo"] == "FIFO"
    assert corpo["topico"] == c.TOPICO_FIFO
    assert corpo["message_group_id"] == mgid
    assert corpo["message_id"] == MESSAGE_ID_FIFO
    assert all(d["confirmada"] for d in corpo["destinos"])
    # O MessageGroupId foi informado ao Publish; o MessageDeduplicationId NÃO
    # (dedup por conteúdo habilitada) — Req. 5.5, 11.3.
    _, kwargs = cliente_sns.publish.call_args
    assert kwargs["MessageGroupId"] == mgid
    assert "MessageDeduplicationId" not in kwargs


def test_fifo_sem_message_group_id_e_rejeitado() -> None:
    cliente = _montar_cliente(cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_FIFO))

    corpo = cliente.post(
        "/api/disparar/fifo", json={"id_pedido": "p-1"}
    ).json()

    assert corpo["aceito"] is False
    assert "message_group_id" in corpo["campos_invalidos"]  # Req. 11.5
    assert corpo["message_id"] is None


# ---------------------------------------------------------------------------
# GET /api/testes/estado e alimentação das estatísticas
# ---------------------------------------------------------------------------
def test_estado_testes_inicia_com_botoes_habilitados() -> None:
    cliente = _montar_cliente(cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_STANDARD))

    estado = cliente.get("/api/testes/estado").json()["testes_ativos"]

    # Nenhum teste ativo no início (todos os botões habilitados) — Req. 9.3, 9.4.
    assert estado[TESTE_DISPARAR_STANDARD] is False
    assert estado[TESTE_DISPARAR_FIFO] is False


def test_disparo_reabilita_botao_apos_concluir() -> None:
    estado_testes = EstadoTestesSns()
    cliente = _montar_cliente(
        cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_STANDARD),
        estado_testes=estado_testes,
    )

    cliente.post("/api/disparar/standard", json={"id_pedido": "p-1"})

    # Concluído o disparo, o botão é reabilitado (Req. 9.4).
    assert estado_testes.ativo(TESTE_DISPARAR_STANDARD) is False


def test_disparo_alimenta_estatisticas_por_cenario() -> None:
    registro = RegistroObservacoesSns()
    id_pedido = "p-stats"
    mensagens = {
        _url(fila): [_mensagem(id_pedido, MESSAGE_ID_STANDARD)]
        for fila in c.FILAS_DESTINO_STANDARD
    }
    cliente = _montar_cliente(
        cliente_sns=_cliente_sns_publica_ok(MESSAGE_ID_STANDARD),
        mensagens_por_fila=mensagens,
        registro=registro,
    )

    cliente.post("/api/disparar/standard", json={"id_pedido": id_pedido})

    estat = cliente.get("/api/estatisticas").json()
    standard = estat["standard"]
    # 1 publicação no tópico Standard (Req. 3.4).
    publicadas = {p["nome"]: p["valor"] for p in standard["publicadas_por_topico"]}
    assert publicadas[c.TOPICO_STANDARD] == 1
    # 3 Entrega_Confirmada (uma por fila de destino) — Req. 3.5.
    confirmadas = {p["nome"]: p["valor"] for p in standard["confirmadas_por_fila"]}
    assert sum(confirmadas.values()) == 3
    # O cenário FIFO permanece zerado (particionamento) — Req. 3.7.
    fifo = estat["fifo"]
    assert sum(p["valor"] for p in fifo["publicadas_por_topico"]) == 0
