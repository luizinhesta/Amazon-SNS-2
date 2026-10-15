"""Testes unitários do controle de autenticação do laboratório SNS (Tarefa 10.1).

Verificam o controlador de tentativas por origem (lógica pura, com relógio
injetável) e o tratamento de falha de autorização via IAM_Role_EC2:

- Não exposição de credenciais da AWS no navegador (Req. 12.4).
- Exigência de usuário/senha válidos para conceder acesso (Req. 12.5).
- Bloqueio da origem após 5 falhas consecutivas por 300 segundos, com expiração
  verificada via relógio injetado, sem ``sleep`` real (Req. 12.6).
- Um sucesso antes do limite reinicia a contagem de falhas (Req. 12.6).
- Restrição às origens autorizadas (Req. 12.7).
- Falha de autorização via IAM interrompendo a operação, registrando o evento e
  expondo erro sem persistir dados parciais (Req. 12.9).

Referências de requisitos: 12.4, 12.5, 12.6, 12.7, 12.9.
"""

from __future__ import annotations

import pytest

from app.dominio import constantes_sns as c
from app.seguranca.autenticacao_sns import (
    ControladorAutenticacaoSns,
    EventoFalhaAutorizacao,
    FalhaAutorizacaoIAM,
    RegistroFalhasAutorizacao,
    ResultadoAutenticacao,
    sanear_para_navegador,
    tratar_falha_autorizacao,
)


class RelogioFake:
    """Relógio controlável para testar expiração do bloqueio sem sleep real."""

    def __init__(self, inicial: float = 0.0) -> None:
        self.agora = inicial

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


ORIGEM = "203.0.113.10"


def _controlador(relogio: RelogioFake | None = None) -> ControladorAutenticacaoSns:
    """Cria um controlador com a origem padrão já autorizada (Req. 12.7)."""
    rel = relogio or RelogioFake()
    return ControladorAutenticacaoSns([ORIGEM], relogio=rel)


# ---------------------------------------------------------------------------
# Req. 12.5 — exigência de usuário/senha válidos
# ---------------------------------------------------------------------------


def test_sucesso_concede_acesso() -> None:
    controlador = _controlador()
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    assert avaliacao.resultado is ResultadoAutenticacao.SUCESSO
    assert avaliacao.acesso_concedido is True
    assert avaliacao.falhas_consecutivas == 0


def test_falha_nao_concede_acesso() -> None:
    controlador = _controlador()
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)
    assert avaliacao.resultado is ResultadoAutenticacao.FALHA
    assert avaliacao.acesso_concedido is False
    assert avaliacao.falhas_consecutivas == 1


# ---------------------------------------------------------------------------
# Req. 12.6 — bloqueio após 5 falhas consecutivas por 300 s
# ---------------------------------------------------------------------------


def test_bloqueia_apos_cinco_falhas_consecutivas() -> None:
    controlador = _controlador()
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO - 1):
        avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)
        assert avaliacao.resultado is ResultadoAutenticacao.FALHA

    # 5ª falha dispara o bloqueio.
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)
    assert avaliacao.resultado is ResultadoAutenticacao.BLOQUEADA
    assert avaliacao.bloqueada is True
    assert avaliacao.segundos_restantes_bloqueio == c.BLOQUEIO_AUTENTICACAO_SEGUNDOS
    assert controlador.esta_bloqueada(ORIGEM)


def test_bloqueio_recusa_credenciais_validas_enquanto_vigente() -> None:
    relogio = RelogioFake()
    controlador = _controlador(relogio)
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO):
        controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)

    # Mesmo com credenciais válidas, o acesso é recusado durante o bloqueio.
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    assert avaliacao.resultado is ResultadoAutenticacao.BLOQUEADA
    assert avaliacao.acesso_concedido is False


def test_bloqueio_expira_apos_300_segundos() -> None:
    relogio = RelogioFake()
    controlador = _controlador(relogio)
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO):
        controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)

    assert controlador.esta_bloqueada(ORIGEM)
    # Pouco antes de expirar ainda está bloqueada.
    relogio.avancar(c.BLOQUEIO_AUTENTICACAO_SEGUNDOS - 1)
    assert controlador.esta_bloqueada(ORIGEM)
    # Após 300 s, o bloqueio expira e a autenticação volta a ser possível.
    relogio.avancar(1)
    assert not controlador.esta_bloqueada(ORIGEM)
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    assert avaliacao.resultado is ResultadoAutenticacao.SUCESSO


def test_sucesso_antes_do_limite_reinicia_contagem() -> None:
    controlador = _controlador()
    # 4 falhas (uma a menos que o limite).
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO - 1):
        controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)

    # Um sucesso reinicia a contagem.
    sucesso = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    assert sucesso.falhas_consecutivas == 0

    # Agora mais 4 falhas não devem bloquear (contagem reiniciou).
    for _ in range(c.MAX_TENTATIVAS_AUTENTICACAO - 1):
        avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=False)
        assert avaliacao.resultado is ResultadoAutenticacao.FALHA
    assert not controlador.esta_bloqueada(ORIGEM)


