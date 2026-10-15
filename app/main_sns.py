"""Composição e ponto de entrada do laboratório Amazon SNS na EC2 (Tarefa 16.1).

Este módulo é o **entrypoint** do laboratório **AWS SNS Delivery Lab** executado na
instância EC2. Ele compõe, em um único processo, os três elementos descritos no
``design.md`` e no glossário do ``requirements.md`` (termo **Sistema**):

1. a **API_Backend** (FastAPI), criada por :func:`app.api.rotas_sns.criar_app_sns`,
   que registra todos os roteadores do laboratório (saúde, configuração,
   estatísticas, arquitetura, disparo Standard/FIFO, comparação, DLQ e autenticação)
   e injeta as dependências em ``app.state``;
2. o **Dashboard** estático (``web/sns/``), servido pela própria aplicação via
   ``starlette.staticfiles.StaticFiles`` na raiz (Req. 9.1 — a mesma aplicação que
   hospeda a API serve o Dashboard);
3. o **Verificador_Entrega**, que já é instanciado por :func:`criar_app_sns` dentro
   dos serviços de disparo/comparação/DLQ (``app.state.servico_*_sns``) e roda
   **somente sob demanda**, quando o usuário aciona manualmente um teste pelos
   endpoints — nunca em laço, carga ou agendamento automático (Req. 9.1, 9.2).

Regra central desta tarefa (Req. 1.9): a disponibilização do Dashboard é
**condicionada** à verificação de inicialização dos recursos AWS. Antes de servir o
Dashboard, :func:`compor_aplicacao_sns` executa a verificação de inicialização em
modo **não interruptivo** (para o endpoint ``GET /api/saude`` continuar respondendo)
e **só monta o Dashboard quando a verificação é bem-sucedida**. Se a verificação
falha, qualquer requisição ao conteúdo estático recebe uma resposta de
indisponibilidade (HTTP 503) com a **causa em pt-BR**, identificando o recurso
ausente/inacessível por nome e tipo. A API continua respondendo sob ``/api`` para
inspeção da causa.

Garantia de execução manual, sem automação (Req. 9.1, 9.2, 9.5, 9.6, 9.7):

- Diferentemente do laboratório SQS (``app/main.py``), este entrypoint **não** inicia
  nenhuma *thread* de segundo plano, *scheduler*, laço de teste, teste de carga ou
  publicação repetitiva automática. Não há ``@app.on_event("startup")`` que suba
  processos de fundo.
- Cada teste (disparo, comparação, DLQ) roda **apenas** quando o usuário aciona o
  endpoint correspondente; o Verificador_Entrega é invocado por esse acionamento e
  respeita o Timeout_Verificacao, sem repetir automaticamente (Req. 9.5, 9.6, 9.7).

Credenciais (Req. 12.1, 12.2): a aplicação resolve as credenciais exclusivamente pela
**IAM_Role_EC2** através da cadeia de provedores padrão do boto3. Nenhuma Access Key
(``aws_access_key_id``/``aws_secret_access_key``) é fixada em código, configuração ou
variáveis de ambiente.

Isolamento do laboratório SQS: este módulo **não** importa nem altera ``app/main.py``
(entrypoint do laboratório SQS). Ele reutiliza apenas a fábrica ``criar_app_sns`` e
serve o Dashboard dedicado em ``web/sns/``.

Como iniciar a aplicação (resumo; detalhes em ``IMPLANTACAO.md``)::

    uvicorn app.main_sns:app --host 0.0.0.0 --port 8000

O objeto ``app`` deste módulo é a instância FastAPI composta e pronta para servir.

Referências de requisitos: 1.9, 9.1, 9.2, 9.5, 9.6, 9.7, 12.1, 12.2.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from app.api.rotas_sns import criar_app_sns
from app.api.servico_autenticacao_sns import CredenciaisDashboardSns
from app.seguranca.autenticacao_sns import ControladorAutenticacaoSns
from app.verificacao_inicializacao_sns import (
    RelatorioInicializacao,
    VerificacaoInicializacaoSns,
)

# ---------------------------------------------------------------------------
# Variáveis de ambiente que configuram o entrypoint em produção (EC2)
# ---------------------------------------------------------------------------
# Nenhum segredo fica no código: os valores vêm do ambiente (ex.: ``Environment=``
# de uma unit systemd) e NUNCA de Access Keys da AWS (Req. 12.1, 12.2).
ENV_ORIGENS_AUTORIZADAS: str = "DASHBOARD_SNS_ORIGENS_AUTORIZADAS"
ENV_LIBERAR_TODAS_ORIGENS: str = "DASHBOARD_SNS_LIBERAR_TODAS_ORIGENS"
ENV_USUARIO: str = "DASHBOARD_SNS_USUARIO"
ENV_SENHA: str = "DASHBOARD_SNS_SENHA"
ENV_NOME_IAM_ROLE: str = "SNS_LAB_IAM_ROLE"
ENV_ID_INSTANCIA_EC2: str = "SNS_LAB_EC2_INSTANCE_ID"

# Nome padrão da IAM_Role_EC2 do laboratório, usado quando a env não é definida.
NOME_IAM_ROLE_PADRAO: str = "delivery-sns-ec2-role"

# Credenciais de laboratório usadas apenas quando as envs não são definidas, para
# não quebrar o uso local. Em produção, defina DASHBOARD_SNS_USUARIO/SENHA.
USUARIO_PADRAO_LABORATORIO: str = "admin"
SENHA_PADRAO_LABORATORIO: str = "trocar-no-console"

# Diretório do Dashboard estático do laboratório SNS (``web/sns/``), relativo à raiz
# do projeto. Mantido configurável para testes e para implantações alternativas.
_RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRETORIO_DASHBOARD_SNS_PADRAO: str = os.path.join(_RAIZ_PROJETO, "web", "sns")


# ---------------------------------------------------------------------------
# Montagem do Dashboard estático condicionada à verificação (Req. 1.9)
# ---------------------------------------------------------------------------
def _montar_dashboard_disponivel(app: FastAPI, diretorio_dashboard: str) -> None:
    """Serve o Dashboard estático de ``diretorio_dashboard`` na raiz (Req. 9.1).

    Usa ``StaticFiles`` com ``html=True`` para que ``/`` sirva ``index.html`` e os
    demais arquivos (CSS/JS) sejam servidos pelos seus caminhos. O *mount* é feito na
    raiz **após** os roteadores ``/api/*`` já registrados por ``criar_app_sns``, de
    modo que a API tem precedência sobre o conteúdo estático.
    """
    app.mount(
        "/",
        StaticFiles(directory=diretorio_dashboard, html=True),
        name="dashboard-sns",
    )


def _montar_dashboard_indisponivel(
    app: FastAPI, resultado: RelatorioInicializacao
) -> None:
    """Impede a disponibilização do Dashboard e expõe a causa em pt-BR (Req. 1.9).

    Quando a verificação de inicialização falha, o Dashboard **não** fica disponível:
    toda requisição que não seja de ``/api/*`` recebe HTTP 503 com uma mensagem em
    pt-BR que identifica o recurso indisponível por nome e tipo. O endpoint
    ``GET /api/saude`` continua respondendo (com ``saudavel=False``) para inspeção da
    causa, pois os roteadores da API foram registrados antes deste *fallback*.
    """

    @app.get("/", include_in_schema=False)
    @app.get("/{caminho:path}", include_in_schema=False)
    def dashboard_indisponivel(request: Request, caminho: str = "") -> JSONResponse:
        # Deixa a API responder normalmente; apenas o conteúdo estático é bloqueado.
        if request.url.path.startswith("/api"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Rota de API não encontrada."},
            )
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "O Dashboard está indisponível porque a verificação de "
                    "inicialização dos recursos AWS falhou. "
                    + resultado.mensagem_pt_br
                ),
                "recurso_indisponivel": (
                    {
                        "nome": resultado.recurso_indisponivel.nome,
                        "tipo": resultado.recurso_indisponivel.tipo.value,
                    }
                    if resultado.recurso_indisponivel is not None
                    else None
                ),
            },
        )


# ---------------------------------------------------------------------------
# Configuração de autenticação a partir de variáveis de ambiente (Req. 12.5, 12.7)
# ---------------------------------------------------------------------------
def _str_para_booleano(valor: Optional[str]) -> bool:
    """Interpreta uma env textual como booleano (``"true"``/``"1"`` → ``True``)."""
    if valor is None:
        return False
    return valor.strip().lower() in {"true", "1", "sim", "yes"}


def _construir_controlador_autenticacao(
    ambiente: dict[str, str],
    *,
    emitir_aviso: Callable[[str], None],
) -> ControladorAutenticacaoSns:
    """Constrói o :class:`ControladorAutenticacaoSns` a partir do ambiente (Req. 12.7).

    Regras de configuração:

    - Se ``DASHBOARD_SNS_ORIGENS_AUTORIZADAS`` contém uma lista separada por
      vírgulas, cada origem (IP) é autorizada explicitamente.
    - Se o valor for ``"*"`` ou ``DASHBOARD_SNS_LIBERAR_TODAS_ORIGENS`` for verdadeiro,
      ativa o modo laboratório aberto (``permitir_todas_origens=True``).
    - Se nenhuma origem é configurada e a liberação total não é solicitada, registra
      um aviso em pt-BR explicando que o login ficará bloqueado até configurar as
      envs. Não libera todas as origens silenciosamente (seria inseguro).
    """
    valor_origens = (ambiente.get(ENV_ORIGENS_AUTORIZADAS) or "").strip()
    liberar_todas_flag = _str_para_booleano(ambiente.get(ENV_LIBERAR_TODAS_ORIGENS))
    liberar_todas = liberar_todas_flag or valor_origens == "*"

    if liberar_todas:
        return ControladorAutenticacaoSns(permitir_todas_origens=True)

    origens = [
        origem.strip() for origem in valor_origens.split(",") if origem.strip()
    ]

    if not origens:
        emitir_aviso(
            "Aviso de segurança: nenhuma origem foi autorizada para o Dashboard do "
            "laboratório SNS. O login ficará bloqueado até configurar a variável de "
            f"ambiente '{ENV_ORIGENS_AUTORIZADAS}' (lista de IPs separados por "
            f"vírgula) ou '{ENV_LIBERAR_TODAS_ORIGENS}=true' (modo laboratório aberto)."
        )

    return ControladorAutenticacaoSns(origens)


def _construir_credenciais_dashboard(ambiente: dict[str, str]) -> CredenciaisDashboardSns:
    """Monta as :class:`CredenciaisDashboardSns` a partir do ambiente (Req. 12.5).

    Usa ``DASHBOARD_SNS_USUARIO``/``DASHBOARD_SNS_SENHA`` quando definidas; caso
    contrário, mantém o par de laboratório padrão para não quebrar o uso local.
    Nenhum segredo é fixado no código em produção: os valores vêm do ambiente, nunca
    de Access Keys da AWS (Req. 12.2).
    """
    usuario = ambiente.get(ENV_USUARIO) or USUARIO_PADRAO_LABORATORIO
    senha = ambiente.get(ENV_SENHA) or SENHA_PADRAO_LABORATORIO
    return CredenciaisDashboardSns(usuario=usuario, senha=senha)


# ---------------------------------------------------------------------------
# Composição da aplicação do laboratório SNS
# ---------------------------------------------------------------------------
def compor_aplicacao_sns(
    *,
    verificador_inicializacao_sns: Optional[VerificacaoInicializacaoSns] = None,
    diretorio_dashboard: str = DIRETORIO_DASHBOARD_SNS_PADRAO,
    ambiente: Optional[dict[str, str]] = None,
    **kwargs: Any,
) -> FastAPI:
    """Compõe a aplicação completa do laboratório SNS (API + Dashboard + Verificador).

    Fluxo da composição:

    1. Resolve a configuração de autenticação (origens autorizadas e credenciais do
       Dashboard) a partir do ambiente, quando o chamador não as injeta. Em produção,
       isso permite o login com origens autorizadas via env, sem segredos no código
       (Req. 12.5, 12.7).
    2. Cria a **API_Backend** com :func:`app.api.rotas_sns.criar_app_sns`, que
       registra todos os roteadores e instancia o **Verificador_Entrega** dentro dos
       serviços de disparo/comparação/DLQ. Em produção, os componentes boto3 são
       criados com credenciais pela IAM_Role_EC2 (sem Access Keys — Req. 12.1, 12.2).
    3. Executa a **verificação de inicialização** dos recursos AWS em modo **não
       interruptivo** (Req. 1.9). O resultado fica em
       ``app.state.resultado_verificacao_sns``.
    4. Se a verificação **tiver sucesso**: serve o Dashboard estático de ``web/sns/``
       (Req. 9.1). Se **falhar**: não serve o Dashboard — expõe a causa em pt-BR
       (HTTP 503) — mantendo a API respondendo sob ``/api`` (Req. 1.9).

    Importante — **sem automação de testes** (Req. 9.1, 9.2, 9.5, 9.6, 9.7): esta
    composição **não** inicia nenhuma *thread*, *scheduler*, laço ou carga. Nenhum
    teste roda sozinho; o Verificador_Entrega só é invocado pelo acionamento manual
    dos endpoints de disparo, comparação e DLQ.

    Args:
        verificador_inicializacao_sns: verificador de inicialização injetável; em
            testes, injete um com clientes boto3 simulados para controlar o resultado
            da verificação sem AWS real. Quando ``None``, ``criar_app_sns`` cria o
            verificador real (requer ``nome_iam_role``/``id_instancia_ec2`` resolvidos
            do ambiente). A mesma instância é usada tanto para o *gate* do Dashboard
            quanto pelo endpoint ``GET /api/saude``.
        diretorio_dashboard: caminho do Dashboard estático (padrão: ``web/sns/``).
        ambiente: mapa de variáveis de ambiente usado para resolver autenticação e
            identificadores (IAM Role, instância EC2). Quando ``None``, usa
            ``os.environ``. Útil para testes determinísticos.
        **kwargs: repassados a :func:`criar_app_sns` (ex.: ``estado_simulacao_sns``,
            ``sns_gateway``, ``verificador_entrega_sns``, resolvedores de ARN/URL,
            ``controlador_autenticacao_sns``, ``credenciais_dashboard_sns``).

    Returns:
        A instância :class:`FastAPI` composta, com o resultado da verificação em
        ``app.state.resultado_verificacao_sns``.
    """
    ambiente = dict(os.environ) if ambiente is None else dict(ambiente)

    # Passo 1: configura a autenticação a partir do ambiente quando não injetada.
    # A injeção explícita por kwargs tem precedência e não é sobrescrita.
    if "controlador_autenticacao_sns" not in kwargs:
        kwargs["controlador_autenticacao_sns"] = _construir_controlador_autenticacao(
            ambiente,
            emitir_aviso=lambda mensagem: print(mensagem, file=sys.stderr),
        )
    if "credenciais_dashboard_sns" not in kwargs:
        kwargs["credenciais_dashboard_sns"] = _construir_credenciais_dashboard(ambiente)

    # Identificadores da IAM Role e da instância EC2 usados pelo verificador real
    # (apenas quando o chamador não injeta um verificador). Resolvidos do ambiente,
    # sem segredos no código.
    if verificador_inicializacao_sns is not None:
        kwargs["verificador_inicializacao_sns"] = verificador_inicializacao_sns
    else:
        kwargs.setdefault(
            "nome_iam_role", ambiente.get(ENV_NOME_IAM_ROLE) or NOME_IAM_ROLE_PADRAO
        )
        kwargs.setdefault("id_instancia_ec2", ambiente.get(ENV_ID_INSTANCIA_EC2) or "")

    # Passo 2: cria a API_Backend com todos os roteadores e o Verificador_Entrega
    # já instanciado nos serviços injetados em app.state.
    app = criar_app_sns(**kwargs)

    # Dependência efetiva resolvida por criar_app_sns (real em produção; o fake
    # injetado em testes). É a MESMA instância usada por GET /api/saude.
    verificador_efetivo: VerificacaoInicializacaoSns = (
        app.state.verificador_inicializacao_sns
    )

    # Passo 3: verificação de inicialização em modo não interruptivo (Req. 1.9).
    resultado = verificador_efetivo.verificar_recursos(interromper_em_falha=False)
    app.state.resultado_verificacao_sns = resultado

    # Passo 4: o Dashboard só é disponibilizado quando a verificação tem sucesso.
    if not resultado.sucesso:
        _montar_dashboard_indisponivel(app, resultado)
        return app

    # O mount dos estáticos vem por último, para a API ter precedência sobre ``/``.
    _montar_dashboard_disponivel(app, diretorio_dashboard)
    return app


def criar_app_padrao() -> FastAPI:
    """Cria a aplicação padrão (produção) para servir via servidor ASGI.

    As dependências ficam como ``None`` e são criadas por ``criar_app_sns`` com
    credenciais pela IAM_Role_EC2 (sem Access Keys — Req. 12.1, 12.2). Use esta
    fábrica com o modo *factory* do servidor ASGI, ou acesse o atributo ``app`` deste
    módulo (resolvido sob demanda — ver :func:`__getattr__`).
    """
    return compor_aplicacao_sns()


def __getattr__(nome: str) -> FastAPI:
    """Resolve ``app.main_sns.app`` sob demanda (PEP 562), sem avaliar no import.

    Permite iniciar com ``uvicorn app.main_sns:app`` enquanto mantém o import do
    módulo livre de efeitos colaterais: a aplicação padrão (que cria clientes boto3
    reais) só é construída quando o servidor ASGI realmente acessa o atributo
    ``app``. Assim, os testes podem importar :func:`compor_aplicacao_sns` e injetar
    fakes sem acionar a AWS.
    """
    if nome == "app":
        aplicacao = criar_app_padrao()
        globals()["app"] = aplicacao  # memoiza para acessos subsequentes.
        return aplicacao
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
