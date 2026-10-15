"""Testes de integração do endpoint de comparação Standard x FIFO (Tarefa 13.2).

Exercitam, via :class:`fastapi.testclient.TestClient`, o endpoint
``POST /api/comparar``, injetando um SnsGateway e um gateway de leitura SQS
simulados (sem AWS real), de modo a validar:

- execução de **dois testes independentes**, um Standard e um FIFO (Req. 7.1);
- publicação das **três mensagens** sequenciais "Pedido criado", "Compra
  aprovada" e "Pedido em preparação", nessa ordem, em ambos os cenários (Req.
  7.2, 7.3);
- uso de um **único MessageGroupId** no teste FIFO (Req. 7.3);
- retorno da **ordem de publicação**, da **ordem de recebimento** (observada por
  leitura real, sem reordenar) e do **MessageId** de cada mensagem, para os dois
  testes **lado a lado** (Req. 7.4, 7.5);
- **texto explicativo em pt-BR** de que o Standard não garante ordenação (Req.
  7.6);
- estado **"Não confirmado"** quando uma mensagem não é confirmada dentro do
  Timeout_Verificacao_Entrega (Req. 7.9);
- **interrupção com causa em pt-BR** quando o tópico está indisponível ou a
  autenticação falha (Req. 7.8);
- estado "teste ativo" (botão COMPARAR) reabilitado ao concluir (Req. 9.3, 9.4).

Referências de requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9.
"""

from __future__ import annotations

import json
from typing import Optional
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.acesso.sns_gateway import SnsGateway
from app.acesso.sqs_leitura_gateway_sns import MensagemVisualizada
from app.api.estado_testes_sns import TESTE_COMPARAR, EstadoTestesSns
from app.api.rotas_sns import criar_app_sns
from app.dominio import constantes_sns as c
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns


# ---------------------------------------------------------------------------
# Clientes/gateways boto3 simulados
# ---------------------------------------------------------------------------
def _cliente_sns_sequencia(message_ids: list[str]) -> MagicMock:
    """SNS simulado que devolve um MessageId distinto por chamada de publish."""
    cliente = MagicMock()
    cliente.publish.side_effect = [{"MessageId": mid} for mid in message_ids]
    return cliente


def _cliente_sns_falha(erro: Exception) -> MagicMock:
    cliente = MagicMock()
    cliente.publish.side_effect = erro
    return cliente


