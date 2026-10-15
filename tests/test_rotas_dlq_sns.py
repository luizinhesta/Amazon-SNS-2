"""Testes de integração do endpoint de teste de DLQ do SNS (Tarefa 13.3).

Exercitam, via :class:`fastapi.testclient.TestClient`, o endpoint
``POST /api/dlq/simular-falha``, injetando um Gerenciador_Falha_Controlada, um
SnsGateway e um gateway de leitura SQS simulados (sem AWS real), de modo a
validar o fluxo de Falha_Entrega_Controlada → DLQ do SNS:

- seleção de uma Assinatura_SNS específica (cenário + destino) (Req. 8.1);
- salvamento e aplicação do ``Deny`` temporário na fila de destino alvo via
  Gerenciador_Falha_Controlada, sem excluir filas nem assinaturas (Req. 8.2);
- publicação da mensagem de teste no tópico correspondente (Req. 8.3);
- verificação das demais assinaturas do mesmo tópico (Req. 8.4);
- verificação da DLQ compatível até o Timeout_Verificacao_DLQ (Req. 8.5);
- confirmação na DLQ exibida como Evento_Observado (Req. 8.6);
- estado "Não confirmado" quando a DLQ não confirma no timeout (Req. 8.7);
- restauração da Access_Policy_Fila ao final — sempre, inclusive em erro (Req. 8.8);
- orientação de restauração manual em pt-BR quando a restauração falha (Req. 8.9);
- acionamento manual (o teste só roda quando o endpoint é chamado) (Req. 8.10);
- texto explicativo em pt-BR sobre a DLQ do SNS (Req. 8.11);
- estado "teste ativo" (botão TESTAR DLQ) reabilitado ao concluir (Req. 9.1, 9.3, 9.4).

Referências de requisitos: 8.1-8.11, 9.1, 9.3, 9.4.
"""

from __future__ import annotations

import json
from typing import Optional
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.acesso.gerenciador_falha_controlada_sns import ResultadoRestauracao
from app.acesso.sns_gateway import SnsGateway
from app.acesso.sqs_leitura_gateway_sns import MensagemVisualizada
from app.api.estado_testes_sns import TESTE_DLQ, EstadoTestesSns
from app.api.rotas_sns import criar_app_sns
from app.dominio import constantes_sns as c
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns


# ---------------------------------------------------------------------------
# Componentes simulados
# ---------------------------------------------------------------------------
class _GerenciadorFalhaFake:
    """Gerenciador_Falha_Controlada simulado: registra as chamadas do round-trip.

    Permite verificar que a policy foi salva e o ``Deny`` aplicado ANTES da
    publicação, e que a restauração ocorreu ao final (sempre). O desfecho da
    restauração é configurável para exercitar o caminho de falha (Req. 8.9).
    """

    def __init__(self, restauracao: Optional[ResultadoRestauracao] = None) -> None:
        self.chamadas: list[str] = []
        self.policy_salva = {"Version": "2012-10-17", "Statement": []}
        self._restauracao = restauracao or ResultadoRestauracao(sucesso=True)
        self.deny_queue_url: Optional[str] = None
        self.deny_topic_arn: Optional[str] = None

    def salvar_policy_original(self, queue_url: str):
        self.chamadas.append(f"salvar:{queue_url}")
        return self.policy_salva

    def aplicar_deny_temporario(self, queue_url: str, topic_arn: str) -> None:
        self.chamadas.append(f"deny:{queue_url}")
        self.deny_queue_url = queue_url
        self.deny_topic_arn = topic_arn

    def restaurar_policy(self, queue_url: str, policy_original) -> ResultadoRestauracao:
        self.chamadas.append(f"restaurar:{queue_url}")
        return self._restauracao


class _SqsLeituraFake:
    """Gateway de leitura SQS simulado: devolve, por fila, mensagens fixas."""

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


def _cliente_sns(message_id: str = "mid-teste") -> MagicMock:
    cliente = MagicMock()
    cliente.publish.return_value = {"MessageId": message_id}
    return cliente


