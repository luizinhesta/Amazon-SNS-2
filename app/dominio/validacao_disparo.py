"""Validador de payload de disparo de publicação no SNS (Standard e FIFO).

Implementa a regra de aceitação de um disparo de publicação (Tarefa 3.1 do spec
``aws-sns-delivery-lab``):

- O ID_Pedido deve ter de 1 a 80 caracteres (Req. 4.1, 5.1).
- No cenário FIFO, o MessageGroupId deve estar presente e ter de 1 a 128
  caracteres (Req. 5.2, 11.5).
- Uma publicação FIFO sem MessageGroupId é sempre rejeitada (Req. 11.5).

A validação aceita se e somente se todos os campos aplicáveis são válidos. Ao
rejeitar, identifica ao menos um campo inválido e preserva os valores informados,
com mensagens em pt-BR (Req. 4.7, 5.9).

Este módulo é lógica de domínio pura (sem efeitos colaterais): recebe os valores
informados e devolve um resultado estruturado, sem publicar nada no SNS nem
acessar recursos AWS. Consome apenas as constantes de faixa de
:mod:`app.dominio.constantes_sns` e o enum :class:`~app.dominio.tipos_sns.Cenario`.

Correctness Property 6 (design.md): *Para qualquer* payload de disparo, a
validação deve aceitar se e somente se o ID_Pedido tiver de 1 a 80 caracteres e,
no cenário FIFO, o MessageGroupId tiver de 1 a 128 caracteres; uma publicação
FIFO sem MessageGroupId deve ser sempre rejeitada e, ao rejeitar, deve
identificar ao menos um campo inválido e preservar os valores informados.

Referências de requisitos: 4.1, 4.7, 5.1, 5.2, 5.9, 11.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.dominio import constantes_sns as c
from app.dominio.tipos_sns import Cenario

# Nomes dos campos usados no resultado e nas mensagens (rótulos em pt-BR estáveis
# para o Dashboard e para os testes).
CAMPO_ID_PEDIDO: str = "id_pedido"
CAMPO_MESSAGE_GROUP_ID: str = "message_group_id"


@dataclass(frozen=True)
class PayloadDisparo:
    """Valores informados em um disparo de publicação, preservados tal como vieram.

    Attributes:
        cenario: cenário do disparo (STANDARD ou FIFO).
        id_pedido: ID_Pedido informado pelo usuário (preservado como string).
        message_group_id: MessageGroupId informado; ``None`` quando ausente.
            Relevante apenas no cenário FIFO; ignorado no Standard.
    """

    cenario: Cenario
    id_pedido: str
    message_group_id: str | None = None


@dataclass(frozen=True)
class ResultadoValidacaoDisparo:
    """Resultado da validação de um disparo de publicação.

    Attributes:
        aceito: ``True`` se e somente se todos os campos aplicáveis são válidos.
        campos_invalidos: nomes dos campos considerados inválidos. Vazio quando
            aceito; contém ao menos um elemento quando rejeitado.
        mensagens: mensagens em pt-BR por campo inválido (``campo -> mensagem``).
            Vazio quando aceito.
        payload: o payload informado, preservado integralmente (Req. 4.7, 5.9).
    """

    aceito: bool
    payload: PayloadDisparo
    campos_invalidos: tuple[str, ...] = field(default_factory=tuple)
    mensagens: dict[str, str] = field(default_factory=dict)


def _comprimento(valor: str | None) -> int:
    """Comprimento em caracteres de ``valor``; 0 quando ``None``."""
    return len(valor) if valor is not None else 0


def validar_disparo(payload: PayloadDisparo) -> ResultadoValidacaoDisparo:
    """Valida um payload de disparo de publicação no SNS.

    Aceita se e somente se:

    - o ID_Pedido tiver de ``ID_PEDIDO_TAMANHO_MIN`` a ``ID_PEDIDO_TAMANHO_MAX``
      caracteres (1 a 80); e
    - no cenário FIFO, o MessageGroupId estiver presente e tiver de
      ``MESSAGE_GROUP_ID_TAMANHO_MIN`` a ``MESSAGE_GROUP_ID_TAMANHO_MAX``
      caracteres (1 a 128).

    No cenário Standard o MessageGroupId é ignorado. Uma publicação FIFO sem
    MessageGroupId é sempre rejeitada. Ao rejeitar, o resultado lista ao menos um
    campo inválido, traz a mensagem em pt-BR correspondente e preserva o payload
    informado.

    Args:
        payload: os valores informados no disparo.

    Returns:
        ResultadoValidacaoDisparo com ``aceito``, ``campos_invalidos``,
        ``mensagens`` e o ``payload`` preservado.
    """
    campos_invalidos: list[str] = []
    mensagens: dict[str, str] = {}

    # --- ID_Pedido: obrigatório em ambos os cenários (Req. 4.1, 5.1) ---
    tamanho_id = _comprimento(payload.id_pedido)
    if not (c.ID_PEDIDO_TAMANHO_MIN <= tamanho_id <= c.ID_PEDIDO_TAMANHO_MAX):
        campos_invalidos.append(CAMPO_ID_PEDIDO)
        mensagens[CAMPO_ID_PEDIDO] = (
            f"ID_Pedido inválido: informe de {c.ID_PEDIDO_TAMANHO_MIN} a "
            f"{c.ID_PEDIDO_TAMANHO_MAX} caracteres."
        )

    # --- MessageGroupId: obrigatório e limitado apenas no FIFO (Req. 5.2, 11.5) ---
    if payload.cenario is Cenario.FIFO:
        if payload.message_group_id is None or payload.message_group_id == "":
            # Publicação FIFO sem MessageGroupId é sempre rejeitada (Req. 11.5).
            campos_invalidos.append(CAMPO_MESSAGE_GROUP_ID)
            mensagens[CAMPO_MESSAGE_GROUP_ID] = (
                "MessageGroupId é obrigatório para publicação FIFO: informe de "
                f"{c.MESSAGE_GROUP_ID_TAMANHO_MIN} a "
                f"{c.MESSAGE_GROUP_ID_TAMANHO_MAX} caracteres."
            )
        else:
            tamanho_grupo = _comprimento(payload.message_group_id)
            if not (
                c.MESSAGE_GROUP_ID_TAMANHO_MIN
                <= tamanho_grupo
                <= c.MESSAGE_GROUP_ID_TAMANHO_MAX
            ):
                campos_invalidos.append(CAMPO_MESSAGE_GROUP_ID)
                mensagens[CAMPO_MESSAGE_GROUP_ID] = (
                    f"MessageGroupId inválido: informe de "
                    f"{c.MESSAGE_GROUP_ID_TAMANHO_MIN} a "
                    f"{c.MESSAGE_GROUP_ID_TAMANHO_MAX} caracteres."
                )

    aceito = len(campos_invalidos) == 0
    return ResultadoValidacaoDisparo(
        aceito=aceito,
        payload=payload,
        campos_invalidos=tuple(campos_invalidos),
        mensagens=mensagens,
    )