class _SqsLeituraFake:
    """Gateway de leitura SQS simulado: devolve, por fila, mensagens fixas.

    O conteúdo de cada mensagem é embrulhado no envelope padrão do SNS (campo
    ``Message`` com o JSON do payload de aplicação), como chega numa fila sem raw
    message delivery, para exercitar a extração de conteúdo da ordem de recebimento.
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


def _mensagem(
    id_pedido: str, cenario: str, conteudo: str, message_id: str
) -> MensagemVisualizada:
    """Monta uma mensagem como o SNS a entrega numa fila (envelope SNS)."""
    payload = {
        "id_pedido": id_pedido,
        "cenario": cenario,
        "destino": c.DESTINO_1,
        "titulo_destino": c.TITULO_DESTINO[c.DESTINO_1],
        "conteudo": conteudo,
        "app_time": "2024-01-01T00:00:00+00:00",
        "sequencia": 1,
    }
    envelope = {
        "Type": "Notification",
        "MessageId": message_id,
        "Message": json.dumps(payload, ensure_ascii=False),
        "MessageAttributes": {
            "id_pedido": {"Type": "String", "Value": id_pedido},
            "cenario": {"Type": "String", "Value": cenario},
        },
    }
    return MensagemVisualizada(
        message_id=message_id,
        body=json.dumps(envelope, ensure_ascii=False),
        message_attributes={
            "id_pedido": {"DataType": "String", "StringValue": id_pedido}
        },
    )


def _mensagens_do_destino1(
    id_pedido: str, cenario: str, conteudos_e_ids: list[tuple[str, str]]
) -> dict[str, list[MensagemVisualizada]]:
    """Coloca as mensagens na fila Destino_1 do cenário (a lida pela comparação)."""
    filas = (
        c.FILAS_DESTINO_STANDARD if cenario == "standard" else c.FILAS_DESTINO_FIFO
    )
    destino1 = filas[0]
    return {
        _url(destino1): [
            _mensagem(id_pedido, cenario, conteudo, mid)
            for conteudo, mid in conteudos_e_ids
        ]
    }


def _montar_cliente(
    *,
    cliente_sns: MagicMock,
    mensagens_por_fila: Optional[dict[str, list[MensagemVisualizada]]] = None,
    registro: Optional[RegistroObservacoesSns] = None,
    estado_testes: Optional[EstadoTestesSns] = None,
) -> TestClient:
    """Monta o app com SnsGateway e gateway de leitura SQS simulados."""
    gateway = SnsGateway(cliente_sns=cliente_sns)
    leitura = _SqsLeituraFake(mensagens_por_fila or {})
    # relogio controlado: cada chamada avança 1000s, de modo que, após uma única
    # leitura sem completar o total esperado, o timeout seja atingido e as
    # mensagens faltantes virem "Não confirmado" sem gastar tempo real.
    estado_relogio = {"t": 0.0}

    def _relogio() -> float:
        atual = estado_relogio["t"]
        estado_relogio["t"] += 1000.0
        return atual

    app = criar_app_sns(
        verificador_inicializacao_sns=MagicMock(),
        registro_observacoes_sns=registro,
        estado_testes_sns=estado_testes,
        sns_gateway=gateway,
        sqs_leitura_gateway_sns=leitura,  # type: ignore[arg-type]
        resolver_arn_topico=_arn,
        resolver_url_fila=_url,
    )
    # Substitui relógio/dormir do serviço de comparação para determinismo.
    servico = app.state.servico_comparacao_sns
    servico._relogio = _relogio  # type: ignore[attr-defined]
    servico._dormir = lambda _s: None  # type: ignore[attr-defined]
    servico._pausa_entre_tentativas_s = 0.0  # type: ignore[attr-defined]
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/comparar — caminho feliz
# ---------------------------------------------------------------------------
def test_comparar_executa_dois_testes_independentes_lado_a_lado() -> None:
    id_pedido = "pedido-cmp"
    msgs = c.MENSAGENS_COMPARACAO
    # IDs de publicação: 3 Standard + 3 FIFO (ordem das chamadas de publish).
    ids_pub = ["s1", "s2", "s3", "f1", "f2", "f3"]
    cliente_sns = _cliente_sns_sequencia(list(ids_pub))

    # Standard chega fora de ordem (demonstração), FIFO chega na ordem publicada.
    recebidas_standard = _mensagens_do_destino1(
        id_pedido,
        "standard",
        [(msgs[1], "rs2"), (msgs[0], "rs1"), (msgs[2], "rs3")],
    )
    recebidas_fifo = _mensagens_do_destino1(
        id_pedido,
        "fifo",
        [(msgs[0], "rf1"), (msgs[1], "rf2"), (msgs[2], "rf3")],
    )
    mensagens = {**recebidas_standard, **recebidas_fifo}

    cliente = _montar_cliente(cliente_sns=cliente_sns, mensagens_por_fila=mensagens)

    corpo = cliente.post("/api/comparar", json={"id_pedido": id_pedido}).json()

    assert corpo["concluido"] is True
    assert corpo["interrompido"] is False
    # Dois testes independentes, lado a lado (Req. 7.1, 7.5).
    assert corpo["standard"]["tipo"] == "Standard"
    assert corpo["fifo"]["tipo"] == "FIFO"
    # Ordem de publicação: as três mensagens na sequência correta (Req. 7.2, 7.3).
    pub_std = [m["conteudo"] for m in corpo["standard"]["ordem_publicacao"]]
    pub_fifo = [m["conteudo"] for m in corpo["fifo"]["ordem_publicacao"]]
    assert pub_std == list(msgs)
    assert pub_fifo == list(msgs)
    # Ordem de recebimento apresentada SEM reordenar (Req. 7.7).
    rec_std = [i["conteudo"] for i in corpo["standard"]["ordem_recebimento"]]
    rec_fifo = [i["conteudo"] for i in corpo["fifo"]["ordem_recebimento"]]
    assert rec_std == [msgs[1], msgs[0], msgs[2]]  # ordem exata de leitura
    assert rec_fifo == list(msgs)
    # MessageId presente em cada mensagem (Req. 7.4).
    assert [m["message_id"] for m in corpo["standard"]["ordem_publicacao"]] == [
        "s1",
        "s2",
        "s3",
    ]
    # Texto explicativo em pt-BR sobre ausência de garantia de ordenação (Req. 7.6).
    assert "não garante ordenação" in corpo["observacao"]


def test_comparar_fifo_usa_um_unico_message_group_id() -> None:
    id_pedido = "pedido-mgid"
    cliente_sns = _cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"])
    cliente = _montar_cliente(cliente_sns=cliente_sns)

    corpo = cliente.post(
        "/api/comparar",
        json={"id_pedido": id_pedido, "message_group_id": "grupo-unico"},
    ).json()

    assert corpo["fifo"]["message_group_id"] == "grupo-unico"
    # As três publicações FIFO (chamadas 4, 5, 6) usaram o mesmo MessageGroupId e
    # nenhuma enviou MessageDeduplicationId (dedup por conteúdo habilitada).
    chamadas_fifo = cliente_sns.publish.call_args_list[3:]
    assert len(chamadas_fifo) == 3
    for _, kwargs in chamadas_fifo:
        assert kwargs["MessageGroupId"] == "grupo-unico"
        assert "MessageDeduplicationId" not in kwargs


def test_comparar_message_group_id_derivado_quando_ausente() -> None:
    id_pedido = "pedido-derivado"
    cliente_sns = _cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"])
    cliente = _montar_cliente(cliente_sns=cliente_sns)

    corpo = cliente.post("/api/comparar", json={"id_pedido": id_pedido}).json()

    # MessageGroupId derivado do ID_Pedido, único para o teste FIFO (Req. 7.3).
    assert corpo["fifo"]["message_group_id"] == f"comparacao-{id_pedido}"


def test_comparar_mensagens_nao_confirmadas_aparecem_como_nao_confirmado() -> None:
    id_pedido = "pedido-timeout"
    cliente_sns = _cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"])
    # Nenhuma mensagem nas filas → nada é confirmado dentro do timeout (Req. 7.9).
    cliente = _montar_cliente(cliente_sns=cliente_sns, mensagens_por_fila={})

    corpo = cliente.post("/api/comparar", json={"id_pedido": id_pedido}).json()

    for teste in (corpo["standard"], corpo["fifo"]):
        assert len(teste["ordem_recebimento"]) == 3
        assert all(
            item["estado"] == "Não confirmado" and item["confirmada"] is False
            for item in teste["ordem_recebimento"]
        )
        assert all(item["conteudo"] is None for item in teste["ordem_recebimento"])


def test_comparar_confirmacao_parcial_completa_com_nao_confirmado() -> None:
    id_pedido = "pedido-parcial"
    msgs = c.MENSAGENS_COMPARACAO
    cliente_sns = _cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"])
    # Apenas 1 das 3 mensagens chega em cada fila Destino_1.
    mensagens = {
        **_mensagens_do_destino1(id_pedido, "standard", [(msgs[0], "rs1")]),
        **_mensagens_do_destino1(id_pedido, "fifo", [(msgs[0], "rf1")]),
    }
    cliente = _montar_cliente(cliente_sns=cliente_sns, mensagens_por_fila=mensagens)

    corpo = cliente.post("/api/comparar", json={"id_pedido": id_pedido}).json()

    std = corpo["standard"]["ordem_recebimento"]
    assert len(std) == 3
    assert std[0]["confirmada"] is True and std[0]["conteudo"] == msgs[0]
    assert std[1]["estado"] == "Não confirmado"
    assert std[2]["estado"] == "Não confirmado"


# ---------------------------------------------------------------------------
# POST /api/comparar — interrupção (Req. 7.8)
# ---------------------------------------------------------------------------
def test_comparar_interrompe_com_causa_pt_br_quando_publicacao_falha() -> None:
    erro = RuntimeError("AuthorizationError: tópico indisponível")
    cliente = _montar_cliente(cliente_sns=_cliente_sns_falha(erro))

    corpo = cliente.post("/api/comparar", json={"id_pedido": "p-err"}).json()

    assert corpo["concluido"] is False
    assert corpo["interrompido"] is True
    assert "interrompida" in corpo["mensagem"].lower()
    assert corpo["erro_original"] and "AuthorizationError" in corpo["erro_original"]


# ---------------------------------------------------------------------------
# Estado do teste COMPARAR (Req. 9.3, 9.4)
# ---------------------------------------------------------------------------
def test_comparar_reabilita_botao_apos_concluir() -> None:
    estado_testes = EstadoTestesSns()
    cliente = _montar_cliente(
        cliente_sns=_cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"]),
        estado_testes=estado_testes,
    )

    cliente.post("/api/comparar", json={"id_pedido": "p-estado"})

    # Concluída a comparação, o botão COMPARAR é reabilitado (Req. 9.4).
    assert estado_testes.ativo(TESTE_COMPARAR) is False


def test_comparar_alimenta_estatisticas_por_cenario() -> None:
    registro = RegistroObservacoesSns()
    id_pedido = "p-stats-cmp"
    msgs = c.MENSAGENS_COMPARACAO
    cliente_sns = _cliente_sns_sequencia(["s1", "s2", "s3", "f1", "f2", "f3"])
    mensagens = {
        **_mensagens_do_destino1(
            id_pedido,
            "standard",
            [(msgs[0], "rs1"), (msgs[1], "rs2"), (msgs[2], "rs3")],
        ),
        **_mensagens_do_destino1(
            id_pedido,
            "fifo",
            [(msgs[0], "rf1"), (msgs[1], "rf2"), (msgs[2], "rf3")],
        ),
    }
    cliente = _montar_cliente(
        cliente_sns=cliente_sns, mensagens_por_fila=mensagens, registro=registro
    )

    cliente.post("/api/comparar", json={"id_pedido": id_pedido})

    estat = cliente.get("/api/estatisticas").json()
    # 3 publicações em cada tópico (uma por mensagem de comparação) — Req. 7.4.
    pub_std = {p["nome"]: p["valor"] for p in estat["standard"]["publicadas_por_topico"]}
    pub_fifo = {p["nome"]: p["valor"] for p in estat["fifo"]["publicadas_por_topico"]}
    assert pub_std[c.TOPICO_STANDARD] == 3
    assert pub_fifo[c.TOPICO_FIFO] == 3