def _cliente_sns_falha(erro: Exception) -> MagicMock:
    cliente = MagicMock()
    cliente.publish.side_effect = erro
    return cliente


def _mensagem(id_pedido: str, cenario: str, message_id: str) -> MensagemVisualizada:
    """Monta uma mensagem como o SNS a entrega numa fila/DLQ (envelope SNS)."""
    payload = {
        "id_pedido": id_pedido,
        "cenario": cenario,
        "destino": c.DESTINO_1,
        "titulo_destino": c.TITULO_DESTINO[c.DESTINO_1],
        "conteudo": c.TEXTO_NOTIFICACAO_VISUAL,
        "app_time": "2024-01-01T00:00:00+00:00",
        "sequencia": 1,
    }
    envelope = {
        "Type": "Notification",
        "MessageId": message_id,
        "Message": json.dumps(payload, ensure_ascii=False),
    }
    return MensagemVisualizada(
        message_id=message_id,
        body=json.dumps(envelope, ensure_ascii=False),
        message_attributes={
            "id_pedido": {"DataType": "String", "StringValue": id_pedido}
        },
    )


def _montar_cliente(
    *,
    cliente_sns: MagicMock,
    gerenciador: Optional[_GerenciadorFalhaFake] = None,
    mensagens_por_fila: Optional[dict[str, list[MensagemVisualizada]]] = None,
    registro: Optional[RegistroObservacoesSns] = None,
    estado_testes: Optional[EstadoTestesSns] = None,
) -> tuple[TestClient, _GerenciadorFalhaFake]:
    """Monta o app com Gerenciador_Falha_Controlada, SnsGateway e leitura simulados.

    O relógio do VerificadorEntrega é substituído por um que avança em saltos
    grandes, de modo que, após uma leitura sem correlação, o timeout seja atingido
    sem gastar tempo real (as verificações "Não confirmado" ficam determinísticas).
    """
    gateway = SnsGateway(cliente_sns=cliente_sns)
    leitura = _SqsLeituraFake(mensagens_por_fila or {})
    gerente = gerenciador or _GerenciadorFalhaFake()

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
        gerenciador_falha_controlada_sns=gerente,  # type: ignore[arg-type]
        resolver_arn_topico=_arn,
        resolver_url_fila=_url,
    )
    verificador = app.state.servico_dlq_sns._verificador  # type: ignore[attr-defined]
    verificador._relogio = _relogio  # type: ignore[attr-defined]
    verificador._dormir = lambda _s: None  # type: ignore[attr-defined]
    return TestClient(app), gerente


