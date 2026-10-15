"""Testes de integração do endpoint de autenticação do SNS (Tarefa 13.4).

Exercitam, via :class:`fastapi.testclient.TestClient` (httpx), o endpoint
``POST /api/autenticacao`` do laboratório **AWS SNS Delivery Lab**, injetando um
:class:`ControladorAutenticacaoSns` com **relógio controlável** e um verificador de
credenciais determinístico, sem AWS real:

- sucesso com credenciais válidas (``acesso_concedido=True``, Req. 12.5);
- falha com credenciais inválidas (``acesso_concedido=False``, Req. 12.5);
- bloqueio da origem após 5 falhas consecutivas por 300 s, com recusa das novas
  tentativas durante o bloqueio e liberação após a expiração verificada pelo
  relógio injetado, sem ``sleep`` real (Req. 12.6);
- um sucesso antes do limite reinicia a contagem de falhas (Req. 12.6);
- a resposta não expõe credenciais da AWS no navegador (Req. 12.4).

Referências de requisitos: 12.4, 12.5, 12.6.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.rotas_sns import criar_app_sns
from app.api.servico_autenticacao_sns import CredenciaisDashboardSns
from app.dominio import constantes_sns as c
from app.seguranca.autenticacao_sns import ControladorAutenticacaoSns

USUARIO = "admin"
SENHA = "senha-de-teste"
ORIGEM = "203.0.113.10"


class RelogioFake:
    """Relógio controlável para testar expiração do bloqueio sem sleep real."""

    def __init__(self, inicial: float = 0.0) -> None:
        self.agora = inicial

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def _cliente(relogio: RelogioFake) -> TestClient:
    """Monta o app SNS com controlador (relógio fake) e credenciais injetadas.

    O verificador de inicialização é um :class:`MagicMock` para não acionar boto3:
    o endpoint de autenticação não depende de recursos AWS.
    """
    controlador = ControladorAutenticacaoSns(
        permitir_todas_origens=True, relogio=relogio
    )
    app = criar_app_sns(
        verificador_inicializacao_sns=MagicMock(),
        controlador_autenticacao_sns=controlador,
        credenciais_dashboard_sns=CredenciaisDashboardSns(
            usuario=USUARIO, senha=SENHA
        ),
    )
    return TestClient(app)


def _login(cliente: TestClient, usuario: str, senha: str) -> dict:
    resposta = cliente.post(
        "/api/autenticacao",
        json={"usuario": usuario, "senha": senha, "origem": ORIGEM},
    )
    assert resposta.status_code == 200
    return resposta.json()


# ---------------------------------------------------------------------------
# Req. 12.5 — sucesso e falha de autenticação
# ---------------------------------------------------------------------------
def test_login_com_credenciais_validas_concede_acesso() -> None:
    cliente = _cliente(RelogioFake())

    corpo = _login(cliente, USUARIO, SENHA)

    assert corpo["acesso_concedido"] is True
    assert corpo["resultado"] == "SUCESSO"
    assert corpo["bloqueada"] is False
    assert corpo["segundos_restantes_bloqueio"] == 0


def test_login_com_credenciais_invalidas_nega_acesso() -> None:
    cliente = _cliente(RelogioFake())

    corpo = _login(cliente, USUARIO, "senha-errada")

    assert corpo["acesso_concedido"] is False
    assert corpo["resultado"] == "FALHA"
    assert corpo["bloqueada"] is False


# ---------------------------------------------------------------------------
# Req. 12.6 — bloqueio após 5 falhas consecutivas por 300 s
# ---------------------------------------------------------------------------
def test_bloqueio_apos_cinco_falhas_consecutivas() -> None:
    relogio = RelogioFake()
    cliente = _cliente(relogio)
    max_tentativas = c.MAX_TENTATIVAS_AUTENTICACAO

    # As (max-1) primeiras falhas não bloqueiam.
    for _ in range(max_tentativas - 1):
        corpo = _login(cliente, USUARIO, "senha-errada")
        assert corpo["resultado"] == "FALHA"
        assert corpo["bloqueada"] is False

    # A 5ª falha consecutiva dispara o bloqueio por 300 s.
    corpo = _login(cliente, USUARIO, "senha-errada")
    assert corpo["bloqueada"] is True
    assert corpo["resultado"] == "BLOQUEADA"
    assert corpo["segundos_restantes_bloqueio"] == c.BLOQUEIO_AUTENTICACAO_SEGUNDOS

    # Durante o bloqueio, mesmo credenciais válidas são recusadas sem avaliar.
    corpo = _login(cliente, USUARIO, SENHA)
    assert corpo["bloqueada"] is True
    assert corpo["acesso_concedido"] is False
    assert 0 < corpo["segundos_restantes_bloqueio"] <= c.BLOQUEIO_AUTENTICACAO_SEGUNDOS


def test_bloqueio_expira_apos_300_segundos() -> None:
    relogio = RelogioFake()
    cliente = _cliente(relogio)

    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO):
        _login(cliente, USUARIO, "senha-errada")

    # Avança além do período de bloqueio: a origem é liberada.
    relogio.avancar(c.BLOQUEIO_AUTENTICACAO_SEGUNDOS + 1)

    corpo = _login(cliente, USUARIO, SENHA)
    assert corpo["acesso_concedido"] is True
    assert corpo["bloqueada"] is False


def test_sucesso_antes_do_limite_reinicia_contagem() -> None:
    relogio = RelogioFake()
    cliente = _cliente(relogio)

    # Quatro falhas (uma a menos que o limite).
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO - 1):
        _login(cliente, USUARIO, "senha-errada")

    # Um sucesso reinicia a contagem de falhas consecutivas.
    corpo = _login(cliente, USUARIO, SENHA)
    assert corpo["acesso_concedido"] is True

    # Uma nova falha, após o sucesso, não deve bloquear (contagem reiniciada).
    corpo = _login(cliente, USUARIO, "senha-errada")
    assert corpo["bloqueada"] is False
    assert corpo["resultado"] == "FALHA"


# ---------------------------------------------------------------------------
# Req. 12.4 — não exposição de credenciais da AWS no navegador
# ---------------------------------------------------------------------------
def test_resposta_nao_expoe_credenciais_da_aws() -> None:
    cliente = _cliente(RelogioFake())

    resposta = cliente.post(
        "/api/autenticacao",
        json={"usuario": USUARIO, "senha": SENHA, "origem": ORIGEM},
    )
    corpo = resposta.json()

    # Nenhuma chave sensível (senha, segredo, credencial da AWS) na resposta.
    chaves_proibidas = {
        "senha",
        "password",
        "secret",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "credenciais",
        "credentials",
    }
    assert chaves_proibidas.isdisjoint(set(corpo.keys()))
    # Também não deve ecoar a senha informada em nenhum valor textual.
    assert SENHA not in resposta.text


def test_origem_ausente_usa_host_do_cliente() -> None:
    """Quando a origem não é informada, o host do cliente é usado (Req. 12.7)."""
    cliente = _cliente(RelogioFake())

    resposta = cliente.post(
        "/api/autenticacao",
        json={"usuario": USUARIO, "senha": SENHA},
    )
    assert resposta.status_code == 200
    assert resposta.json()["acesso_concedido"] is True
