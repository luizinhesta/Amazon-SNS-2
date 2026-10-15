"""Serviço de autenticação do Dashboard do laboratório SNS (Tarefa 13.4).

Encapsula a lógica do endpoint ``POST /api/autenticacao`` do laboratório **AWS SNS
Delivery Lab**, mantendo o roteador FastAPI fino. É análogo a
:mod:`app.api.servico_autenticacao` (laboratório SQS), porém dedicado ao contexto
SNS: reutiliza o :class:`app.seguranca.autenticacao_sns.ControladorAutenticacaoSns`,
que implementa o bloqueio por origem após 5 falhas consecutivas por 300 segundos
(Req. 12.6) e a restrição às origens autorizadas (Req. 12.7).

A verificação das credenciais (usuário/senha) é delegada a um **validador
injetável** (:class:`CredenciaisDashboardSns`), de modo que os testes forneçam
credenciais determinísticas sem segredos no código. A comparação usa
``hmac.compare_digest`` para evitar vazamento por tempo. As credenciais da AWS
**nunca** são expostas ao navegador: a avaliação é serializada por
:meth:`AvaliacaoAutenticacao.para_navegador` e saneada por
:func:`app.seguranca.autenticacao_sns.sanear_para_navegador`, descartando qualquer
chave sensível antes do envio ao cliente (Req. 12.4).

Referências de requisitos: 12.4, 12.5, 12.6, 12.7.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from app.seguranca.autenticacao_sns import (
    AvaliacaoAutenticacao,
    ControladorAutenticacaoSns,
    sanear_para_navegador,
)


@dataclass(frozen=True)
class CredenciaisDashboardSns:
    """Credenciais esperadas do Dashboard (usuário/senha) para o login (Req. 12.5).

    Em produção, os valores vêm de uma fonte segura (ex.: parâmetro protegido),
    jamais de Access Keys da AWS. Nos testes, injeta-se um par determinístico. A
    verificação é feita em tempo constante com ``hmac.compare_digest`` para não
    vazar informação por diferença de tempo.
    """

    usuario: str
    senha: str

    def conferem(self, usuario: str, senha: str) -> bool:
        """Retorna ``True`` se usuário e senha informados conferem (tempo constante)."""
        usuario_ok = hmac.compare_digest(self.usuario, usuario)
        senha_ok = hmac.compare_digest(self.senha, senha)
        return usuario_ok and senha_ok


def autenticar_sns(
    usuario: str,
    senha: str,
    origem: str | None,
    *,
    controlador: ControladorAutenticacaoSns,
    credenciais: CredenciaisDashboardSns,
    origem_requisicao: str,
) -> dict[str, object]:
    """Avalia uma tentativa de login do Dashboard do SNS (Req. 12.4, 12.5, 12.6, 12.7).

    A ``origem`` efetiva é a informada no payload ou, na ausência, o host do cliente
    (``origem_requisicao``). As credenciais são verificadas pelo validador injetável
    e o desfecho (incluindo o bloqueio por origem após 5 falhas consecutivas por
    300 s) é determinado pelo :class:`ControladorAutenticacaoSns`.

    O resultado é serializado para o navegador de forma segura: usa
    :meth:`AvaliacaoAutenticacao.para_navegador` e, por garantia adicional, passa
    por :func:`sanear_para_navegador`, de modo que nenhuma credencial da AWS ou
    segredo trafegue ao cliente (Req. 12.4).

    Args:
        usuario: usuário informado no login.
        senha: senha informada no login.
        origem: origem informada no payload (ex.: IP); quando ``None``, usa o host
            do cliente da requisição.
        controlador: controlador de autenticação com bloqueio por origem.
        credenciais: validador de usuário/senha injetável.
        origem_requisicao: host do cliente da requisição (fallback de origem).

    Returns:
        Dicionário seguro para o navegador com o desfecho e o estado de bloqueio,
        sem qualquer credencial da AWS (Req. 12.4).
    """
    origem_efetiva = origem or origem_requisicao
    credenciais_validas = credenciais.conferem(usuario, senha)

    avaliacao: AvaliacaoAutenticacao = controlador.avaliar_tentativa(
        origem_efetiva, credenciais_validas
    )

    # Dupla proteção contra exposição de credenciais da AWS no navegador (Req. 12.4):
    # a representação já é segura, e sanear_para_navegador remove qualquer chave
    # sensível que porventura venha a ser incluída no futuro.
    return sanear_para_navegador(avaliacao.para_navegador())