# ---------------------------------------------------------------------------
# Caminho feliz: confirmação na DLQ (Evento_Observado) e policy restaurada
# ---------------------------------------------------------------------------
def test_simular_falha_confirma_na_dlq_e_restaura_policy() -> None:
    id_pedido = "pedido-dlq"
    gerente = _GerenciadorFalhaFake()
    # A mensagem de teste é confirmada na DLQ Standard; as demais filas (destino_2
    # e destino_3) continuam confirmando a entrega.
    mensagens = {
        _url(c.DLQ_SNS_STANDARD): [_mensagem(id_pedido, "standard", "dlq-1")],
        _url(c.FILA_DESTINO2_STANDARD): [_mensagem(id_pedido, "standard", "d2")],
        _url(c.FILA_DESTINO3_STANDARD): [_mensagem(id_pedido, "standard", "d3")],
    }
    cliente, gerente = _montar_cliente(
        cliente_sns=_cliente_sns("mid-teste"),
        gerenciador=gerente,
        mensagens_por_fila=mensagens,
    )

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": id_pedido},
    ).json()

    assert corpo["concluido"] is True
    # Assinatura selecionada e fila afetada (Destino_1 Standard) (Req. 8.1).
    assert corpo["fila_destino_afetada"] == c.FILA_DESTINO1_STANDARD
    assert corpo["destino"] == "destino_1"
    assert corpo["tipo"] == "Standard"
    # Publicação de teste (Req. 8.3).
    assert corpo["message_id_teste"] == "mid-teste"
    # Confirmação na DLQ como Evento_Observado (Req. 8.5, 8.6).
    assert corpo["estado_dlq"] == "Entrega_Confirmada"
    assert corpo["dlq"] == c.DLQ_SNS_STANDARD
    # Demais assinaturas confirmadas (Req. 8.4).
    assert len(corpo["demais_assinaturas"]) == 2
    assert all(a["confirmada"] is True for a in corpo["demais_assinaturas"])
    destinos = {a["destino"] for a in corpo["demais_assinaturas"]}
    assert destinos == {"destino_2", "destino_3"}
    # Policy restaurada ao final (Req. 8.8).
    assert corpo["policy_restaurada"] is True
    # Texto explicativo em pt-BR sobre a DLQ do SNS (Req. 8.11).
    assert "DLQ" in corpo["texto_explicativo"]
    assert "assinatura" in corpo["texto_explicativo"].lower()
    # Ordem do round-trip: salvar e aplicar Deny ANTES; restaurar ao final.
    assert gerente.chamadas[0].startswith("salvar:")
    assert gerente.chamadas[1].startswith("deny:")
    assert gerente.chamadas[-1].startswith("restaurar:")
    # O Deny foi aplicado na fila alvo com o ARN do tópico (Req. 8.2).
    assert gerente.deny_queue_url == _url(c.FILA_DESTINO1_STANDARD)
    assert gerente.deny_topic_arn == _arn(c.TOPICO_STANDARD)


def test_simular_falha_registra_presenca_na_dlq_como_evento_observado() -> None:
    id_pedido = "pedido-stats"
    registro = RegistroObservacoesSns()
    mensagens = {
        _url(c.DLQ_SNS_STANDARD): [_mensagem(id_pedido, "standard", "dlq-1")],
    }
    cliente, _ = _montar_cliente(
        cliente_sns=_cliente_sns(),
        mensagens_por_fila=mensagens,
        registro=registro,
    )

    cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": id_pedido},
    )

    estat = cliente.get("/api/estatisticas").json()
    dlq_std = {d["nome"]: d["valor"] for d in estat["standard"]["presentes_por_dlq"]}
    assert dlq_std.get(c.DLQ_SNS_STANDARD) == 1


# ---------------------------------------------------------------------------
# DLQ não confirma no timeout → "Não confirmado" (Req. 8.7)
# ---------------------------------------------------------------------------
def test_simular_falha_dlq_nao_confirmada_fica_nao_confirmado() -> None:
    id_pedido = "pedido-timeout"
    # Nenhuma mensagem na DLQ → "Não confirmado" ao atingir o Timeout_Verificacao_DLQ.
    cliente, _ = _montar_cliente(cliente_sns=_cliente_sns(), mensagens_por_fila={})

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": id_pedido},
    ).json()

    assert corpo["concluido"] is True
    assert corpo["estado_dlq"] == "Não confirmado"
    assert corpo["dlq_message_id"] is None
    # Mesmo sem confirmação, a policy é restaurada (Req. 8.8).
    assert corpo["policy_restaurada"] is True


# ---------------------------------------------------------------------------
# Falha na restauração → orienta restauração manual (Req. 8.9)
# ---------------------------------------------------------------------------
def test_simular_falha_restauracao_falha_orienta_restauracao_manual() -> None:
    id_pedido = "pedido-restaura"
    gerente = _GerenciadorFalhaFake(
        restauracao=ResultadoRestauracao(
            sucesso=False,
            mensagem=(
                "Falha ao restaurar a Access_Policy_Fila. Restaure manualmente "
                "pelo Console AWS."
            ),
            fila_afetada=_url(c.FILA_DESTINO1_STANDARD),
        )
    )
    cliente, _ = _montar_cliente(cliente_sns=_cliente_sns(), gerenciador=gerente)

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": id_pedido},
    ).json()

    assert corpo["policy_restaurada"] is False
    assert "Console AWS" in corpo["mensagem_restauracao"]