# ---------------------------------------------------------------------------
# Req. 12.7 — restrição às origens autorizadas
# ---------------------------------------------------------------------------


def test_origem_nao_autorizada_e_rejeitada() -> None:
    controlador = _controlador()
    avaliacao = controlador.avaliar_tentativa(
        "198.51.100.5", credenciais_validas=True
    )
    assert avaliacao.resultado is ResultadoAutenticacao.ORIGEM_NAO_AUTORIZADA
    assert avaliacao.acesso_concedido is False


def test_sem_origens_autorizadas_nada_e_permitido_por_padrao() -> None:
    controlador = ControladorAutenticacaoSns(relogio=RelogioFake())
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    assert avaliacao.resultado is ResultadoAutenticacao.ORIGEM_NAO_AUTORIZADA


def test_permitir_todas_origens_libera_qualquer_origem() -> None:
    controlador = ControladorAutenticacaoSns(
        permitir_todas_origens=True, relogio=RelogioFake()
    )
    avaliacao = controlador.avaliar_tentativa(
        "qualquer-origem", credenciais_validas=True
    )
    assert avaliacao.resultado is ResultadoAutenticacao.SUCESSO


def test_autorizar_e_revogar_origem() -> None:
    controlador = ControladorAutenticacaoSns(relogio=RelogioFake())
    controlador.autorizar_origem(ORIGEM)
    assert controlador.origem_autorizada(ORIGEM)
    controlador.revogar_origem(ORIGEM)
    assert not controlador.origem_autorizada(ORIGEM)


# ---------------------------------------------------------------------------
# Req. 12.4 — não expor credenciais da AWS no navegador
# ---------------------------------------------------------------------------


def test_sanear_remove_credenciais_aws() -> None:
    dados = {
        "resultado": "SUCESSO",
        "aws_access_key_id": "AKIAEXEMPLO",
        "aws_secret_access_key": "segredo",
        "aws_session_token": "token",
        "mensagem": "ok",
    }
    saneado = sanear_para_navegador(dados)
    assert "aws_access_key_id" not in saneado
    assert "aws_secret_access_key" not in saneado
    assert "aws_session_token" not in saneado
    assert saneado["resultado"] == "SUCESSO"
    assert saneado["mensagem"] == "ok"


def test_sanear_e_recursivo_e_cobre_senha() -> None:
    dados = {
        "usuario": "admin",
        "senha": "123",
        "config": {"password": "x", "regiao": "us-east-1"},
    }
    saneado = sanear_para_navegador(dados)
    assert "senha" not in saneado
    assert saneado["usuario"] == "admin"
    assert saneado["config"] == {"regiao": "us-east-1"}


def test_para_navegador_nao_expoe_credenciais() -> None:
    controlador = _controlador()
    avaliacao = controlador.avaliar_tentativa(ORIGEM, credenciais_validas=True)
    payload = avaliacao.para_navegador()
    chaves = {str(k).lower() for k in payload}
    assert not any("secret" in k or "key" in k or "senha" in k for k in chaves)
    assert payload["acesso_concedido"] is True


# ---------------------------------------------------------------------------
# Req. 12.9 — falha de autorização via IAM_Role_EC2
# ---------------------------------------------------------------------------


def test_tratar_falha_autorizacao_registra_evento_sem_dados_parciais() -> None:
    registro = RegistroFalhasAutorizacao()
    evento = tratar_falha_autorizacao(
        operacao="Publish",
        recurso="arn:aws:sns:us-east-1:123456789012:delivery-sns-standard",
        erro_original="AccessDenied",
        registro=registro,
    )
    assert isinstance(evento, EventoFalhaAutorizacao)
    assert registro.quantidade() == 1
    assert evento.operacao == "Publish"
    assert evento.erro_original == "AccessDenied"
    assert "interrompida" in evento.mensagem
    assert "nenhum dado parcial" in evento.mensagem


def test_falha_autorizacao_iam_preserva_erro_original() -> None:
    erro = FalhaAutorizacaoIAM(
        operacao="ReceiveMessage",
        recurso="delivery-sns-sms-standard",
        erro_original="AccessDenied",
    )
    assert erro.operacao == "ReceiveMessage"
    assert erro.recurso == "delivery-sns-sms-standard"
    assert erro.erro_original == "AccessDenied"
    assert "ReceiveMessage" in str(erro)


# ---------------------------------------------------------------------------
# Validação de parâmetros do construtor
# ---------------------------------------------------------------------------


def test_construtor_rejeita_max_tentativas_invalido() -> None:
    with pytest.raises(ValueError):
        ControladorAutenticacaoSns(max_tentativas=0)


def test_construtor_rejeita_bloqueio_negativo() -> None:
    with pytest.raises(ValueError):
        ControladorAutenticacaoSns(bloqueio_segundos=-1)
