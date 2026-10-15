"""Testes de sanidade dos contratos base do SNS (Tarefa 1).

Verificam que as constantes do laboratório AWS SNS Delivery Lab e os tipos de
domínio (Cenario, EstadoEntrega, OrigemEvento) estão definidos conforme os
requisitos 1.1-1.7, 2.3, 2.5. São testes unitários simples; a lógica de domínio
(derivador de estado, validações, agregadores) é testada em tarefas posteriores.
"""

from __future__ import annotations

from app.dominio import constantes_sns as c
from app.dominio.tipos_sns import (
    CENARIOS_PERMITIDOS,
    ESTADOS_ENTREGA_PERMITIDOS,
    ORIGENS_EVENTO_PERMITIDAS,
    Cenario,
    EstadoEntrega,
    OrigemEvento,
)


def test_regiao_us_east_1() -> None:
    # Req. 1.1 a 1.6: toda a infraestrutura opera em us-east-1.
    assert c.REGIAO_AWS == "us-east-1"


def test_nomes_dos_dois_topicos() -> None:
    # Req. 1.1, 1.2: um tópico Standard e um FIFO (sufixo .fifo obrigatório).
    assert c.TOPICO_STANDARD == "delivery-standard"
    assert c.TOPICO_FIFO == "delivery-fifo.fifo"
    assert c.TOPICOS == (c.TOPICO_STANDARD, c.TOPICO_FIFO)


def test_seis_filas_de_destino() -> None:
    # Req. 1.3, 1.4: três filas de destino por cenário, correspondentes a
    # Destino_1, Destino_2 e Destino_3.
    assert c.FILAS_DESTINO_STANDARD == (
        "delivery-destino1-standard",
        "delivery-destino2-standard",
        "delivery-destino3-standard",
    )
    assert c.FILAS_DESTINO_FIFO == (
        "delivery-destino1-fifo.fifo",
        "delivery-destino2-fifo.fifo",
        "delivery-destino3-fifo.fifo",
    )
    assert len(c.FILAS_DESTINO) == 6
    assert c.FILAS_DESTINO_POR_TOPICO[c.TOPICO_STANDARD] == c.FILAS_DESTINO_STANDARD
    assert c.FILAS_DESTINO_POR_TOPICO[c.TOPICO_FIFO] == c.FILAS_DESTINO_FIFO


def test_nomes_das_duas_dlqs() -> None:
    # Req. 1.5, 1.6: nomes exatos das DLQs do SNS.
    assert c.DLQ_SNS_STANDARD == "delivery-sns-dlq-standard"
    assert c.DLQ_SNS_FIFO == "delivery-sns-dlq.fifo"
    assert c.DLQS == (c.DLQ_SNS_STANDARD, c.DLQ_SNS_FIFO)
    assert c.DLQ_POR_TOPICO[c.TOPICO_STANDARD] == c.DLQ_SNS_STANDARD
    assert c.DLQ_POR_TOPICO[c.TOPICO_FIFO] == c.DLQ_SNS_FIFO


def test_deduplicacao_por_conteudo_fifo_habilitada() -> None:
    # Req. 2.3: Deduplicacao_Por_Conteudo do Topico_FIFO habilitada por padrão.
    assert c.DEDUPLICACAO_POR_CONTEUDO_FIFO is True


def test_timeouts_de_simulacao_padroes_e_faixas() -> None:
    # Req. 2.5: Timeout_Verificacao_Entrega padrão 30s faixa 5-120s;
    # Timeout_Verificacao_DLQ padrão 120s faixa 30-300s.
    assert c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO == 30
    assert c.TIMEOUT_VERIFICACAO_ENTREGA_MIN == 5
    assert c.TIMEOUT_VERIFICACAO_ENTREGA_MAX == 120
    assert c.TIMEOUT_VERIFICACAO_DLQ_PADRAO == 120
    assert c.TIMEOUT_VERIFICACAO_DLQ_MIN == 30
    assert c.TIMEOUT_VERIFICACAO_DLQ_MAX == 300


def test_intervalo_atualizacao_e_long_polling() -> None:
    # Intervalo de atualização padrão 10s faixa 5-300s; Long Polling 1-20s.
    assert c.INTERVALO_ATUALIZACAO_PADRAO == 10
    assert c.INTERVALO_ATUALIZACAO_MIN == 5
    assert c.INTERVALO_ATUALIZACAO_MAX == 300
    assert c.LONG_POLLING_MIN == 1
    assert c.LONG_POLLING_MAX == 20


def test_tres_destinos_e_texto_visual() -> None:
    # Req. 4.5: os três destinos e o texto da notificação visual.
    assert c.DESTINOS == ("destino_1", "destino_2", "destino_3")
    assert set(c.TITULO_DESTINO) == set(c.DESTINOS)
    assert (
        c.TEXTO_NOTIFICACAO_VISUAL
        == "Seu pedido foi aprovado e está sendo preparado"
    )


def test_faixas_de_validacao_de_disparo() -> None:
    # Req. 4.1, 5.1, 5.2: ID_Pedido 1-80; MessageGroupId 1-128.
    assert c.ID_PEDIDO_TAMANHO_MIN == 1
    assert c.ID_PEDIDO_TAMANHO_MAX == 80
    assert c.MESSAGE_GROUP_ID_TAMANHO_MIN == 1
    assert c.MESSAGE_GROUP_ID_TAMANHO_MAX == 128


def test_cenario_tem_apenas_standard_e_fifo() -> None:
    assert {ce.value for ce in Cenario} == {"standard", "fifo"}
    assert CENARIOS_PERMITIDOS == frozenset(Cenario)


def test_estado_entrega_corresponde_ao_modelo_de_estados() -> None:
    valores = {e.value for e in EstadoEntrega}
    assert valores == {"Entrega_Publicada", "Entrega_Confirmada", "Não confirmado"}
    assert ESTADOS_ENTREGA_PERMITIDOS == frozenset(EstadoEntrega)


def test_origem_evento_tem_apenas_observado_e_inferido() -> None:
    assert {o.value for o in OrigemEvento} == {"Evento_Observado", "Evento_Inferido"}
    assert ORIGENS_EVENTO_PERMITIDAS == frozenset(OrigemEvento)
