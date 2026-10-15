"""Testes unitários do derivador de estado de entrega (Tarefa 2.2).

Validam a função pura ``derivar_estado_entrega`` do laboratório AWS SNS Delivery
Lab, cobrindo o modelo de estados do design.md e os requisitos 6.1, 6.2, 6.6 e
4.3. Os testes de propriedade (Properties 1 e 4) são implementados nas tarefas
2.3 e 2.4; aqui cobrimos exemplos concretos e casos de borda.
"""

from __future__ import annotations

from app.dominio.derivador_estado_entrega import (
    LeituraFilaDestino,
    ObservacoesEntrega,
    derivar_estado_entrega,
)
from app.dominio.tipos_sns import EstadoEntrega


def test_publicacao_aceita_sozinha_nao_confirma_entrega() -> None:
    # Req. 6.2, 4.3: aceitar a publicação (MessageId) nunca basta para
    # Entrega_Confirmada — fica em Entrega_Publicada.
    obs = ObservacoesEntrega(id_pedido="pedido-0001", publicacao_aceita=True)
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_PUBLICADA


def test_estado_inicial_sem_sinais_e_entrega_publicada() -> None:
    # Sem publicação, leitura ou timeout: ponto de partida do modelo de estados.
    obs = ObservacoesEntrega(id_pedido="pedido-0001")
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_PUBLICADA


def test_leitura_correlacionada_confirma_entrega() -> None:
    # Req. 6.1: leitura real na fila de destino correlacionada pelo ID_Pedido.
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        publicacao_aceita=True,
        leituras=(
            LeituraFilaDestino(
                id_pedido="pedido-0001",
                fila_destino="delivery-destino1-standard",
                message_id="mid-1",
            ),
        ),
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_CONFIRMADA


def test_leitura_de_outro_pedido_nao_confirma() -> None:
    # Req. 6.1, 10.2: mensagens de terceiros (outro ID_Pedido) são ignoradas e
    # jamais confirmam a entrega do teste em execução.
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        publicacao_aceita=True,
        leituras=(LeituraFilaDestino(id_pedido="pedido-9999"),),
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_PUBLICADA


def test_timeout_sem_leitura_produz_nao_confirmado() -> None:
    # Req. 6.6, 7.9, 8.7: timeout sem leitura correlacionada → "Não confirmado",
    # nunca "entregue".
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        publicacao_aceita=True,
        timeout_atingido=True,
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.NAO_CONFIRMADO


def test_timeout_com_apenas_leitura_de_terceiros_produz_nao_confirmado() -> None:
    # Req. 6.6: leitura não correlacionada + timeout → "Não confirmado".
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        publicacao_aceita=True,
        leituras=(LeituraFilaDestino(id_pedido="pedido-9999"),),
        timeout_atingido=True,
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.NAO_CONFIRMADO


def test_leitura_correlacionada_prevalece_sobre_timeout() -> None:
    # A confirmação é um fato observado e tem precedência: mesmo com timeout
    # sinalizado, uma leitura correlacionada confirma a entrega (Req. 6.1).
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        publicacao_aceita=True,
        leituras=(LeituraFilaDestino(id_pedido="pedido-0001"),),
        timeout_atingido=True,
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_CONFIRMADA


def test_id_pedido_ausente_nunca_confirma() -> None:
    # Sem ID_Pedido do teste não há como correlacionar: nunca Entrega_Confirmada.
    obs = ObservacoesEntrega(
        id_pedido=None,
        leituras=(LeituraFilaDestino(id_pedido="pedido-0001"),),
        timeout_atingido=True,
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.NAO_CONFIRMADO


def test_leitura_sem_id_pedido_nao_correlaciona() -> None:
    # Uma leitura cujo envelope não trouxe ID_Pedido não correlaciona.
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        leituras=(LeituraFilaDestino(id_pedido=None),),
    )
    assert derivar_estado_entrega(obs) == EstadoEntrega.ENTREGA_PUBLICADA


def test_retorno_sempre_pertence_ao_conjunto_fechado() -> None:
    # A derivação sempre retorna exatamente um valor de EstadoEntrega.
    obs = ObservacoesEntrega(
        id_pedido="pedido-0001",
        leituras=(LeituraFilaDestino(id_pedido="pedido-0001"),),
    )
    assert derivar_estado_entrega(obs) in set(EstadoEntrega)
