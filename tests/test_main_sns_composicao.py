"""Testes de integração da composição do laboratório SNS na EC2 (Tarefa 16.1).

Validam, via :class:`fastapi.testclient.TestClient` e com um verificador de
inicialização de clientes boto3 **simulados** (sem AWS real), as três
responsabilidades do entrypoint :mod:`app.main_sns`:

- o **Dashboard** estático (``web/sns/``) é servido na raiz quando a verificação de
  inicialização é bem-sucedida (Req. 9.1 — a mesma aplicação serve a API e o
  Dashboard), e a API continua respondendo sob ``/api`` (precedência sobre os
  estáticos);
- a disponibilização do Dashboard é **condicionada** à verificação: quando um recurso
  AWS está ausente/inacessível, o Dashboard **não** fica disponível (HTTP 503) e a
  causa é exposta em pt-BR, identificando o recurso por nome e tipo; ``GET /api/saude``
  segue respondendo com ``saudavel=False`` (Req. 1.9);
- **ausência de loops/schedulers/automação**: a composição não registra *startup
  events* nem sobe *threads* de segundo plano, e cada teste roda apenas por
  acionamento manual dos endpoints (Req. 9.1, 9.2, 9.5, 9.6, 9.7).

Referências de requisitos: 1.9, 9.1, 9.2, 9.5, 9.6, 9.7.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main_sns import compor_aplicacao_sns
from app.dominio import constantes_sns as c
from app.verificacao_inicializacao_sns import VerificacaoInicializacaoSns

NOME_IAM_ROLE = "delivery-sns-lab-role"
ID_INSTANCIA_EC2 = "i-0abc123def456"
REGIAO = c.REGIAO_AWS
CONTA = "123456789012"


# ---------------------------------------------------------------------------
# Clientes boto3 simulados (recursos presentes) — espelham test_rotas_sns.py
# ---------------------------------------------------------------------------
def _arn_topico(nome: str) -> str:
    return f"arn:aws:sns:{REGIAO}:{CONTA}:{nome}"


def _cliente_sns_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.list_topics.return_value = {
        "Topics": [{"TopicArn": _arn_topico(nome)} for nome in c.TOPICOS]
    }
    cliente.get_topic_attributes.return_value = {"Attributes": {"TopicArn": "x"}}

    def _subs(TopicArn: str, **_kw):
        nome = TopicArn.rsplit(":", 1)[-1]
        filas = c.FILAS_DESTINO_POR_TOPICO.get(nome, ())
        return {
            "Subscriptions": [
                {
                    "SubscriptionArn": f"arn:aws:sns:{REGIAO}:{CONTA}:{nome}:sub-{i}",
                    "Protocol": "sqs",
                    "Endpoint": f"arn:aws:sqs:{REGIAO}:{CONTA}:{fila}",
                }
                for i, fila in enumerate(filas)
            ]
        }

    cliente.list_subscriptions_by_topic.side_effect = _subs
    return cliente


def _cliente_sqs_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.get_queue_url.side_effect = lambda QueueName: {
        "QueueUrl": f"https://sqs.{REGIAO}.amazonaws.com/{CONTA}/{QueueName}"
    }
    cliente.get_queue_attributes.return_value = {
        "Attributes": {"QueueArn": "arn:aws:sqs:...:fila"}
    }
    return cliente


def _cliente_iam_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.get_role.return_value = {"Role": {"RoleName": NOME_IAM_ROLE}}
    return cliente


def _cliente_ec2_ok() -> MagicMock:
    cliente = MagicMock()
    cliente.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": ID_INSTANCIA_EC2}]}]
    }
    return cliente


def _verificador_ok() -> VerificacaoInicializacaoSns:
    return VerificacaoInicializacaoSns(
        cliente_sns=_cliente_sns_ok(),
        cliente_sqs=_cliente_sqs_ok(),
        cliente_iam=_cliente_iam_ok(),
        cliente_ec2=_cliente_ec2_ok(),
        nome_iam_role=NOME_IAM_ROLE,
        id_instancia_ec2=ID_INSTANCIA_EC2,
    )


def _verificador_sem_ec2() -> VerificacaoInicializacaoSns:
    """Todos os recursos presentes, exceto a instância EC2 (nenhuma reserva)."""
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": []}
    return VerificacaoInicializacaoSns(
        cliente_sns=_cliente_sns_ok(),
        cliente_sqs=_cliente_sqs_ok(),
        cliente_iam=_cliente_iam_ok(),
        cliente_ec2=ec2,
        nome_iam_role=NOME_IAM_ROLE,
        id_instancia_ec2=ID_INSTANCIA_EC2,
    )


def _compor(verificador: VerificacaoInicializacaoSns) -> "FastAPI":  # type: ignore[name-defined]
    # ``ambiente={}`` evita que variáveis do ambiente real do executor influenciem o
    # teste; a autenticação cai no modo laboratório padrão (origens não liberadas),
    # sem efeito sobre os endpoints exercitados aqui.
    return compor_aplicacao_sns(
        verificador_inicializacao_sns=verificador,
        ambiente={},
    )


# ---------------------------------------------------------------------------
# Verificação bem-sucedida: Dashboard servido + API disponível
# ---------------------------------------------------------------------------
def test_dashboard_servido_quando_verificacao_ok() -> None:
    app = _compor(_verificador_ok())

    assert app.state.resultado_verificacao_sns.sucesso is True

    cliente = TestClient(app)
    # A raiz serve o index.html do Dashboard SNS (StaticFiles com html=True).
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "AWS SNS Delivery Lab" in resposta.text


def test_api_tem_precedencia_sobre_estaticos_quando_ok() -> None:
    app = _compor(_verificador_ok())
    cliente = TestClient(app)

    # Mesmo com o Dashboard montado na raiz, a API responde sob /api.
    corpo = cliente.get("/api/saude").json()
    assert corpo["saudavel"] is True
    assert corpo["recursos"] and all(r["disponivel"] for r in corpo["recursos"])

    # A arquitetura confirma que todos os roteadores foram registrados.
    arquitetura = cliente.get("/api/arquitetura").json()
    assert len(arquitetura["topicos"]) == 2
    assert len(arquitetura["assinaturas"]) == 6
    assert len(arquitetura["filas_destino"]) == 6
    assert len(arquitetura["dlqs"]) == 2


# ---------------------------------------------------------------------------
# Verificação falha: Dashboard bloqueado (503) + causa em pt-BR
# ---------------------------------------------------------------------------
def test_dashboard_bloqueado_quando_verificacao_falha() -> None:
    app = _compor(_verificador_sem_ec2())

    assert app.state.resultado_verificacao_sns.sucesso is False

    cliente = TestClient(app)
    resposta = cliente.get("/")

    assert resposta.status_code == 503
    corpo = resposta.json()
    # A causa em pt-BR identifica o recurso indisponível por nome e tipo.
    assert "verificação de inicialização" in corpo["detail"]
    assert corpo["recurso_indisponivel"]["tipo"] == "instância EC2"
    assert corpo["recurso_indisponivel"]["nome"] == ID_INSTANCIA_EC2


def test_saude_continua_respondendo_quando_dashboard_bloqueado() -> None:
    app = _compor(_verificador_sem_ec2())
    cliente = TestClient(app)

    # GET /api/saude segue respondendo (modo não interruptivo) para inspeção.
    corpo = cliente.get("/api/saude").json()
    assert corpo["saudavel"] is False
    indisponiveis = [r for r in corpo["recursos"] if not r["disponivel"]]
    assert len(indisponiveis) == 1
    assert indisponiveis[0]["tipo"] == "instância EC2"
    assert indisponiveis[0]["detalhe_erro"]  # erro original preservado


def test_qualquer_caminho_estatico_bloqueado_mas_api_responde_404_coerente() -> None:
    app = _compor(_verificador_sem_ec2())
    cliente = TestClient(app)

    # Caminho estático arbitrário é bloqueado com 503.
    assert cliente.get("/styles.css").status_code == 503
    # Uma rota de API inexistente devolve 404 (não 503), pois o fallback distingue /api.
    assert cliente.get("/api/rota-que-nao-existe").status_code == 404


# ---------------------------------------------------------------------------
# Ausência de loops / schedulers / automação (Req. 9.1, 9.2, 9.5, 9.6, 9.7)
# ---------------------------------------------------------------------------
def test_composicao_nao_registra_startup_events() -> None:
    """A composição não agenda nenhum processo de fundo no ciclo de vida da app.

    Diferentemente do laboratório SQS, o entrypoint SNS não registra handlers de
    ``startup`` que subam threads/schedulers; os testes rodam só sob demanda.
    """
    app = _compor(_verificador_ok())
    assert app.router.on_startup == []
    assert app.router.on_shutdown == []


def test_subir_a_aplicacao_nao_deixa_threads_de_fundo_persistentes() -> None:
    """Entrar e sair do ciclo de vida da aplicação não deixa threads próprias vivas.

    O ``TestClient`` do Starlette sobe threads internas (portal/servidor) apenas
    enquanto o contexto está ativo; elas são encerradas no fim do ``with``. O que
    importa para esta tarefa é que a **aplicação** não suba laços de teste, carga ou
    agendamento automático que **persistam** após o shutdown — ao contrário do
    laboratório SQS, que inicia consumidores/supervisor em threads daemon (Req. 9.2).

    Comparamos as threads vivas antes de compor e depois de o ciclo de vida terminar:
    nenhuma thread adicional da aplicação deve sobreviver.
    """
    antes = threading.active_count()

    app = _compor(_verificador_ok())
    with TestClient(app) as cliente:
        cliente.get("/api/saude")

    depois = threading.active_count()

    # Nenhuma thread de fundo da aplicação persiste após o shutdown.
    assert depois <= antes
    # A composição não guardou nenhum gerenciador de processos de fundo em app.state.
    assert not hasattr(app.state, "gerenciador_consumidores")
    assert not hasattr(app.state, "gerenciador_monitor_dlq")
