"""Endpoints de saúde, configuração, estatísticas e arquitetura do laboratório SNS.

Este módulo expõe :class:`fastapi.APIRouter` **dedicados ao laboratório Amazon
SNS**, com prefixo ``/api``, para não colidir com as rotas do laboratório SQS já
servidas por :func:`app.api.app.create_app`. A Tarefa 12.1 implementou os
endpoints de saúde e configuração; a Tarefa 12.2 adiciona ``GET /api/estatisticas``
e ``GET /api/arquitetura``. O contrato segue o ``design.md`` (seção
"API_Backend (FastAPI)"):

- ``GET /api/saude`` — verificação de inicialização dos recursos AWS, reutilizando
  :class:`app.verificacao_inicializacao_sns.VerificacaoInicializacaoSns` em modo
  **não interruptivo**, para sempre responder (com ``saudavel=False`` quando algum
  recurso está indisponível), preservando o erro original da AWS (Req. 1.9, 1.11).
- ``GET /api/config`` — retorna **Config_Aplicada** e **Config_Simulacao** com
  rótulos textuais **distintos**, além da orientação em pt-BR de que a
  Config_Aplicada só muda no Console AWS (Req. 2.1-2.9).
- ``PUT /api/config/simulacao`` — ajusta o **Timeout_Verificacao_Entrega** e o
  **Timeout_Verificacao_DLQ** dentro das faixas, reutilizando o validador de faixa
  do SNS; ao rejeitar, preserva o valor anterior e informa a faixa válida em pt-BR
  (Req. 2.5, 2.7, 2.8).
- ``GET /api/estatisticas`` — agrega as estatísticas **por cenário** (publicadas
  por tópico, Entrega_Confirmada por fila, presentes por DLQ e o horário da última
  atualização bem-sucedida), reutilizando o agregador puro
  (:mod:`app.observabilidade.agregador_estatisticas_sns`). Aplica um **timeout de
  3s**: ao exceder, retorna indicação de timeout e **preserva os últimos dados
  válidos**, mantendo inalterado o horário do último sucesso (Req. 3.4-3.10, 14.1,
  14.3, 3.9).
- ``GET /api/arquitetura`` — devolve os dados da **representação visual** da
  arquitetura: os dois tópicos com tipo, as seis assinaturas, as seis filas de
  destino e as duas DLQs, derivados das constantes do laboratório (Req. 3.1, 3.2).

Decisões de design relevantes:

- **Isolamento do laboratório SQS.** Nada aqui importa ou altera o ``app/main.py``
  nem o ``app/api/app.py`` do laboratório SQS. Os esquemas Pydantic são definidos
  localmente com o sufixo ``Sns`` e as dependências vêm das constantes/validadores
  ``*_sns``.
- **Injeção de dependências via fábrica.** :func:`criar_app_sns` constrói a
  instância FastAPI e injeta o estado de simulação e o verificador de inicialização
  em ``app.state``. Em produção, cria o verificador boto3 real (credenciais pela
  IAM Role da EC2, sem Access Keys — Req. 12.1, 12.2). Em testes, injeta um
  verificador simulado para não depender da AWS real.
- **pt-BR em todas as mensagens ao usuário.** Mensagens, rótulos e descrições são
  em português do Brasil; nomes técnicos permanecem em inglês quando apropriado.

Referências de requisitos: 1.9, 1.11, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9,
3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 12.1, 12.2, 13.5, 14.1, 14.3.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Iterable, Optional

import boto3
from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field

from app.acesso.sns_gateway import SnsGateway
from app.acesso.sqs_leitura_gateway_sns import SqsLeituraGateway
from app.api.estado_estatisticas_sns import (
    EstadoEstatisticasSns,
    ResultadoEstatisticasSns,
)
from app.api.estado_simulacao_sns import EstadoConfigSimulacaoSns
from app.api.estado_testes_sns import (
    TESTE_COMPARAR,
    TESTE_DISPARAR_FIFO,
    TESTE_DISPARAR_STANDARD,
    TESTE_DLQ,
    EstadoTestesSns,
)
from app.api.servico_autenticacao_sns import (
    CredenciaisDashboardSns,
    autenticar_sns,
)
from app.api.servico_comparacao_sns import (
    ResultadoComparacao,
    ServicoComparacaoSns,
)
from app.api.servico_disparo_sns import ResultadoDisparo, ServicoDisparoSns
from app.api.servico_dlq_sns import (
    ResultadoDlq,
    SelecaoAssinaturaInvalida,
    ServicoDlqSns,
    TEXTO_EXPLICATIVO_DLQ,
)
from app.acesso.gerenciador_falha_controlada_sns import GerenciadorFalhaControlada
from app.api.verificador_entrega_sns import VerificadorEntrega
from app.dominio import constantes_sns as c
from app.dominio.tipos_sns import Cenario
from app.dominio.validacao_faixa_sns import ResultadoValidacaoFaixa
from app.observabilidade.agregador_estatisticas_sns import (
    EstatisticasCenario,
    EstatisticasSns,
)
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns
from app.seguranca.autenticacao_sns import ControladorAutenticacaoSns
from app.verificacao_inicializacao_sns import VerificacaoInicializacaoSns

# ---------------------------------------------------------------------------
# Rótulos distintos de Config_Aplicada e Config_Simulacao (Req. 2.6)
# ---------------------------------------------------------------------------
# O Dashboard usa estes rótulos textuais para distinguir, em cada parâmetro, o que
# é comportamento real da AWS (Config_Aplicada) do que é lógica da aplicação
# (Config_Simulacao).
ROTULO_CONFIG_APLICADA: str = "Config_Aplicada"
ROTULO_CONFIG_SIMULACAO: str = "Config_Simulacao"

# Orientação em pt-BR exibida sempre que o usuário consulta a configuração ou tenta
# ajustar um parâmetro de Config_Aplicada: ela só muda no Console AWS (Req. 2.9).
ORIENTACAO_CONFIG_APLICADA: str = (
    "Os parâmetros de Config_Aplicada refletem o que está configurado nos recursos "
    "SNS e SQS (tipo do tópico, Redrive_Policy_SNS das assinaturas, "
    "Deduplicacao_Por_Conteudo e Access_Policy_Fila) e só podem ser alterados "
    f"manualmente no Console AWS (região {c.REGIAO_AWS}). A aplicação não cria, "
    "modifica nem exclui recursos AWS."
)


# ---------------------------------------------------------------------------
# Esquemas Pydantic (dedicados ao laboratório SNS)
# ---------------------------------------------------------------------------
class RecursoSaudeSns(BaseModel):
    """Status de um recurso AWS individual na verificação de inicialização."""

    nome: str = Field(..., description="Nome do recurso (ex.: delivery-standard).")
    tipo: str = Field(..., description="Tipo do recurso em pt-BR (ex.: tópico SNS).")
    disponivel: bool = Field(
        ..., description="True se o recurso existe e está acessível."
    )
    detalhe_erro: Optional[str] = Field(
        None,
        description="Erro original da AWS quando o recurso está indisponível.",
    )


class RespostaSaudeSns(BaseModel):
    """Resposta de ``GET /api/saude`` (verificação de inicialização, Req. 1.9, 1.11)."""

    saudavel: bool = Field(
        ..., description="True somente se todos os recursos estão disponíveis."
    )
    mensagem: str = Field(..., description="Mensagem em pt-BR pronta para o Dashboard.")
    recursos: list[RecursoSaudeSns] = Field(
        default_factory=list,
        description="Status de cada recurso checado, na ordem de verificação.",
    )


class ParametroConfigSns(BaseModel):
    """Um parâmetro de configuração com rótulo distinto Config_Aplicada/Simulacao."""

    nome: str = Field(..., description="Nome do parâmetro em pt-BR.")
    valor: Any = Field(..., description="Valor atual do parâmetro.")
    unidade: Optional[str] = Field(
        None, description="Unidade do valor quando aplicável (ex.: segundos)."
    )
    rotulo: str = Field(
        ...,
        description="Rótulo distinto: 'Config_Aplicada' ou 'Config_Simulacao'.",
    )
    ajustavel: bool = Field(
        ..., description="True para Config_Simulacao; False para Config_Aplicada."
    )
    faixa_minima: Optional[int] = Field(
        None, description="Limite inferior da faixa, quando ajustável."
    )
    faixa_maxima: Optional[int] = Field(
        None, description="Limite superior da faixa, quando ajustável."
    )
    orientacao: Optional[str] = Field(
        None,
        description=(
            "Orientação em pt-BR; nos parâmetros de Config_Aplicada indica que a "
            "mudança só ocorre no Console AWS."
        ),
    )


class RespostaConfigSns(BaseModel):
    """Resposta de ``GET /api/config`` (Config_Aplicada e Config_Simulacao, Req. 2.1-2.9)."""

    config_aplicada: list[ParametroConfigSns] = Field(default_factory=list)
    config_simulacao: list[ParametroConfigSns] = Field(default_factory=list)
    orientacao_config_aplicada: str = Field(
        ...,
        description="Orientação em pt-BR de que a Config_Aplicada só muda no Console AWS.",
    )


class AjusteConfigSimulacaoSns(BaseModel):
    """Corpo de ``PUT /api/config/simulacao``: parâmetros a ajustar (Req. 2.5, 2.8).

    Todos opcionais; parâmetros não informados não são alterados. Os valores são
    recebidos como opcionais e validados pelas faixas do SNS, de modo que valores
    fora da faixa sejam rejeitados com a faixa válida (sem levantar erro HTTP).
    """

    timeout_verificacao_entrega_segundos: Optional[int] = Field(
        None,
        description="Novo Timeout_Verificacao_Entrega em segundos (faixa 5 a 120).",
    )
    timeout_verificacao_dlq_segundos: Optional[int] = Field(
        None,
        description="Novo Timeout_Verificacao_DLQ em segundos (faixa 30 a 300).",
    )


class ResultadoAjusteParametroSns(BaseModel):
    """Resultado do ajuste de um único parâmetro de Config_Simulacao."""

    parametro: str = Field(..., description="Nome do parâmetro ajustado.")
    aceito: bool = Field(..., description="True se o valor informado foi aceito.")
    valor_efetivo: int = Field(
        ...,
        description="Valor que passa a valer (novo se aceito, anterior se rejeitado).",
    )
    mensagem: str = Field(
        ...,
        description="Mensagem em pt-BR; vazia se aceito, com a faixa válida se rejeitado.",
    )


class RespostaAjusteConfigSimulacaoSns(BaseModel):
    """Resposta de ``PUT /api/config/simulacao`` com o desfecho de cada ajuste."""

    ajustes: list[ResultadoAjusteParametroSns] = Field(default_factory=list)
    config_simulacao: list[ParametroConfigSns] = Field(
        default_factory=list,
        description="Snapshot da Config_Simulacao após aplicar os ajustes aceitos.",
    )


# ---------------------------------------------------------------------------
# Esquemas Pydantic — estatísticas da visão geral (Tarefa 12.2)
# ---------------------------------------------------------------------------
class ContadorRecursoSns(BaseModel):
    """Contador inteiro ≥ 0 associado a um recurso identificado por nome (Req. 3.4-3.6)."""

    nome: str = Field(..., description="Nome do recurso (tópico, fila de destino ou DLQ).")
    valor: int = Field(
        ..., ge=0, description="Valor inteiro maior ou igual a 0 (0 quando ausente)."
    )


class EstatisticasCenarioSns(BaseModel):
    """Estatísticas de um cenário (Standard ou FIFO) com os três contadores (Req. 3.4-3.7)."""

    cenario: str = Field(..., description="Cenário: 'standard' ou 'fifo'.")
    rotulo: str = Field(
        ..., description="Rótulo distinto do conjunto exibido no Dashboard (Req. 3.7)."
    )
    publicadas_por_topico: list[ContadorRecursoSns] = Field(
        default_factory=list,
        description="Total publicado por tópico, identificando cada tópico (Req. 3.4).",
    )
    confirmadas_por_fila: list[ContadorRecursoSns] = Field(
        default_factory=list,
        description=(
            "Entrega_Confirmada por fila de destino, identificando cada fila (Req. 3.5)."
        ),
    )
    presentes_por_dlq: list[ContadorRecursoSns] = Field(
        default_factory=list,
        description="Mensagens presentes por DLQ, identificando cada DLQ (Req. 3.6).",
    )


class RespostaEstatisticasSns(BaseModel):
    """Resposta de ``GET /api/estatisticas`` (agregado por cenário com timeout, Req. 3.4-3.10, 14.3)."""

    standard: Optional[EstatisticasCenarioSns] = Field(
        None, description="Conjunto de estatísticas do cenário Standard (Req. 3.7)."
    )
    fifo: Optional[EstatisticasCenarioSns] = Field(
        None, description="Conjunto de estatísticas do cenário FIFO (Req. 3.7)."
    )
    ultima_atualizacao: Optional[str] = Field(
        None,
        description=(
            "Horário da última atualização bem-sucedida em ISO 8601, com data, hora "
            "(incluindo segundos) e fuso horário (Req. 3.8). Em timeout, mantém o "
            "horário do último sucesso (Req. 3.9)."
        ),
    )
    timeout: bool = Field(
        False,
        description=(
            "True quando a atualização excedeu o tempo limite e os dados devolvidos "
            "são os últimos válidos preservados (Req. 14.3, 3.9)."
        ),
    )
    mensagem: str = Field(
        "",
        description=(
            "Mensagem em pt-BR; vazia em sucesso e, em timeout, indicando que os "
            "dados podem estar desatualizados (Req. 3.9)."
        ),
    )


# ---------------------------------------------------------------------------
# Esquemas Pydantic — representação da arquitetura (Tarefa 12.2)
# ---------------------------------------------------------------------------
class AssinaturaArquiteturaSns(BaseModel):
    """Uma das seis Assinatura_SNS da representação visual (tópico → fila de destino)."""

    topico: str = Field(..., description="Tópico de origem da assinatura.")
    fila_destino: str = Field(..., description="Fila de destino assinante do tópico.")
    protocolo: str = Field("sqs", description="Protocolo da assinatura (SQS).")


class TopicoArquiteturaSns(BaseModel):
    """Um dos dois tópicos SNS da representação visual, com tipo textual (Req. 3.1, 3.2)."""

    nome: str = Field(..., description="Nome do tópico SNS.")
    tipo: str = Field(..., description="Tipo textual distinto: 'Standard' ou 'FIFO' (Req. 3.2).")
    dlq_compativel: str = Field(
        ..., description="DLQ do SNS compatível com o tipo do tópico (Redrive_Policy_SNS)."
    )


class RecursoArquiteturaSns(BaseModel):
    """Fila de destino ou DLQ na representação visual, identificada por nome e tipo."""

    nome: str = Field(..., description="Nome do recurso SQS.")
    tipo: str = Field(..., description="Tipo textual: 'Standard' ou 'FIFO'.")


class RespostaArquiteturaSns(BaseModel):
    """Resposta de ``GET /api/arquitetura`` (dados da representação visual, Req. 3.1, 3.2).

    Contém os dois tópicos (com tipo), as seis assinaturas, as seis filas de
    destino e as duas DLQs que o Dashboard desenha na visão geral.
    """

    topicos: list[TopicoArquiteturaSns] = Field(default_factory=list)
    assinaturas: list[AssinaturaArquiteturaSns] = Field(default_factory=list)
    filas_destino: list[RecursoArquiteturaSns] = Field(default_factory=list)
    dlqs: list[RecursoArquiteturaSns] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Esquemas Pydantic — disparo Standard e FIFO (Tarefa 13.1)
# ---------------------------------------------------------------------------
class DisparoStandardSns(BaseModel):
    """Corpo de ``POST /api/disparar/standard`` (Req. 4.1).

    O ID_Pedido é recebido como string e validado pela regra de domínio
    (:func:`app.dominio.validacao_disparo.validar_disparo`), e não pelo Pydantic,
    para produzir mensagens em pt-BR por campo e preservar o valor informado em
    caso de rejeição (Req. 4.7).
    """

    id_pedido: str = Field(
        ..., description="ID_Pedido da publicação (1 a 80 caracteres)."
    )


class DisparoFifoSns(BaseModel):
    """Corpo de ``POST /api/disparar/fifo`` (Req. 5.1, 5.2).

    O MessageDeduplicationId **não** é solicitado: a Deduplicacao_Por_Conteudo do
    Topico_FIFO está habilitada por padrão, de modo que o SNS o deriva do conteúdo
    (Req. 5.4, 11.3). Os valores são validados pela regra de domínio.
    """

    id_pedido: str = Field(
        ..., description="ID_Pedido da publicação (1 a 80 caracteres)."
    )
    message_group_id: Optional[str] = Field(
        None, description="MessageGroupId da publicação FIFO (1 a 128 caracteres)."
    )


class DestinoDisparoSns(BaseModel):
    """Resultado da verificação de entrega em uma fila de destino (Req. 4.4, 5.7, 6.3)."""

    destino: str = Field(..., description="Identificador do destino (destino_1..3).")
    titulo_destino: str = Field(..., description="Título descritivo do destino (pt-BR).")
    fila_destino: str = Field(..., description="Nome da fila de destino verificada.")
    estado: str = Field(
        ..., description="Estado derivado: 'Entrega_Confirmada' ou 'Não confirmado'."
    )
    confirmada: bool = Field(
        ..., description="True se houve leitura real correlacionada pelo ID_Pedido."
    )
    message_id: Optional[str] = Field(
        None, description="MessageId lido na fila, quando a entrega é confirmada."
    )


class RespostaDisparoSns(BaseModel):
    """Resposta dos endpoints de disparo Standard/FIFO (Req. 4.4-4.8, 5.6-5.10).

    Em sucesso, traz tópico, tipo, ID_Pedido, (MessageGroupId no FIFO), MessageId,
    os três destinos e a notificação visual. Em rejeição de validação ou falha de
    publicação, traz as mensagens em pt-BR e preserva os valores informados.
    """

    aceito: bool = Field(
        ..., description="True quando o payload foi aceito e a publicação ocorreu."
    )
    cenario: str = Field(..., description="Cenário do disparo: 'standard' ou 'fifo'.")
    id_pedido: str = Field(..., description="ID_Pedido informado (preservado).")
    topico: Optional[str] = Field(None, description="Tópico utilizado na publicação.")
    tipo: Optional[str] = Field(None, description="Tipo do tópico: 'Standard' ou 'FIFO'.")
    message_group_id: Optional[str] = Field(
        None, description="MessageGroupId informado (apenas FIFO)."
    )
    message_id: Optional[str] = Field(
        None, description="MessageId retornado pelo SNS (Entrega_Publicada)."
    )
    destinos: list[DestinoDisparoSns] = Field(
        default_factory=list,
        description="Resultado da verificação nas três filas de destino.",
    )
    notificacao_visual: str = Field(
        "",
        description=(
            "Texto da notificação APENAS visual; o laboratório não envia SMS nem "
            "e-mail reais (Req. 4.5, 4.6, 5.8)."
        ),
    )
    falha_publicacao: bool = Field(
        False, description="True quando a publicação foi tentada mas falhou (Req. 4.8)."
    )
    campos_invalidos: list[str] = Field(
        default_factory=list,
        description="Campos reprovados na validação (vazio quando aceito).",
    )
    mensagens: dict[str, str] = Field(
        default_factory=dict,
        description="Mensagens em pt-BR por campo inválido (validação).",
    )
    mensagem: str = Field(
        "", description="Mensagem geral em pt-BR (sucesso, rejeição ou falha)."
    )
    erro_original: Optional[str] = Field(
        None, description="Erro original da AWS em falha de publicação (Req. 4.8)."
    )


# ---------------------------------------------------------------------------
# Esquemas Pydantic — comparação Standard x FIFO (Tarefa 13.2)
# ---------------------------------------------------------------------------
class CompararSns(BaseModel):
    """Corpo de ``POST /api/comparar`` (Req. 7.1-7.3).

    O ID_Pedido correlaciona as três mensagens em ambos os cenários. O
    MessageGroupId do teste FIFO é opcional: quando ausente, o serviço deriva um
    valor estável a partir do ID_Pedido; em todo caso, o teste FIFO usa um
    **único** MessageGroupId para as três mensagens (Req. 7.3).
    """

    id_pedido: str = Field(
        ..., description="ID_Pedido usado para correlacionar as três mensagens."
    )
    message_group_id: Optional[str] = Field(
        None,
        description=(
            "MessageGroupId único do teste FIFO; quando ausente, é derivado do "
            "ID_Pedido."
        ),
    )


class MensagemComparacaoSns(BaseModel):
    """Uma das três mensagens publicadas em um teste de comparação (Req. 7.4)."""

    sequencia: int = Field(..., ge=1, description="Ordem de publicação (1, 2, 3).")
    conteudo: str = Field(..., description="Conteúdo da mensagem publicada.")
    message_id: str = Field(..., description="MessageId retornado pelo SNS.")


class ItemRecebimentoSns(BaseModel):
    """Uma mensagem observada na ordem de recebimento de um teste (Req. 7.4, 7.9)."""

    conteudo: Optional[str] = Field(
        None, description="Conteúdo lido na fila; nulo quando 'Não confirmado'."
    )
    message_id: Optional[str] = Field(
        None, description="MessageId lido na fila, quando confirmada."
    )
    estado: str = Field(
        ...,
        description="Estado: 'Entrega_Confirmada' ou 'Não confirmado' (Req. 7.9).",
    )
    confirmada: bool = Field(
        ..., description="True se houve leitura real correlacionada pelo ID_Pedido."
    )


class ResultadoTesteComparacaoSns(BaseModel):
    """Resultado de um dos dois testes independentes (Standard ou FIFO) (Req. 7.4)."""

    cenario: str = Field(..., description="Cenário: 'standard' ou 'fifo'.")
    tipo: str = Field(..., description="Tipo textual do tópico: 'Standard' ou 'FIFO'.")
    topico: str = Field(..., description="Nome do tópico utilizado.")
    id_pedido: str = Field(..., description="ID_Pedido correlacionado neste teste.")
    message_group_id: Optional[str] = Field(
        None, description="MessageGroupId único do teste (apenas FIFO)."
    )
    ordem_publicacao: list[MensagemComparacaoSns] = Field(
        default_factory=list,
        description="As três mensagens na ordem de publicação (Req. 7.4).",
    )
    ordem_recebimento: list[ItemRecebimentoSns] = Field(
        default_factory=list,
        description=(
            "Ordem de recebimento observada por leitura real, sem reordenar; "
            "posições não confirmadas aparecem como 'Não confirmado' (Req. 7.4, "
            "7.7, 7.9)."
        ),
    )


class RespostaCompararSns(BaseModel):
    """Resposta de ``POST /api/comparar`` (dois testes lado a lado, Req. 7.5, 7.6, 7.8).

    Em sucesso, traz os resultados Standard e FIFO lado a lado e o texto
    explicativo em pt-BR sobre a ausência de garantia de ordenação no Standard. Em
    interrupção (tópico indisponível ou falha de autenticação), traz a causa em
    pt-BR e o erro original, com ``interrompido=True`` (Req. 7.8).
    """

    concluido: bool = Field(
        ..., description="True quando os dois testes rodaram sem interrupção."
    )
    standard: Optional[ResultadoTesteComparacaoSns] = Field(
        None, description="Resultado do teste Standard (Req. 7.1, 7.2, 7.4)."
    )
    fifo: Optional[ResultadoTesteComparacaoSns] = Field(
        None, description="Resultado do teste FIFO (Req. 7.1, 7.3, 7.4)."
    )
    observacao: str = Field(
        "",
        description=(
            "Texto em pt-BR: o Standard não garante ordenação, mesmo quando as "
            "mensagens chegam na sequência correta (Req. 7.6)."
        ),
    )
    interrompido: bool = Field(
        False,
        description="True quando a comparação foi interrompida (Req. 7.8).",
    )
    mensagem: str = Field(
        "",
        description=(
            "Mensagem em pt-BR; vazia em sucesso e, em interrupção, indicando a "
            "causa (Req. 7.8)."
        ),
    )
    erro_original: Optional[str] = Field(
        None, description="Erro original da AWS em interrupção (Req. 7.8)."
    )


# ---------------------------------------------------------------------------
# Esquemas Pydantic — teste de DLQ com Falha_Entrega_Controlada (Tarefa 13.3)
# ---------------------------------------------------------------------------
class SimularFalhaDlqSns(BaseModel):
    """Corpo de ``POST /api/dlq/simular-falha`` (Req. 8.1, 8.3, 8.10).

    Exige a seleção de uma Assinatura_SNS específica, identificada pelo cenário
    (Standard/FIFO) e pelo destino (``destino_1``/``2``/``3``), que determinam a
    fila de destino alvo cujo recebimento vindo do SNS será negado. O acionamento
    é sempre manual: este endpoint só executa quando chamado explicitamente pelo
    usuário (Req. 8.10).
    """

    cenario: str = Field(
        ..., description="Cenário da assinatura: 'standard' ou 'fifo'."
    )
    destino: str = Field(
        ...,
        description=(
            "Destino da assinatura alvo: 'destino_1', 'destino_2' ou 'destino_3'."
        ),
    )
    id_pedido: str = Field(
        ..., description="ID_Pedido da mensagem de teste (chave de correlação)."
    )


class DemaisAssinaturaDlqSns(BaseModel):
    """Resultado da verificação de uma das demais assinaturas do tópico (Req. 8.4)."""

    destino: str = Field(..., description="Destino da assinatura verificada.")
    fila_destino: str = Field(..., description="Fila de destino dessa assinatura.")
    estado: str = Field(
        ..., description="Estado: 'Entrega_Confirmada' ou 'Não confirmado'."
    )
    confirmada: bool = Field(
        ..., description="True se houve leitura real correlacionada pelo ID_Pedido."
    )
    message_id: Optional[str] = Field(
        None, description="MessageId lido na fila, quando a entrega é confirmada."
    )


class RespostaSimularFalhaDlqSns(BaseModel):
    """Resposta de ``POST /api/dlq/simular-falha`` (teste de DLQ, Req. 8.1-8.11).

    Traz a assinatura selecionada, a fila de destino afetada, o MessageId da
    publicação de teste, o estado na DLQ (Evento_Observado) com o nome da DLQ, o
    resultado das demais assinaturas, o desfecho da restauração da policy e o
    texto explicativo em pt-BR sobre a DLQ do SNS.
    """

    concluido: bool = Field(
        ..., description="True quando o fluxo rodou sem erro de publicação/verificação."
    )
    cenario: str = Field(..., description="Cenário da assinatura: 'standard' ou 'fifo'.")
    tipo: str = Field(..., description="Tipo textual do tópico: 'Standard' ou 'FIFO'.")
    topico: str = Field(..., description="Tópico correspondente à assinatura selecionada.")
    destino: str = Field(..., description="Destino da assinatura alvo.")
    assinatura_selecionada: str = Field(
        ..., description="Identificação textual da Assinatura_SNS selecionada."
    )
    fila_destino_afetada: str = Field(
        ..., description="Fila de destino cuja Access_Policy_Fila foi ajustada."
    )
    id_pedido: str = Field(..., description="ID_Pedido da mensagem de teste.")
    message_id_teste: Optional[str] = Field(
        None, description="MessageId retornado pelo SNS na publicação de teste."
    )
    estado_dlq: str = Field(
        ...,
        description=(
            "Estado na DLQ: 'Entrega_Confirmada' (Evento_Observado) ou "
            "'Não confirmado' ao esgotar o Timeout_Verificacao_DLQ (Req. 8.6, 8.7)."
        ),
    )
    dlq: str = Field(..., description="Nome da DLQ compatível verificada.")
    dlq_message_id: Optional[str] = Field(
        None, description="MessageId constatado na DLQ quando confirmado."
    )
    demais_assinaturas: list[DemaisAssinaturaDlqSns] = Field(
        default_factory=list,
        description="Resultado das demais assinaturas do mesmo tópico (Req. 8.4).",
    )
    policy_restaurada: bool = Field(
        ..., description="True se a Access_Policy_Fila foi restaurada (Req. 8.8)."
    )
    mensagem_restauracao: str = Field(
        "",
        description=(
            "Mensagem em pt-BR orientando a restauração manual quando a restauração "
            "falha (Req. 8.9); vazia em sucesso."
        ),
    )
    texto_explicativo: str = Field(
        ...,
        description="Texto em pt-BR sobre a DLQ do SNS, configurada na assinatura (Req. 8.11).",
    )
    mensagem: str = Field(
        "", description="Mensagem geral em pt-BR (sucesso ou causa da interrupção)."
    )
    erro_original: Optional[str] = Field(
        None, description="Erro original da AWS quando o fluxo é interrompido."
    )


class RespostaEstadoTestesSns(BaseModel):
    """Resposta de ``GET /api/testes/estado`` (estado 'teste ativo' do lado servidor).

    Mapeia cada teste conhecido para ``True`` quando está ativo (botão
    desabilitado) e ``False`` quando inativo (botão habilitado), expondo do lado
    servidor a decisão que o Dashboard apenas reflete (Req. 9.3, 9.4).
    """

    testes_ativos: dict[str, bool] = Field(
        default_factory=dict,
        description="Mapa teste → ativo (True desabilita o botão correspondente).",
    )


# ---------------------------------------------------------------------------
# Esquemas Pydantic — autenticação do Dashboard (Tarefa 13.4)
# ---------------------------------------------------------------------------
class RequisicaoAutenticacaoSns(BaseModel):
    """Corpo de ``POST /api/autenticacao`` (Req. 12.5, 12.6).

    O login do Dashboard exige usuário e senha. A ``origem`` identifica o
    solicitante para o controle de bloqueio por origem após 5 falhas consecutivas
    (Req. 12.6); quando omitida, usa o host do cliente da requisição (Req. 12.7).
    """

    usuario: str = Field(..., description="Usuário informado no login.")
    senha: str = Field(..., description="Senha informada no login.")
    origem: Optional[str] = Field(
        None,
        description=(
            "Origem do solicitante (ex.: IP). Quando omitida, usa o host do cliente "
            "da requisição. Base do controle de bloqueio por origem (Req. 12.6, 12.7)."
        ),
    )


class RespostaAutenticacaoSns(BaseModel):
    """Resposta de ``POST /api/autenticacao`` (Req. 12.4, 12.5, 12.6).

    Representação **segura** para o navegador: não contém qualquer credencial da
    AWS (Req. 12.4). ``acesso_concedido`` é ``True`` somente com credenciais
    válidas; ``bloqueada`` indica se a origem está em período de bloqueio (após 5
    falhas consecutivas) e ``segundos_restantes_bloqueio`` o tempo restante
    (Req. 12.6).
    """

    acesso_concedido: bool = Field(
        ..., description="True apenas quando a autenticação é bem-sucedida."
    )
    resultado: str = Field(
        ...,
        description=(
            "Desfecho técnico: SUCESSO, FALHA, BLOQUEADA ou ORIGEM_NAO_AUTORIZADA."
        ),
    )
    bloqueada: bool = Field(
        ...,
        description="True se a origem está bloqueada após esta avaliação (Req. 12.6).",
    )
    segundos_restantes_bloqueio: int = Field(
        ..., ge=0, description="Segundos restantes do bloqueio (0 se não bloqueada)."
    )
    mensagem: str = Field(..., description="Mensagem em pt-BR descrevendo o desfecho.")


# ---------------------------------------------------------------------------
# Helpers de acesso às dependências em app.state
# ---------------------------------------------------------------------------
def _estado_simulacao(request: Request) -> EstadoConfigSimulacaoSns:
    return request.app.state.estado_simulacao_sns


def _estado_estatisticas(request: Request) -> EstadoEstatisticasSns:
    return request.app.state.estado_estatisticas_sns


def _verificador_inicializacao(request: Request) -> VerificacaoInicializacaoSns:
    return request.app.state.verificador_inicializacao_sns


def _servico_disparo(request: Request) -> ServicoDisparoSns:
    return request.app.state.servico_disparo_sns


def _servico_comparacao(request: Request) -> ServicoComparacaoSns:
    return request.app.state.servico_comparacao_sns


def _servico_dlq(request: Request) -> ServicoDlqSns:
    return request.app.state.servico_dlq_sns


def _estado_testes(request: Request) -> EstadoTestesSns:
    return request.app.state.estado_testes_sns


def _controlador_autenticacao(request: Request) -> ControladorAutenticacaoSns:
    return request.app.state.controlador_autenticacao_sns


def _credenciais_dashboard(request: Request) -> CredenciaisDashboardSns:
    return request.app.state.credenciais_dashboard_sns


# ---------------------------------------------------------------------------
# Montagem das respostas de configuração
# ---------------------------------------------------------------------------
def _parametros_config_aplicada() -> list[ParametroConfigSns]:
    """Monta a lista de parâmetros de Config_Aplicada (Req. 2.1-2.4, 2.6, 2.9).

    Todos recebem o rótulo distinto ``Config_Aplicada``, ``ajustavel=False`` e a
    orientação de que a mudança só ocorre no Console AWS. Estes parâmetros refletem
    o que foi configurado manualmente nos recursos: o tipo de cada tópico, a
    Redrive_Policy_SNS que aponta para a DLQ compatível, a Deduplicacao_Por_Conteudo
    do Topico_FIFO e a Access_Policy_Fila que autoriza o SNS a publicar.
    """

    def aplicada(nome: str, valor: object, unidade: Optional[str] = None) -> ParametroConfigSns:
        return ParametroConfigSns(
            nome=nome,
            valor=valor,
            unidade=unidade,
            rotulo=ROTULO_CONFIG_APLICADA,
            ajustavel=False,
            orientacao=ORIENTACAO_CONFIG_APLICADA,
        )

    dedup = "Habilitada" if c.DEDUPLICACAO_POR_CONTEUDO_FIFO else "Desabilitada"
    return [
        # Tipo de cada tópico como Config_Aplicada (Req. 2.1).
        aplicada(f"Tipo do tópico '{c.TOPICO_STANDARD}'", "Standard"),
        aplicada(f"Tipo do tópico '{c.TOPICO_FIFO}'", "FIFO"),
        # Redrive_Policy_SNS das assinaturas aponta para a DLQ compatível (Req. 2.2).
        aplicada(
            "Redrive_Policy_SNS das assinaturas Standard",
            f"Aponta para a DLQ '{c.DLQ_SNS_STANDARD}'",
        ),
        aplicada(
            "Redrive_Policy_SNS das assinaturas FIFO",
            f"Aponta para a DLQ '{c.DLQ_SNS_FIFO}'",
        ),
        # Deduplicacao_Por_Conteudo do Topico_FIFO (Req. 2.3).
        aplicada(
            f"Deduplicacao_Por_Conteudo do tópico '{c.TOPICO_FIFO}'", dedup
        ),
        # Access_Policy_Fila autoriza o SNS a publicar em cada fila de destino (Req. 2.4).
        aplicada(
            "Access_Policy_Fila das filas de destino",
            "Autoriza o SNS a publicar em cada fila de destino do cenário",
        ),
    ]


def _parametros_config_simulacao(
    estado: EstadoConfigSimulacaoSns,
) -> list[ParametroConfigSns]:
    """Monta a lista de parâmetros de Config_Simulacao (Req. 2.5, 2.6, 2.7).

    Todos recebem o rótulo distinto ``Config_Simulacao``, ``ajustavel=True`` e a
    faixa válida que o Dashboard deve respeitar.
    """
    valores = estado.valores()

    def simulacao(
        nome: str, valor: int, minimo: int, maximo: int, unidade: Optional[str]
    ) -> ParametroConfigSns:
        return ParametroConfigSns(
            nome=nome,
            valor=valor,
            unidade=unidade,
            rotulo=ROTULO_CONFIG_SIMULACAO,
            ajustavel=True,
            faixa_minima=minimo,
            faixa_maxima=maximo,
        )

    return [
        simulacao(
            "Timeout_Verificacao_Entrega",
            valores.timeout_verificacao_entrega_segundos,
            c.TIMEOUT_VERIFICACAO_ENTREGA_MIN,
            c.TIMEOUT_VERIFICACAO_ENTREGA_MAX,
            "segundos",
        ),
        simulacao(
            "Timeout_Verificacao_DLQ",
            valores.timeout_verificacao_dlq_segundos,
            c.TIMEOUT_VERIFICACAO_DLQ_MIN,
            c.TIMEOUT_VERIFICACAO_DLQ_MAX,
            "segundos",
        ),
        simulacao(
            "Intervalo de atualização",
            valores.intervalo_atualizacao_segundos,
            c.INTERVALO_ATUALIZACAO_MIN,
            c.INTERVALO_ATUALIZACAO_MAX,
            "segundos",
        ),
    ]


# ---------------------------------------------------------------------------
# Roteador de configuração e saúde (Tarefa 12.1)
# ---------------------------------------------------------------------------
def criar_roteador_config_saude_sns() -> APIRouter:
    """Cria o APIRouter com os endpoints de saúde e configuração do SNS (Tarefa 12.1)."""
    roteador = APIRouter(prefix="/api", tags=["sns-config-saude"])

    @roteador.get(
        "/saude",
        response_model=RespostaSaudeSns,
        summary="Verificação de inicialização dos recursos AWS",
    )
    def obter_saude(request: Request) -> RespostaSaudeSns:
        """Verifica a existência e a acessibilidade dos recursos AWS (Req. 1.9, 1.11).

        Reutiliza :class:`VerificacaoInicializacaoSns` em modo **não interruptivo**
        para sempre responder (com ``saudavel=False`` quando algum recurso está
        indisponível), preservando o erro original da AWS no detalhe de cada recurso.
        A verificação é *fail-fast*: ``recursos`` traz os recursos checados até o
        ponto da interrupção.
        """
        relatorio = _verificador_inicializacao(request).verificar_recursos(
            interromper_em_falha=False
        )
        recursos = [
            RecursoSaudeSns(
                nome=r.nome,
                tipo=r.tipo.value,
                disponivel=r.disponivel,
                detalhe_erro=(repr(r.erro_original) if r.erro_original else None),
            )
            for r in relatorio.recursos
        ]
        return RespostaSaudeSns(
            saudavel=relatorio.sucesso,
            mensagem=relatorio.mensagem_pt_br,
            recursos=recursos,
        )

    @roteador.get(
        "/config",
        response_model=RespostaConfigSns,
        summary="Configuração aplicada e de simulação",
    )
    def obter_config(request: Request) -> RespostaConfigSns:
        """Retorna Config_Aplicada e Config_Simulacao com rótulos distintos (Req. 2.1-2.9)."""
        return RespostaConfigSns(
            config_aplicada=_parametros_config_aplicada(),
            config_simulacao=_parametros_config_simulacao(_estado_simulacao(request)),
            orientacao_config_aplicada=ORIENTACAO_CONFIG_APLICADA,
        )

    @roteador.put(
        "/config/simulacao",
        response_model=RespostaAjusteConfigSimulacaoSns,
        summary="Ajuste de parâmetros de Config_Simulacao",
    )
    def ajustar_config_simulacao(
        ajuste: AjusteConfigSimulacaoSns, request: Request
    ) -> RespostaAjusteConfigSimulacaoSns:
        """Ajusta Timeout_Verificacao_Entrega e _DLQ dentro das faixas (Req. 2.5, 2.7, 2.8).

        Cada parâmetro informado é validado pela faixa correspondente: aceito só se
        estiver dentro do intervalo; ao rejeitar, o valor anterior é **preservado**
        e a mensagem em pt-BR indica a **faixa válida**. Parâmetros não informados
        não são alterados.
        """
        estado = _estado_simulacao(request)
        ajustes: list[ResultadoAjusteParametroSns] = []

        if ajuste.timeout_verificacao_entrega_segundos is not None:
            resultado: ResultadoValidacaoFaixa = (
                estado.ajustar_timeout_verificacao_entrega(
                    ajuste.timeout_verificacao_entrega_segundos
                )
            )
            ajustes.append(
                ResultadoAjusteParametroSns(
                    parametro="Timeout_Verificacao_Entrega",
                    aceito=resultado.aceito,
                    valor_efetivo=resultado.valor_efetivo,
                    mensagem=resultado.mensagem,
                )
            )

        if ajuste.timeout_verificacao_dlq_segundos is not None:
            resultado = estado.ajustar_timeout_verificacao_dlq(
                ajuste.timeout_verificacao_dlq_segundos
            )
            ajustes.append(
                ResultadoAjusteParametroSns(
                    parametro="Timeout_Verificacao_DLQ",
                    aceito=resultado.aceito,
                    valor_efetivo=resultado.valor_efetivo,
                    mensagem=resultado.mensagem,
                )
            )

        return RespostaAjusteConfigSimulacaoSns(
            ajustes=ajustes,
            config_simulacao=_parametros_config_simulacao(estado),
        )

    return roteador


# ---------------------------------------------------------------------------
# Conversão do agregado interno para o esquema de resposta
# ---------------------------------------------------------------------------
# Rótulos distintos dos dois conjuntos de estatísticas exibidos lado a lado (Req. 3.7).
ROTULO_CENARIO_STANDARD: str = "Cenário Standard"
ROTULO_CENARIO_FIFO: str = "Cenário FIFO"


def _contadores(mapa: dict[str, int]) -> list[ContadorRecursoSns]:
    """Converte um dicionário nome→contador em uma lista ordenada por nome.

    A ordenação por nome mantém a resposta estável entre requisições, o que
    facilita o consumo pelo Dashboard e a asserção nos testes.
    """
    return [
        ContadorRecursoSns(nome=nome, valor=valor)
        for nome, valor in sorted(mapa.items())
    ]


def _cenario_para_esquema(
    cenario: Cenario, rotulo: str, estat: EstatisticasCenario
) -> EstatisticasCenarioSns:
    """Monta o esquema de um cenário a partir do :class:`EstatisticasCenario`."""
    return EstatisticasCenarioSns(
        cenario=cenario.value,
        rotulo=rotulo,
        publicadas_por_topico=_contadores(estat.publicadas_por_topico),
        confirmadas_por_fila=_contadores(estat.confirmadas_por_fila),
        presentes_por_dlq=_contadores(estat.presentes_por_dlq),
    )


def _estatisticas_para_resposta(
    resultado: ResultadoEstatisticasSns,
) -> RespostaEstatisticasSns:
    """Converte o :class:`ResultadoEstatisticasSns` para o corpo HTTP (Req. 3.4-3.10, 14.3).

    Trata o caso de timeout logo na primeira coleta (ainda sem snapshot em cache):
    devolve ``standard``/``fifo`` nulos, ``timeout=True`` e a mensagem de
    desatualização, sem horário de última atualização.
    """
    estat: Optional[EstatisticasSns] = resultado.estatisticas
    if estat is None:
        return RespostaEstatisticasSns(
            standard=None,
            fifo=None,
            ultima_atualizacao=None,
            timeout=resultado.timeout,
            mensagem=resultado.mensagem,
        )

    ultima = (
        estat.ultima_atualizacao.isoformat()
        if estat.ultima_atualizacao is not None
        else None
    )
    return RespostaEstatisticasSns(
        standard=_cenario_para_esquema(
            Cenario.STANDARD, ROTULO_CENARIO_STANDARD, estat.standard
        ),
        fifo=_cenario_para_esquema(Cenario.FIFO, ROTULO_CENARIO_FIFO, estat.fifo),
        ultima_atualizacao=ultima,
        timeout=resultado.timeout,
        mensagem=resultado.mensagem,
    )


# ---------------------------------------------------------------------------
# Montagem dos dados da arquitetura (Req. 3.1, 3.2)
# ---------------------------------------------------------------------------
def _dados_arquitetura() -> RespostaArquiteturaSns:
    """Monta os dados da representação visual da arquitetura (Req. 3.1, 3.2).

    Deriva tudo das constantes do laboratório: os dois tópicos com o tipo textual
    distinto e a DLQ compatível, as seis assinaturas (fan-out de cada tópico para
    as suas três filas de destino), as seis filas de destino e as duas DLQs. É uma
    função pura, sem acesso à AWS: descreve os recursos que o usuário criou
    manualmente, conforme o laboratório não cria nem altera recursos.
    """
    topicos = [
        TopicoArquiteturaSns(
            nome=c.TOPICO_STANDARD,
            tipo="Standard",
            dlq_compativel=c.DLQ_SNS_STANDARD,
        ),
        TopicoArquiteturaSns(
            nome=c.TOPICO_FIFO,
            tipo="FIFO",
            dlq_compativel=c.DLQ_SNS_FIFO,
        ),
    ]

    assinaturas: list[AssinaturaArquiteturaSns] = []
    for topico, filas in c.FILAS_DESTINO_POR_TOPICO.items():
        for fila in filas:
            assinaturas.append(
                AssinaturaArquiteturaSns(topico=topico, fila_destino=fila)
            )

    filas_destino = [
        RecursoArquiteturaSns(nome=fila, tipo="Standard")
        for fila in c.FILAS_DESTINO_STANDARD
    ] + [
        RecursoArquiteturaSns(nome=fila, tipo="FIFO")
        for fila in c.FILAS_DESTINO_FIFO
    ]

    dlqs = [
        RecursoArquiteturaSns(nome=c.DLQ_SNS_STANDARD, tipo="Standard"),
        RecursoArquiteturaSns(nome=c.DLQ_SNS_FIFO, tipo="FIFO"),
    ]

    return RespostaArquiteturaSns(
        topicos=topicos,
        assinaturas=assinaturas,
        filas_destino=filas_destino,
        dlqs=dlqs,
    )


# ---------------------------------------------------------------------------
# Roteador de estatísticas e arquitetura (Tarefa 12.2)
# ---------------------------------------------------------------------------
def criar_roteador_estatisticas_arquitetura_sns() -> APIRouter:
    """Cria o APIRouter com ``GET /api/estatisticas`` e ``GET /api/arquitetura`` (Tarefa 12.2)."""
    roteador = APIRouter(prefix="/api", tags=["sns-estatisticas-arquitetura"])

    @roteador.get(
        "/estatisticas",
        response_model=RespostaEstatisticasSns,
        summary="Estatísticas agregadas por cenário com timeout de 3s",
    )
    def obter_estatisticas(request: Request) -> RespostaEstatisticasSns:
        """Agrega as estatísticas por cenário respeitando o timeout de 3s (Req. 3.4-3.10, 14.1, 14.3).

        Delega ao :class:`EstadoEstatisticasSns`, que executa a coleta e a
        agregação com limite de tempo: concluindo dentro do prazo, devolve o novo
        agregado (publicadas por tópico, Entrega_Confirmada por fila e presentes em
        cada DLQ, separados por cenário, com o horário da última atualização
        bem-sucedida); ao exceder, retorna a indicação de timeout e **preserva os
        últimos dados válidos**, mantendo inalterado o horário do último sucesso.
        """
        return _estatisticas_para_resposta(_estado_estatisticas(request).obter())

    @roteador.get(
        "/arquitetura",
        response_model=RespostaArquiteturaSns,
        summary="Dados da representação visual da arquitetura",
    )
    def obter_arquitetura() -> RespostaArquiteturaSns:
        """Retorna os dados da arquitetura: 2 tópicos, 6 assinaturas, 6 filas, 2 DLQs (Req. 3.1, 3.2)."""
        return _dados_arquitetura()

    return roteador


# ---------------------------------------------------------------------------
# Conversão do resultado de disparo para o esquema de resposta (Tarefa 13.1)
# ---------------------------------------------------------------------------
def _disparo_para_resposta(resultado: ResultadoDisparo) -> RespostaDisparoSns:
    """Converte o :class:`ResultadoDisparo` do serviço para o corpo HTTP."""
    destinos = [
        DestinoDisparoSns(
            destino=d.destino,
            titulo_destino=d.titulo_destino,
            fila_destino=d.fila_destino,
            estado=d.estado.value,
            confirmada=d.confirmada,
            message_id=d.message_id,
        )
        for d in resultado.destinos
    ]
    return RespostaDisparoSns(
        aceito=resultado.aceito,
        cenario=resultado.cenario.value,
        id_pedido=resultado.id_pedido,
        topico=resultado.topico,
        tipo=resultado.tipo,
        message_group_id=resultado.message_group_id,
        message_id=resultado.message_id,
        destinos=destinos,
        notificacao_visual=resultado.notificacao_visual,
        falha_publicacao=resultado.falha_publicacao,
        campos_invalidos=list(resultado.campos_invalidos),
        mensagens=dict(resultado.mensagens),
        mensagem=resultado.mensagem,
        erro_original=resultado.erro_original,
    )


# ---------------------------------------------------------------------------
# Roteador de disparo Standard/FIFO (Tarefa 13.1)
# ---------------------------------------------------------------------------
def criar_roteador_disparo_sns() -> APIRouter:
    """Cria o APIRouter com os endpoints de disparo e o estado de testes (Tarefa 13.1).

    Expõe ``POST /api/disparar/standard`` e ``POST /api/disparar/fifo``, que validam
    o payload, publicam via SnsGateway, registram Entrega_Publicada com o MessageId
    e disparam a verificação de entrega nas três filas de destino, além de
    ``GET /api/testes/estado``, que expõe do lado servidor o estado "teste ativo"
    (botão desabilitado) que o Dashboard reflete (Req. 9.3, 9.4).
    """
    roteador = APIRouter(prefix="/api", tags=["sns-disparo"])

    def _disparar(
        request: Request,
        cenario: Cenario,
        teste: str,
        id_pedido: str,
        message_group_id: Optional[str],
    ) -> RespostaDisparoSns:
        """Executa um disparo marcando o teste como ativo durante a execução.

        O estado "teste ativo" é mantido do lado servidor: o botão correspondente
        fica desabilitado enquanto o teste executa (Req. 9.3) e é reabilitado ao
        concluir — inclusive em erro —, graças ao context manager ``em_execucao``
        (Req. 9.4).
        """
        estado_testes = _estado_testes(request)
        servico = _servico_disparo(request)
        with estado_testes.em_execucao(teste):
            resultado = servico.disparar(
                cenario, id_pedido, message_group_id=message_group_id
            )
        return _disparo_para_resposta(resultado)

    @roteador.post(
        "/disparar/standard",
        response_model=RespostaDisparoSns,
        summary="Publica no Topico_Standard e dispara a verificação de entrega",
    )
    def disparar_standard(
        corpo: DisparoStandardSns, request: Request
    ) -> RespostaDisparoSns:
        """Publica no Topico_Standard e verifica a entrega nas três filas (Req. 4.1-4.8).

        Valida o ID_Pedido; publica via SnsGateway; registra Entrega_Publicada com
        o MessageId; dispara a verificação de entrega por leitura real nas três
        filas de destino Standard; e, em falha de publicação, registra o erro
        original e indica a falha em pt-BR, sem enviar SMS/e-mail reais.
        """
        return _disparar(
            request,
            Cenario.STANDARD,
            TESTE_DISPARAR_STANDARD,
            corpo.id_pedido,
            None,
        )

    @roteador.post(
        "/disparar/fifo",
        response_model=RespostaDisparoSns,
        summary="Publica no Topico_FIFO (MessageGroupId) e dispara a verificação",
    )
    def disparar_fifo(corpo: DisparoFifoSns, request: Request) -> RespostaDisparoSns:
        """Publica no Topico_FIFO e verifica a entrega nas três filas (Req. 5.1-5.10, 11.5).

        Valida o ID_Pedido e o MessageGroupId (FIFO sem MessageGroupId é sempre
        rejeitado); publica via SnsGateway sempre com MessageGroupId e sem
        MessageDeduplicationId (dedup por conteúdo habilitada); registra
        Entrega_Publicada com o MessageId; dispara a verificação nas três filas de
        destino FIFO; e, em falha, registra o erro original e indica a falha em
        pt-BR, sem enviar SMS/e-mail reais.
        """
        return _disparar(
            request,
            Cenario.FIFO,
            TESTE_DISPARAR_FIFO,
            corpo.id_pedido,
            corpo.message_group_id,
        )

    @roteador.get(
        "/testes/estado",
        response_model=RespostaEstadoTestesSns,
        summary="Estado 'teste ativo' (botão desabilitado) do lado servidor",
    )
    def obter_estado_testes(request: Request) -> RespostaEstadoTestesSns:
        """Expõe o estado "teste ativo" que desabilita os botões no Dashboard (Req. 9.3, 9.4)."""
        return RespostaEstadoTestesSns(testes_ativos=_estado_testes(request).estado())

    return roteador


# ---------------------------------------------------------------------------
# Conversão do resultado de comparação para o esquema de resposta (Tarefa 13.2)
# ---------------------------------------------------------------------------
def _teste_comparacao_para_esquema(
    resultado,
) -> ResultadoTesteComparacaoSns:
    """Converte um :class:`ResultadoTesteComparacao` para o esquema de resposta."""
    return ResultadoTesteComparacaoSns(
        cenario=resultado.cenario.value,
        tipo=resultado.tipo,
        topico=resultado.topico,
        id_pedido=resultado.id_pedido,
        message_group_id=resultado.message_group_id,
        ordem_publicacao=[
            MensagemComparacaoSns(
                sequencia=m.sequencia, conteudo=m.conteudo, message_id=m.message_id
            )
            for m in resultado.ordem_publicacao
        ],
        ordem_recebimento=[
            ItemRecebimentoSns(
                conteudo=item.conteudo,
                message_id=item.message_id,
                estado=item.estado.value,
                confirmada=item.confirmada,
            )
            for item in resultado.ordem_recebimento
        ],
    )


def _comparacao_para_resposta(resultado: ResultadoComparacao) -> RespostaCompararSns:
    """Converte o :class:`ResultadoComparacao` do serviço para o corpo HTTP."""
    return RespostaCompararSns(
        concluido=resultado.concluido,
        standard=(
            _teste_comparacao_para_esquema(resultado.standard)
            if resultado.standard is not None
            else None
        ),
        fifo=(
            _teste_comparacao_para_esquema(resultado.fifo)
            if resultado.fifo is not None
            else None
        ),
        observacao=resultado.observacao,
        interrompido=resultado.interrompido,
        mensagem=resultado.mensagem,
        erro_original=resultado.erro_original,
    )


# ---------------------------------------------------------------------------
# Roteador de comparação Standard x FIFO (Tarefa 13.2)
# ---------------------------------------------------------------------------
def criar_roteador_comparacao_sns() -> APIRouter:
    """Cria o APIRouter com ``POST /api/comparar`` (Tarefa 13.2).

    Executa os dois testes independentes (Standard e FIFO, FIFO com um único
    MessageGroupId), publicando as três mensagens de comparação em sequência,
    observando a ordem de recebimento por leitura real (sem reordenar) e retornando
    os resultados lado a lado com o texto explicativo em pt-BR (Req. 7.1-7.9). O
    botão COMPARAR fica desabilitado enquanto o teste executa, graças ao estado de
    testes do lado servidor (Req. 9.3, 9.4).
    """
    roteador = APIRouter(prefix="/api", tags=["sns-comparacao"])

    @roteador.post(
        "/comparar",
        response_model=RespostaCompararSns,
        summary="Compara Standard x FIFO executando dois testes independentes",
    )
    def comparar(corpo: CompararSns, request: Request) -> RespostaCompararSns:
        """Executa a comparação Standard x FIFO e retorna os dois testes lado a lado.

        Marca o teste COMPARAR como ativo durante a execução (botão desabilitado —
        Req. 9.3) e o reabilita ao concluir, inclusive em erro (Req. 9.4). Em
        interrupção por tópico indisponível ou falha de autenticação, devolve a
        causa em pt-BR (Req. 7.8).
        """
        estado_testes = _estado_testes(request)
        servico = _servico_comparacao(request)
        with estado_testes.em_execucao(TESTE_COMPARAR):
            resultado = servico.comparar(
                corpo.id_pedido, message_group_id=corpo.message_group_id
            )
        return _comparacao_para_resposta(resultado)

    return roteador


# ---------------------------------------------------------------------------
# Conversão do resultado de teste de DLQ para o esquema de resposta (Tarefa 13.3)
# ---------------------------------------------------------------------------
def _dlq_para_resposta(resultado: ResultadoDlq) -> RespostaSimularFalhaDlqSns:
    """Converte o :class:`ResultadoDlq` do serviço para o corpo HTTP."""
    return RespostaSimularFalhaDlqSns(
        concluido=resultado.concluido,
        cenario=resultado.cenario.value,
        tipo=resultado.tipo,
        topico=resultado.topico,
        destino=resultado.destino,
        assinatura_selecionada=resultado.assinatura_selecionada,
        fila_destino_afetada=resultado.fila_destino_afetada,
        id_pedido=resultado.id_pedido,
        message_id_teste=resultado.message_id_teste,
        estado_dlq=resultado.estado_dlq.value,
        dlq=resultado.dlq,
        dlq_message_id=resultado.dlq_message_id,
        demais_assinaturas=[
            DemaisAssinaturaDlqSns(
                destino=d.destino,
                fila_destino=d.fila_destino,
                estado=d.estado.value,
                confirmada=d.confirmada,
                message_id=d.message_id,
            )
            for d in resultado.demais_assinaturas
        ],
        policy_restaurada=resultado.policy_restaurada,
        mensagem_restauracao=resultado.mensagem_restauracao,
        texto_explicativo=resultado.texto_explicativo,
        mensagem=resultado.mensagem,
        erro_original=resultado.erro_original,
    )


# ---------------------------------------------------------------------------
# Roteador de teste de DLQ com Falha_Entrega_Controlada (Tarefa 13.3)
# ---------------------------------------------------------------------------
def criar_roteador_dlq_sns() -> APIRouter:
    """Cria o APIRouter com ``POST /api/dlq/simular-falha`` (Tarefa 13.3).

    Exige acionamento manual e a seleção de uma Assinatura_SNS (cenário + destino);
    salva e aplica o ``Deny`` temporário via Gerenciador_Falha_Controlada, publica
    a mensagem de teste, verifica as demais assinaturas e a DLQ compatível (até o
    Timeout_Verificacao_DLQ), restaura a Access_Policy_Fila ao final (sempre) e, em
    falha de restauração, identifica a fila afetada e orienta a restauração manual
    pelo Console AWS (pt-BR). Exibe o texto explicativo em pt-BR sobre a DLQ do SNS
    (Req. 8.1-8.11). O botão TESTAR DLQ fica desabilitado enquanto o teste executa,
    graças ao estado de testes do lado servidor (Req. 9.1, 9.3, 9.4).
    """
    roteador = APIRouter(prefix="/api", tags=["sns-dlq"])

    @roteador.post(
        "/dlq/simular-falha",
        response_model=RespostaSimularFalhaDlqSns,
        summary="Testa a DLQ do SNS com Falha_Entrega_Controlada reversível",
    )
    def simular_falha_dlq(
        corpo: SimularFalhaDlqSns, request: Request
    ) -> RespostaSimularFalhaDlqSns:
        """Executa a Falha_Entrega_Controlada e verifica a DLQ do SNS (Req. 8.1-8.11).

        Valida a seleção da Assinatura_SNS (cenário/destino), marca o teste DLQ
        como ativo durante a execução (botão desabilitado — Req. 9.3) e o reabilita
        ao concluir, inclusive em erro (Req. 9.4). A Access_Policy_Fila é sempre
        restaurada ao final (Req. 8.8).
        """
        try:
            cenario = Cenario(corpo.cenario)
        except ValueError:
            return _resposta_dlq_selecao_invalida(
                corpo,
                "Cenário inválido: selecione 'standard' ou 'fifo' para a "
                "Assinatura_SNS.",
            )

        estado_testes = _estado_testes(request)
        servico = _servico_dlq(request)
        with estado_testes.em_execucao(TESTE_DLQ):
            try:
                resultado = servico.simular_falha(
                    cenario, corpo.destino, corpo.id_pedido
                )
            except SelecaoAssinaturaInvalida as erro:
                return _resposta_dlq_selecao_invalida(corpo, str(erro))
        return _dlq_para_resposta(resultado)

    return roteador


def _resposta_dlq_selecao_invalida(
    corpo: SimularFalhaDlqSns, mensagem: str
) -> RespostaSimularFalhaDlqSns:
    """Monta a resposta de seleção inválida de Assinatura_SNS, sem alterar recursos.

    Quando o cenário ou o destino informados não identificam uma Assinatura_SNS do
    laboratório, nenhuma Access_Policy_Fila é alterada: devolve-se um resultado
    não concluído com a mensagem em pt-BR orientando a seleção correta.
    """
    return RespostaSimularFalhaDlqSns(
        concluido=False,
        cenario=corpo.cenario,
        tipo="",
        topico="",
        destino=corpo.destino,
        assinatura_selecionada="",
        fila_destino_afetada="",
        id_pedido=corpo.id_pedido,
        message_id_teste=None,
        estado_dlq="Não confirmado",
        dlq="",
        dlq_message_id=None,
        demais_assinaturas=[],
        policy_restaurada=True,
        mensagem_restauracao="",
        texto_explicativo=TEXTO_EXPLICATIVO_DLQ,
        mensagem=mensagem,
        erro_original=None,
    )


# ---------------------------------------------------------------------------
# Roteador de autenticação do Dashboard (Tarefa 13.4)
# ---------------------------------------------------------------------------
def criar_roteador_autenticacao_sns() -> APIRouter:
    """Cria o APIRouter com ``POST /api/autenticacao`` do Dashboard SNS (Tarefa 13.4).

    Expõe o login do Dashboard reutilizando a camada de segurança do laboratório
    (:class:`ControladorAutenticacaoSns`): valida usuário/senha por um verificador
    injetável e bloqueia a origem após 5 falhas consecutivas por 300 segundos; um
    sucesso antes do limite reinicia a contagem (Req. 12.5, 12.6). A resposta é
    saneada para o navegador, sem expor credenciais da AWS (Req. 12.4).
    """
    roteador = APIRouter(prefix="/api", tags=["sns-autenticacao"])

    @roteador.post(
        "/autenticacao",
        response_model=RespostaAutenticacaoSns,
        summary="Login do Dashboard com bloqueio por origem após 5 falhas",
    )
    def autenticar_endpoint(
        corpo: RequisicaoAutenticacaoSns, request: Request
    ) -> RespostaAutenticacaoSns:
        """Avalia o login do Dashboard do SNS (Req. 12.4, 12.5, 12.6, 12.7).

        Bloqueia a origem após 5 falhas consecutivas por 300 s; um sucesso antes do
        limite reinicia a contagem. A lógica fica em
        :func:`app.api.servico_autenticacao_sns.autenticar_sns`, que serializa o
        resultado de forma segura para o navegador (sem credenciais da AWS).
        """
        origem_requisicao = request.client.host if request.client else "desconhecida"
        seguro = autenticar_sns(
            corpo.usuario,
            corpo.senha,
            corpo.origem,
            controlador=_controlador_autenticacao(request),
            credenciais=_credenciais_dashboard(request),
            origem_requisicao=origem_requisicao,
        )
        return RespostaAutenticacaoSns(
            acesso_concedido=bool(seguro.get("acesso_concedido", False)),
            resultado=str(seguro.get("resultado", "")),
            bloqueada=bool(seguro.get("bloqueada", False)),
            segundos_restantes_bloqueio=int(
                seguro.get("segundos_restantes_bloqueio", 0)
            ),
            mensagem=str(seguro.get("mensagem", "")),
        )

    return roteador


# ---------------------------------------------------------------------------
# Fábrica da aplicação FastAPI do laboratório SNS
# ---------------------------------------------------------------------------
def criar_app_sns(
    *,
    estado_simulacao_sns: Optional[EstadoConfigSimulacaoSns] = None,
    verificador_inicializacao_sns: Optional[VerificacaoInicializacaoSns] = None,
    estado_estatisticas_sns: Optional[EstadoEstatisticasSns] = None,
    provedor_observacoes: Optional[Callable[[], Iterable[object]]] = None,
    registro_observacoes_sns: Optional[RegistroObservacoesSns] = None,
    estado_testes_sns: Optional[EstadoTestesSns] = None,
    servico_disparo_sns: Optional[ServicoDisparoSns] = None,
    servico_comparacao_sns: Optional[ServicoComparacaoSns] = None,
    servico_dlq_sns: Optional[ServicoDlqSns] = None,
    sns_gateway: Optional[SnsGateway] = None,
    verificador_entrega_sns: Optional[VerificadorEntrega] = None,
    sqs_leitura_gateway_sns: Optional[SqsLeituraGateway] = None,
    gerenciador_falha_controlada_sns: Optional[GerenciadorFalhaControlada] = None,
    controlador_autenticacao_sns: Optional[ControladorAutenticacaoSns] = None,
    credenciais_dashboard_sns: Optional[CredenciaisDashboardSns] = None,
    resolver_arn_topico: Optional[Callable[[str], str]] = None,
    resolver_url_fila: Optional[Callable[[str], str]] = None,
    nome_iam_role: str = "delivery-sns-ec2-role",
    id_instancia_ec2: str = "",
) -> FastAPI:
    """Compõe a API_Backend do laboratório SNS (saúde/config/estatísticas/disparo).

    Fluxo da composição:

    1. Cria a instância FastAPI com título "AWS SNS Delivery Lab".
    2. Injeta em ``app.state`` o estado de Config_Simulacao, o verificador de
       inicialização, o estado de estatísticas, o registro de observações, o estado
       de testes ativos e o serviço de disparo. Em produção, deixe os componentes
       como ``None`` para que a fábrica crie os reais sobre boto3 (credenciais pela
       IAM Role da EC2, sem Access Keys — Req. 12.1, 12.2); em testes, injete fakes
       para não depender da AWS real.
    3. Registra os roteadores de saúde/configuração, estatísticas/arquitetura,
       disparo Standard/FIFO, comparação, DLQ e autenticação do Dashboard.

    Observações sobre o wiring do disparo (Tarefa 13.1):

    - O **registro de observações** é a fonte concreta de ``/api/estatisticas``:
      quando ``provedor_observacoes`` não é informado, a fábrica usa
      ``registro_observacoes_sns.observacoes`` como provedor, de modo que cada
      Entrega_Publicada e Entrega_Confirmada registrada pelos disparos passe a
      contar nas estatísticas (Req. 3.4, 3.5).
    - O **estado de testes** mantém, do lado servidor, quais testes estão ativos
      (botão desabilitado), refletido por ``GET /api/testes/estado`` (Req. 9.3, 9.4).
    - O **serviço de disparo**, quando não injetado, é montado com o SnsGateway e o
      VerificadorEntrega (sobre o SqsLeituraGateway), ambos boto3 reais sem Access
      Keys em produção. O Timeout_Verificacao_Entrega vem da Config_Simulacao.

    Args:
        estado_simulacao_sns: estado de Config_Simulacao injetável; ``None`` cria um
            com os valores padrão do laboratório.
        verificador_inicializacao_sns: verificador de inicialização injetável;
            ``None`` cria o real sobre boto3 (requer ``nome_iam_role`` e
            ``id_instancia_ec2``).
        estado_estatisticas_sns: estado de estatísticas injetável; ``None`` cria um
            sobre o provedor derivado do registro de observações.
        provedor_observacoes: callable que devolve o iterável atual de observações;
            quando ``None``, usa ``registro_observacoes_sns.observacoes``.
        registro_observacoes_sns: registro de observações injetável; ``None`` cria um
            vazio, compartilhado entre o serviço de disparo (produtor) e o estado de
            estatísticas (consumidor).
        estado_testes_sns: estado de testes ativos injetável; ``None`` cria um vazio.
        servico_disparo_sns: serviço de disparo injetável; ``None`` monta o real.
        sns_gateway: :class:`SnsGateway` injetável para o serviço de disparo;
            ``None`` cria o real (boto3 sem Access Keys).
        verificador_entrega_sns: :class:`VerificadorEntrega` injetável; ``None`` cria
            o real sobre o SqsLeituraGateway (boto3 sem Access Keys).
        resolver_arn_topico: resolve o ARN de um tópico pelo nome; ``None`` usa um
            resolvedor padrão derivado da região e do laboratório.
        resolver_url_fila: resolve a URL de uma fila pelo nome; ``None`` usa um
            resolvedor padrão derivado da região.
        controlador_autenticacao_sns: controlador de autenticação injetável
            (relógio controlável para testes); ``None`` cria um controlador padrão
            em modo laboratório aberto (``permitir_todas_origens=True``), mantendo o
            bloqueio após 5 falhas consecutivas por 300 s (Req. 12.6).
        credenciais_dashboard_sns: verificador de credenciais (usuário/senha)
            injetável; ``None`` cria um padrão. Em produção, as credenciais vêm de
            uma fonte segura, jamais de Access Keys da AWS (Req. 12.5).
        nome_iam_role: nome da IAM_Role_EC2 usado ao criar o verificador real.
        id_instancia_ec2: id da instância EC2 usado ao criar o verificador real.

    Returns:
        A instância :class:`FastAPI` do laboratório SNS, pronta para servir os
        endpoints de saúde, configuração, estatísticas, arquitetura e disparo.
    """
    app = FastAPI(
        title="AWS SNS Delivery Lab",
        description=(
            "API_Backend do laboratório didático de Amazon SNS (endpoints de saúde, "
            "configuração, estatísticas e arquitetura)."
        ),
    )

    estado_simulacao = estado_simulacao_sns or EstadoConfigSimulacaoSns()
    app.state.estado_simulacao_sns = estado_simulacao
    app.state.verificador_inicializacao_sns = (
        verificador_inicializacao_sns
        if verificador_inicializacao_sns is not None
        else VerificacaoInicializacaoSns(
            nome_iam_role=nome_iam_role,
            id_instancia_ec2=id_instancia_ec2,
        )
    )

    # Registro de observações: fonte concreta de /api/estatisticas e destino dos
    # Evento_Observado registrados pelos disparos (Entrega_Publicada/Confirmada).
    registro = registro_observacoes_sns or RegistroObservacoesSns()
    app.state.registro_observacoes_sns = registro

    # Estado "teste ativo" (botão desabilitado) do lado servidor (Req. 9.3, 9.4).
    estado_testes = estado_testes_sns or EstadoTestesSns()
    app.state.estado_testes_sns = estado_testes

    # Provedor de observações: por padrão, o próprio registro, de modo que cada
    # disparo passe a contar nas estatísticas (Req. 3.4, 3.5).
    provedor = (
        provedor_observacoes
        if provedor_observacoes is not None
        else registro.observacoes
    )
    app.state.estado_estatisticas_sns = (
        estado_estatisticas_sns
        if estado_estatisticas_sns is not None
        else EstadoEstatisticasSns(provedor)
    )

    # Serviço de disparo: montado com SnsGateway + VerificadorEntrega quando não
    # injetado. Em produção, os gateways são boto3 reais sem Access Keys; os
    # resolvedores de ARN/URL derivam dos nomes do laboratório e da região.
    app.state.servico_disparo_sns = servico_disparo_sns or _montar_servico_disparo(
        gateway=sns_gateway,
        verificador=verificador_entrega_sns,
        registro=registro,
        estado_simulacao=estado_simulacao,
        resolver_arn_topico=resolver_arn_topico,
        resolver_url_fila=resolver_url_fila,
    )

    # Serviço de comparação Standard x FIFO (Tarefa 13.2): montado com o SnsGateway
    # e um SqsLeituraGateway de leitura não destrutiva quando não injetado. Observa
    # a ordem de recebimento por leitura real, sem reordenar (Req. 7.7). O
    # Timeout_Verificacao_Entrega vem da Config_Simulacao (Req. 7.9).
    app.state.servico_comparacao_sns = servico_comparacao_sns or _montar_servico_comparacao(
        gateway=sns_gateway,
        leitura=sqs_leitura_gateway_sns,
        registro=registro,
        estado_simulacao=estado_simulacao,
        resolver_arn_topico=resolver_arn_topico,
        resolver_url_fila=resolver_url_fila,
    )

    # Serviço de teste de DLQ com Falha_Entrega_Controlada (Tarefa 13.3): montado
    # com o Gerenciador_Falha_Controlada (round-trip de Access_Policy_Fila), o
    # SnsGateway e o VerificadorEntrega (sobre o SqsLeituraGateway) quando não
    # injetado. Em produção, todos sobre boto3 sem Access Keys. O
    # Timeout_Verificacao_DLQ vem da Config_Simulacao (Req. 8.5).
    app.state.servico_dlq_sns = servico_dlq_sns or _montar_servico_dlq(
        gerenciador=gerenciador_falha_controlada_sns,
        gateway=sns_gateway,
        verificador=verificador_entrega_sns,
        leitura=sqs_leitura_gateway_sns,
        registro=registro,
        estado_simulacao=estado_simulacao,
        resolver_arn_topico=resolver_arn_topico,
        resolver_url_fila=resolver_url_fila,
    )

    # Controlador de autenticação do Dashboard com bloqueio por origem (Tarefa
    # 13.4). Injetável para testes (relógio controlável). Em produção, deixe None
    # para a fábrica criar um controlador padrão; para o laboratório, o modo aberto
    # (permitir_todas_origens=True) autoriza qualquer origem a tentar o login,
    # preservando intacta a lógica de bloqueio após 5 falhas consecutivas por 300 s
    # (Req. 12.6). A restrição de rede a origens autorizadas (Req. 12.7) é aplicada
    # no nível de infraestrutura (Security Group), conforme IMPLANTACAO.md.
    app.state.controlador_autenticacao_sns = (
        controlador_autenticacao_sns
        if controlador_autenticacao_sns is not None
        else ControladorAutenticacaoSns(permitir_todas_origens=True)
    )

    # Credenciais esperadas do Dashboard (Req. 12.5). Injetáveis para testes; em
    # produção vêm de uma fonte segura, nunca de Access Keys da AWS. O verificador
    # de credenciais é injetável, de modo que nenhum segredo fique fixado no código.
    app.state.credenciais_dashboard_sns = (
        credenciais_dashboard_sns
        if credenciais_dashboard_sns is not None
        else CredenciaisDashboardSns(usuario="admin", senha="trocar-no-console")
    )

    app.include_router(criar_roteador_config_saude_sns())
    app.include_router(criar_roteador_estatisticas_arquitetura_sns())
    app.include_router(criar_roteador_disparo_sns())
    app.include_router(criar_roteador_comparacao_sns())
    app.include_router(criar_roteador_dlq_sns())
    app.include_router(criar_roteador_autenticacao_sns())
    return app


# ---------------------------------------------------------------------------
# Resolvedores padrão de ARN de tópico e URL de fila (produção)
# ---------------------------------------------------------------------------
def _resolver_arn_topico_padrao(regiao: str = c.REGIAO_AWS) -> Callable[[str], str]:
    """Cria um resolvedor de ARN de tópico a partir do nome.

    O ARN de um tópico SNS tem o formato ``arn:aws:sns:<regiao>:<conta>:<nome>``.
    O número da conta **não** é fixado em código: é descoberto em tempo de execução
    via ``sts:GetCallerIdentity`` (a mesma IAM Role da EC2 que autentica o resto da
    aplicação), e memoizado para não repetir a chamada. Assim o laboratório funciona
    em qualquer conta sem configuração adicional, respeitando o princípio de não
    hardcodar credenciais nem identificadores (Req. 12.1, 12.2).
    """

    def _resolver(nome: str) -> str:
        return f"arn:aws:sns:{regiao}:{_obter_account_id(regiao)}:{nome}"

    return _resolver


def _resolver_url_fila_padrao(regiao: str = c.REGIAO_AWS) -> Callable[[str], str]:
    """Cria um resolvedor de URL de fila a partir do nome.

    A URL de uma fila SQS tem o formato
    ``https://sqs.<regiao>.amazonaws.com/<conta>/<nome>``. Como no resolvedor de ARN,
    o número da conta é descoberto via ``sts:GetCallerIdentity`` e memoizado, sem
    fixar o identificador em código.
    """

    def _resolver(nome: str) -> str:
        return f"https://sqs.{regiao}.amazonaws.com/{_obter_account_id(regiao)}/{nome}"

    return _resolver


@lru_cache(maxsize=4)
def _obter_account_id(regiao: str = c.REGIAO_AWS) -> str:
    """Descobre o ID da conta AWS via STS, memoizando o resultado.

    Usa a cadeia de credenciais padrão do ``boto3`` (IAM Role da EC2), sem Access
    Keys fixas. O resultado é cacheado por região com ``lru_cache`` para evitar uma
    chamada ao STS a cada disparo. Em produção na EC2, resolve o número real da
    conta do laboratório; em testes, os resolvedores são injetados e esta função
    não é chamada.
    """
    sts = boto3.client("sts", region_name=regiao)
    return sts.get_caller_identity()["Account"]


def _montar_servico_disparo(
    *,
    gateway: Optional[SnsGateway],
    verificador: Optional[VerificadorEntrega],
    registro: RegistroObservacoesSns,
    estado_simulacao: EstadoConfigSimulacaoSns,
    resolver_arn_topico: Optional[Callable[[str], str]],
    resolver_url_fila: Optional[Callable[[str], str]],
) -> ServicoDisparoSns:
    """Monta o :class:`ServicoDisparoSns` com os componentes reais ou injetados.

    O SnsGateway e o VerificadorEntrega (sobre o SqsLeituraGateway) são criados
    sobre boto3 sem Access Keys quando não injetados. O Timeout_Verificacao_Entrega
    é lido dinamicamente da Config_Simulacao a cada disparo (Req. 6.5).
    """
    gw = gateway if gateway is not None else SnsGateway()
    verif = (
        verificador
        if verificador is not None
        else VerificadorEntrega(SqsLeituraGateway())
    )
    return ServicoDisparoSns(
        gateway=gw,
        verificador=verif,
        registro=registro,
        resolver_arn_topico=(
            resolver_arn_topico
            if resolver_arn_topico is not None
            else _resolver_arn_topico_padrao()
        ),
        resolver_url_fila=(
            resolver_url_fila
            if resolver_url_fila is not None
            else _resolver_url_fila_padrao()
        ),
        fonte_timeout_entrega=(
            lambda: estado_simulacao.valores().timeout_verificacao_entrega_segundos
        ),
    )


def _montar_servico_dlq(
    *,
    gerenciador: Optional[GerenciadorFalhaControlada],
    gateway: Optional[SnsGateway],
    verificador: Optional[VerificadorEntrega],
    leitura: Optional[SqsLeituraGateway],
    registro: RegistroObservacoesSns,
    estado_simulacao: EstadoConfigSimulacaoSns,
    resolver_arn_topico: Optional[Callable[[str], str]],
    resolver_url_fila: Optional[Callable[[str], str]],
) -> ServicoDlqSns:
    """Monta o :class:`ServicoDlqSns` com os componentes reais ou injetados.

    O Gerenciador_Falha_Controlada, o SnsGateway e o VerificadorEntrega (sobre o
    SqsLeituraGateway) são criados sobre boto3 sem Access Keys quando não
    injetados. O Timeout_Verificacao_DLQ e o Timeout_Verificacao_Entrega são lidos
    dinamicamente da Config_Simulacao a cada teste (Req. 8.4, 8.5).
    """
    gerente = gerenciador if gerenciador is not None else GerenciadorFalhaControlada()
    gw = gateway if gateway is not None else SnsGateway()
    verif = (
        verificador
        if verificador is not None
        else VerificadorEntrega(leitura if leitura is not None else SqsLeituraGateway())
    )
    return ServicoDlqSns(
        gerenciador=gerente,
        gateway=gw,
        verificador=verif,
        registro=registro,
        resolver_arn_topico=(
            resolver_arn_topico
            if resolver_arn_topico is not None
            else _resolver_arn_topico_padrao()
        ),
        resolver_url_fila=(
            resolver_url_fila
            if resolver_url_fila is not None
            else _resolver_url_fila_padrao()
        ),
        fonte_timeout_dlq=(
            lambda: estado_simulacao.valores().timeout_verificacao_dlq_segundos
        ),
        fonte_timeout_entrega=(
            lambda: estado_simulacao.valores().timeout_verificacao_entrega_segundos
        ),
    )


def _montar_servico_comparacao(
    *,
    gateway: Optional[SnsGateway],
    leitura: Optional[SqsLeituraGateway],
    registro: RegistroObservacoesSns,
    estado_simulacao: EstadoConfigSimulacaoSns,
    resolver_arn_topico: Optional[Callable[[str], str]],
    resolver_url_fila: Optional[Callable[[str], str]],
) -> ServicoComparacaoSns:
    """Monta o :class:`ServicoComparacaoSns` com os componentes reais ou injetados.

    O SnsGateway e o SqsLeituraGateway (leitura não destrutiva) são criados sobre
    boto3 sem Access Keys quando não injetados. O Timeout_Verificacao_Entrega é
    lido dinamicamente da Config_Simulacao a cada comparação (Req. 7.9).
    """
    gw = gateway if gateway is not None else SnsGateway()
    leit = leitura if leitura is not None else SqsLeituraGateway()
    return ServicoComparacaoSns(
        gateway=gw,
        leitura=leit,
        registro=registro,
        resolver_arn_topico=(
            resolver_arn_topico
            if resolver_arn_topico is not None
            else _resolver_arn_topico_padrao()
        ),
        resolver_url_fila=(
            resolver_url_fila
            if resolver_url_fila is not None
            else _resolver_url_fila_padrao()
        ),
        fonte_timeout_entrega=(
            lambda: estado_simulacao.valores().timeout_verificacao_entrega_segundos
        ),
    )
