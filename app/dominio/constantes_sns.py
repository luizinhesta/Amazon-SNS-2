"""Constantes do laboratório AWS SNS Delivery Lab.

Centraliza os valores fixos do laboratório didático de Amazon SNS — região,
nomes dos dois tópicos, nomes das seis filas de destino e das duas DLQs,
parâmetros de Config_Aplicada e Config_Simulacao, destinos do cenário delivery
e o texto da notificação visual.

A aplicação NÃO cria, modifica nem exclui recursos AWS, exceto o ajuste
temporário e reversível de Access_Policy_Fila do cenário de
Falha_Entrega_Controlada. Estas constantes apenas identificam e descrevem os
recursos criados manualmente pelo usuário no Console AWS.

Referências de requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.3, 2.5.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Região AWS
# ---------------------------------------------------------------------------
# Todo o laboratório opera na região Norte da Virgínia (Req. 1.1 a 1.6).
REGIAO_AWS: Final[str] = "us-east-1"

# ---------------------------------------------------------------------------
# Tópicos SNS (criados manualmente no Console AWS)
# ---------------------------------------------------------------------------
# Topico_Standard do tipo Standard (Req. 1.1).
TOPICO_STANDARD: Final[str] = "delivery-standard"
# Topico_FIFO do tipo FIFO (Req. 1.2). Tópicos FIFO exigem o sufixo ".fifo".
TOPICO_FIFO: Final[str] = "delivery-fifo.fifo"

# Conjunto dos dois tópicos esperados pelo laboratório.
TOPICOS: Final[tuple[str, ...]] = (TOPICO_STANDARD, TOPICO_FIFO)

# ---------------------------------------------------------------------------
# Filas de destino SQS (três por cenário, criadas manualmente)
# ---------------------------------------------------------------------------
# Fila_Destino_Standard — três filas Standard, uma por destino (Req. 1.3).
FILA_DESTINO1_STANDARD: Final[str] = "delivery-destino1-standard"
FILA_DESTINO2_STANDARD: Final[str] = "delivery-destino2-standard"
FILA_DESTINO3_STANDARD: Final[str] = "delivery-destino3-standard"

# Fila_Destino_FIFO — três filas FIFO, uma por destino (Req. 1.4). Filas FIFO
# exigem o sufixo ".fifo".
FILA_DESTINO1_FIFO: Final[str] = "delivery-destino1-fifo.fifo"
FILA_DESTINO2_FIFO: Final[str] = "delivery-destino2-fifo.fifo"
FILA_DESTINO3_FIFO: Final[str] = "delivery-destino3-fifo.fifo"

# As três filas de destino de cada cenário, na ordem Destino_1, Destino_2, Destino_3.
FILAS_DESTINO_STANDARD: Final[tuple[str, ...]] = (
    FILA_DESTINO1_STANDARD,
    FILA_DESTINO2_STANDARD,
    FILA_DESTINO3_STANDARD,
)
FILAS_DESTINO_FIFO: Final[tuple[str, ...]] = (
    FILA_DESTINO1_FIFO,
    FILA_DESTINO2_FIFO,
    FILA_DESTINO3_FIFO,
)

# Conjunto das seis filas de destino do laboratório.
FILAS_DESTINO: Final[tuple[str, ...]] = (
    *FILAS_DESTINO_STANDARD,
    *FILAS_DESTINO_FIFO,
)

# ---------------------------------------------------------------------------
# Dead-Letter Queues do SNS (compartilhadas por cenário, criadas manualmente)
# ---------------------------------------------------------------------------
# DLQ_SNS_Standard do tipo Standard (Req. 1.5).
DLQ_SNS_STANDARD: Final[str] = "delivery-sns-dlq-standard"
# DLQ_SNS_FIFO do tipo FIFO (Req. 1.6).
DLQ_SNS_FIFO: Final[str] = "delivery-sns-dlq.fifo"

# Conjunto das duas DLQs do laboratório.
DLQS: Final[tuple[str, ...]] = (DLQ_SNS_STANDARD, DLQ_SNS_FIFO)

# DLQ compatível com o tipo de cada tópico (Redrive_Policy_SNS das assinaturas).
DLQ_POR_TOPICO: Final[dict[str, str]] = {
    TOPICO_STANDARD: DLQ_SNS_STANDARD,
    TOPICO_FIFO: DLQ_SNS_FIFO,
}

# Filas de destino associadas a cada tópico (fan-out para os três destinos).
FILAS_DESTINO_POR_TOPICO: Final[dict[str, tuple[str, ...]]] = {
    TOPICO_STANDARD: FILAS_DESTINO_STANDARD,
    TOPICO_FIFO: FILAS_DESTINO_FIFO,
}

# ---------------------------------------------------------------------------
# Destinos do cenário delivery
# ---------------------------------------------------------------------------
# Os três destinos do fan-out, com rótulo exibido no Dashboard em pt-BR
# (Req. 4.4, 5.7).
DESTINO_1: Final[str] = "destino_1"
DESTINO_2: Final[str] = "destino_2"
DESTINO_3: Final[str] = "destino_3"

DESTINOS: Final[tuple[str, ...]] = (DESTINO_1, DESTINO_2, DESTINO_3)

# Títulos descritivos de cada destino (cenário delivery de comida).
TITULO_DESTINO: Final[dict[str, str]] = {
    DESTINO_1: "Confirmação da aprovação da compra",
    DESTINO_2: "Solicitação para a cozinha preparar o alimento",
    DESTINO_3: "Solicitação para o motoboy buscar o pedido",
}

# Texto da notificação visual exibida no Dashboard (apenas visual; o laboratório
# não envia SMS nem e-mails reais) (Req. 4.5, 4.6).
TEXTO_NOTIFICACAO_VISUAL: Final[str] = "Seu pedido foi aprovado e está sendo preparado"

# ---------------------------------------------------------------------------
# Config_Aplicada — parâmetros efetivamente configurados nos recursos AWS
# ---------------------------------------------------------------------------
# Alterá-los exige mudança no Console AWS (Req. 2.9); a aplicação só os exibe.

# Deduplicacao_Por_Conteudo do Topico_FIFO HABILITADA por padrão (Req. 2.3, 5.4,
# 11.3). Quando habilitada, o MessageDeduplicationId é gerado pelo conteúdo e não
# deve ser solicitado nem aceito no disparo FIFO.
DEDUPLICACAO_POR_CONTEUDO_FIFO: Final[bool] = True

# ---------------------------------------------------------------------------
# Config_Simulacao — parâmetros usados apenas pela lógica da aplicação
# ---------------------------------------------------------------------------
# Ajustáveis pelo usuário no Dashboard, dentro das faixas definidas (Req. 2.5,
# 2.7, 2.8).

# Timeout_Verificacao_Entrega: período máximo para confirmar a presença de uma
# mensagem em uma fila de destino (Req. 2.5).
TIMEOUT_VERIFICACAO_ENTREGA_PADRAO: Final[int] = 30
TIMEOUT_VERIFICACAO_ENTREGA_MIN: Final[int] = 5
TIMEOUT_VERIFICACAO_ENTREGA_MAX: Final[int] = 120

# Timeout_Verificacao_DLQ: período máximo para confirmar a presença de uma
# mensagem em uma DLQ (Req. 2.5).
TIMEOUT_VERIFICACAO_DLQ_PADRAO: Final[int] = 120
TIMEOUT_VERIFICACAO_DLQ_MIN: Final[int] = 30
TIMEOUT_VERIFICACAO_DLQ_MAX: Final[int] = 300

# Intervalo de atualização periódica das estatísticas no Dashboard (Req. 13.2).
INTERVALO_ATUALIZACAO_PADRAO: Final[int] = 10
INTERVALO_ATUALIZACAO_MIN: Final[int] = 5
INTERVALO_ATUALIZACAO_MAX: Final[int] = 300

# Long Polling (WaitTimeSeconds) usado na leitura não destrutiva das filas
# (Req. 10.5, 14.4).
LONG_POLLING_MIN: Final[int] = 1
LONG_POLLING_MAX: Final[int] = 20

# ---------------------------------------------------------------------------
# Validação de disparo
# ---------------------------------------------------------------------------
# Faixa de caracteres do ID_Pedido (Req. 4.1, 5.1).
ID_PEDIDO_TAMANHO_MIN: Final[int] = 1
ID_PEDIDO_TAMANHO_MAX: Final[int] = 80

# Faixa de caracteres do MessageGroupId em publicações FIFO (Req. 5.2).
MESSAGE_GROUP_ID_TAMANHO_MIN: Final[int] = 1
MESSAGE_GROUP_ID_TAMANHO_MAX: Final[int] = 128

# Faixa de caracteres do MessageDeduplicationId em publicações FIFO quando a
# Deduplicacao_Por_Conteudo está desabilitada (Req. 5.3).
MESSAGE_DEDUPLICATION_ID_TAMANHO_MIN: Final[int] = 1
MESSAGE_DEDUPLICATION_ID_TAMANHO_MAX: Final[int] = 128

# ---------------------------------------------------------------------------
# Segurança
# ---------------------------------------------------------------------------
# Bloqueio de autenticação após falhas consecutivas por origem (Req. 12.6).
MAX_TENTATIVAS_AUTENTICACAO: Final[int] = 5
BLOQUEIO_AUTENTICACAO_SEGUNDOS: Final[int] = 300

# ---------------------------------------------------------------------------
# Verificação de inicialização
# ---------------------------------------------------------------------------
# Timeout por recurso ao verificar existência e acessibilidade (Req. 1.9).
TIMEOUT_VERIFICACAO_RECURSO_SEGUNDOS: Final[int] = 10

# ---------------------------------------------------------------------------
# Mensagens padrão do cenário de comparação Standard x FIFO
# ---------------------------------------------------------------------------
# As três mensagens sequenciais publicadas em ambos os cenários (Req. 7.2, 7.3).
MENSAGENS_COMPARACAO: Final[tuple[str, ...]] = (
    "Pedido criado",
    "Compra aprovada",
    "Pedido em preparação",
)