# ---------------------------------------------------------------------------
# Erro de publicação → restaura mesmo assim e repassa a causa (Req. 8.8)
# ---------------------------------------------------------------------------
def test_simular_falha_erro_de_publicacao_restaura_e_reporta_causa() -> None:
    erro = RuntimeError("AuthorizationError: tópico indisponível")
    gerente = _GerenciadorFalhaFake()
    cliente, gerente = _montar_cliente(
        cliente_sns=_cliente_sns_falha(erro), gerenciador=gerente
    )

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": "p-err"},
    ).json()

    assert corpo["concluido"] is False
    assert corpo["erro_original"] and "AuthorizationError" in corpo["erro_original"]
    # A restauração é garantida mesmo em erro de publicação (Req. 8.8).
    assert gerente.chamadas[-1].startswith("restaurar:")
    assert corpo["policy_restaurada"] is True


# ---------------------------------------------------------------------------
# Cenário FIFO: DLQ e tópico FIFO corretos
# ---------------------------------------------------------------------------
def test_simular_falha_cenario_fifo_usa_dlq_e_topico_fifo() -> None:
    id_pedido = "pedido-fifo"
    cliente_sns = _cliente_sns("mid-fifo")
    mensagens = {
        _url(c.DLQ_SNS_FIFO): [_mensagem(id_pedido, "fifo", "dlq-f")],
    }
    cliente, gerente = _montar_cliente(
        cliente_sns=cliente_sns, mensagens_por_fila=mensagens
    )

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "fifo", "destino": "destino_2", "id_pedido": id_pedido},
    ).json()

    assert corpo["tipo"] == "FIFO"
    assert corpo["topico"] == c.TOPICO_FIFO
    assert corpo["dlq"] == c.DLQ_SNS_FIFO
    assert corpo["fila_destino_afetada"] == c.FILA_DESTINO2_FIFO
    # Publicação FIFO usa MessageGroupId único derivado do ID_Pedido.
    _, kwargs = cliente_sns.publish.call_args
    assert kwargs["MessageGroupId"] == f"dlq-{id_pedido}"
    assert "MessageDeduplicationId" not in kwargs
    assert gerente.deny_topic_arn == _arn(c.TOPICO_FIFO)


# ---------------------------------------------------------------------------
# Seleção inválida: não altera recursos e orienta a seleção correta (Req. 8.1)
# ---------------------------------------------------------------------------
def test_simular_falha_destino_invalido_nao_altera_recursos() -> None:
    gerente = _GerenciadorFalhaFake()
    cliente, gerente = _montar_cliente(
        cliente_sns=_cliente_sns(), gerenciador=gerente
    )

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_9", "id_pedido": "p"},
    ).json()

    assert corpo["concluido"] is False
    assert "Assinatura_SNS" in corpo["mensagem"]
    # Nenhuma alteração de Access_Policy_Fila (nenhuma chamada ao gerenciador).
    assert gerente.chamadas == []


def test_simular_falha_cenario_invalido_nao_altera_recursos() -> None:
    gerente = _GerenciadorFalhaFake()
    cliente, gerente = _montar_cliente(
        cliente_sns=_cliente_sns(), gerenciador=gerente
    )

    corpo = cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "outro", "destino": "destino_1", "id_pedido": "p"},
    ).json()

    assert corpo["concluido"] is False
    assert gerente.chamadas == []


# ---------------------------------------------------------------------------
# Estado do teste TESTAR DLQ (Req. 9.1, 9.3, 9.4)
# ---------------------------------------------------------------------------
def test_simular_falha_reabilita_botao_apos_concluir() -> None:
    estado_testes = EstadoTestesSns()
    cliente, _ = _montar_cliente(
        cliente_sns=_cliente_sns(), estado_testes=estado_testes
    )

    cliente.post(
        "/api/dlq/simular-falha",
        json={"cenario": "standard", "destino": "destino_1", "id_pedido": "p-estado"},
    )

    assert estado_testes.ativo(TESTE_DLQ) is False
