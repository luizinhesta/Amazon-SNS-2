"""Serviço de teste de DLQ do SNS com Falha_Entrega_Controlada (Tarefa 13.3).

Orquestra o fluxo acionado pelo endpoint ``POST /api/dlq/simular-falha`` do
Dashboard, demonstrando — de forma **manual, controlada e reversível** — como o
Amazon SNS encaminha para a **DLQ do SNS compatível** uma mensagem que não
conseguiu entregar a uma assinatura cuja fila de destino passou a **negar** o
recebimento vindo do SNS (ver ``design.md`` → seção "Fluxo de
Falha_Entrega_Controlada → DLQ do SNS").

Fluxo (Req. 8.1 a 8.11):

1. **Acionamento manual com seleção de uma Assinatura_SNS.** O endpoint só
   executa por acionamento manual (Req. 8.10) e exige a seleção de uma
   Assinatura_SNS específica — identificada pelo cenário (Standard/FIFO) e pelo
   destino (Destino_1/2/3), que determinam a fila de destino alvo (Req. 8.1).
2. **Preparar a Falha_Entrega_Controlada.** Via Gerenciador_Falha_Controlada,
   **salva** a Access_Policy_Fila original da fila alvo e **aplica** o statement
   ``Deny`` temporário para ``sns.amazonaws.com`` com condição por ``SourceArn``
   do tópico correspondente, sem excluir filas nem assinaturas (Req. 8.2).
3. **Publicar a mensagem de teste** no tópico correspondente à assinatura
   selecionada (Req. 8.3).
4. **Verificar as demais assinaturas** do mesmo tópico (as outras duas filas de
   destino), que devem continuar confirmando a entrega (Req. 8.4), e a **DLQ
   compatível**, aguardando até o Timeout_Verificacao_DLQ (Req. 8.5). Ao
   confirmar na DLQ, registra a presença como **Evento_Observado** (Req. 8.6); se
   o timeout for atingido sem confirmação, o estado é **"Não confirmado"** (Req.
   8.7).
5. **Restaurar a Access_Policy_Fila ao final — SEMPRE.** A restauração ocorre em
   um bloco ``finally``, inclusive quando a publicação ou a verificação levantam
   erro, de modo que a fila nunca permaneça com o ``Deny`` por falha do fluxo
   (Req. 8.8). Se a restauração falhar, o resultado identifica a **fila afetada**
   e orienta a **restauração manual pelo Console AWS** em pt-BR (Req. 8.9).

O resultado reúne a assinatura selecionada, a fila de destino afetada, o
MessageId da publicação de teste, o estado na DLQ (Evento_Observado) com o nome
da DLQ, o resultado das demais assinaturas e o desfecho da restauração da policy,
além do **texto explicativo em pt-BR** sobre a DLQ do SNS (Req. 8.11).

Decisões de design:

- **Seleção da assinatura por cenário + destino.** Uma Assinatura_SNS do
  laboratório associa um tópico a uma fila de destino. O par (cenário, destino)
  identifica de forma estável a assinatura e, portanto, a fila alvo cujo
  recebimento será negado e as "demais assinaturas" (as outras duas filas do
  mesmo tópico) que devem continuar entregando (Req. 8.1, 8.4).
- **Restauração garantida.** A restauração vive em ``finally`` para honrar o
  Req. 8.8 mesmo diante de erro de publicação/verificação, preservando o
  princípio de não deixar recursos AWS em estado alterado por falha do fluxo.
- **Injeção de dependências.** O Gerenciador_Falha_Controlada, o SnsGateway, o
  Verificador_Entrega, o registro de observações, os resolvedores de ARN/URL e a
  fonte de Timeout_Verificacao_DLQ são injetados, permitindo testes de integração
  sem AWS real.
- **Erro original preservado.** Qualquer erro da AWS na publicação/verificação é
  repassado em ``erro_original`` sem mascarar, após a restauração garantida da
  policy.

Referências de requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10,
8.11, 9.1.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from app.acesso.gerenciador_falha_controlada_sns import (
    GerenciadorFalhaControlada,
    ResultadoRestauracao,
)
from app.acesso.sns_gateway import SnsGateway
from app.api.verificador_entrega_sns import VerificadorEntrega
from app.dominio import constantes_sns as c
from app.dominio.envelope_mensagem import PayloadAplicacao
from app.dominio.tipos_sns import Cenario, EstadoEntrega
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns

# Resolvedores injetáveis: nome do tópico → ARN e nome da fila → URL. Em produção
# são resolvidos via boto3; em testes, por fakes.
ResolvedorArnTopico = Callable[[str], str]
ResolvedorUrlFila = Callable[[str], str]
# Fonte do Timeout_Verificacao_DLQ vigente (Config_Simulacao) em segundos.
FonteTimeoutDlq = Callable[[], int]

# Texto explicativo em pt-BR sobre a DLQ do SNS, exibido no Dashboard (Req. 8.11).
TEXTO_EXPLICATIVO_DLQ: str = (
    "A DLQ (Dead-Letter Queue) do SNS é configurada na própria assinatura, por "
    "meio da Redrive_Policy_SNS. Quando o SNS não consegue entregar uma mensagem "
    "ao destino de uma assinatura (por exemplo, porque a Access_Policy_Fila passou "
    "a negar o recebimento vindo do SNS), ele, após as tentativas de reentrega, "
    "encaminha essa mensagem para a DLQ compatível com o tipo do tópico. Neste "
    "teste, a falha de entrega é controlada e reversível: ajustamos temporariamente "
    "a Access_Policy_Fila de uma única fila de destino para negar o SNS e, ao "
    "final, restauramos a policy original integralmente. As demais assinaturas do "
    "mesmo tópico continuam recebendo normalmente."
)

# Metadados estáticos por cenário (tópico, tipo textual, filas, DLQ compatível).
_TOPICO_POR_CENARIO: dict[Cenario, str] = {
    Cenario.STANDARD: c.TOPICO_STANDARD,
    Cenario.FIFO: c.TOPICO_FIFO,
}
_TIPO_TEXTUAL_POR_CENARIO: dict[Cenario, str] = {
    Cenario.STANDARD: "Standard",
    Cenario.FIFO: "FIFO",
}
_FILAS_POR_CENARIO: dict[Cenario, tuple[str, ...]] = {
    Cenario.STANDARD: c.FILAS_DESTINO_STANDARD,
    Cenario.FIFO: c.FILAS_DESTINO_FIFO,
}
_DLQ_POR_CENARIO: dict[Cenario, str] = {
    Cenario.STANDARD: c.DLQ_SNS_STANDARD,
    Cenario.FIFO: c.DLQ_SNS_FIFO,
}
# Índice de cada destino na tupla de filas do cenário (Destino_1 → 0, etc.).
_INDICE_DESTINO: dict[str, int] = {
    c.DESTINO_1: 0,
    c.DESTINO_2: 1,
    c.DESTINO_3: 2,
}


@dataclass(frozen=True)
class ResultadoDemaisAssinatura:
    """Resultado da verificação de uma das demais assinaturas do mesmo tópico (Req. 8.4).

    Attributes:
        destino: destino da assinatura verificada (``destino_1``/``2``/``3``).
        fila_destino: nome da fila de destino dessa assinatura.
        estado: estado derivado (``Entrega_Confirmada`` ou ``Não confirmado``).
        confirmada: ``True`` se houve leitura real correlacionada pelo ID_Pedido.
        message_id: MessageId lido na fila quando confirmada; ``None`` caso contrário.
    """

    destino: str
    fila_destino: str
    estado: EstadoEntrega
    confirmada: bool
    message_id: Optional[str] = None


@dataclass(frozen=True)
class ResultadoDlq:
    """Resultado completo do teste de DLQ com Falha_Entrega_Controlada (Req. 8.1-8.11).

    Attributes:
        cenario: cenário da assinatura selecionada (STANDARD ou FIFO).
        tipo: tipo textual do tópico ("Standard" ou "FIFO").
        topico: nome do tópico correspondente à assinatura selecionada.
        destino: destino da assinatura alvo (fila cujo recebimento foi negado).
        assinatura_selecionada: identificação textual da assinatura selecionada.
        fila_destino_afetada: nome da fila de destino cuja policy foi ajustada.
        id_pedido: ID_Pedido da mensagem de teste publicada.
        message_id_teste: MessageId retornado pelo SNS na publicação de teste.
        estado_dlq: estado na DLQ (``Entrega_Confirmada`` como Evento_Observado ou
            ``Não confirmado`` ao esgotar o Timeout_Verificacao_DLQ) (Req. 8.6, 8.7).
        dlq: nome da DLQ compatível verificada.
        dlq_message_id: MessageId constatado na DLQ quando confirmado.
        demais_assinaturas: resultado das demais assinaturas do mesmo tópico
            (devem continuar confirmando a entrega) (Req. 8.4).
        policy_restaurada: ``True`` se a Access_Policy_Fila foi restaurada (Req. 8.8).
        mensagem_restauracao: mensagem em pt-BR orientando a restauração manual
            quando a restauração falha (Req. 8.9); vazia em sucesso.
        texto_explicativo: texto em pt-BR sobre a DLQ do SNS (Req. 8.11).
        concluido: ``True`` quando o fluxo rodou sem erro de publicação/verificação.
        mensagem: mensagem geral em pt-BR (sucesso ou causa da interrupção).
        erro_original: erro original da AWS quando o fluxo é interrompido.
    """

    cenario: Cenario
    tipo: str
    topico: str
    destino: str
    assinatura_selecionada: str
    fila_destino_afetada: str
    id_pedido: str
    message_id_teste: Optional[str]
    estado_dlq: EstadoEntrega
    dlq: str
    dlq_message_id: Optional[str]
    demais_assinaturas: tuple[ResultadoDemaisAssinatura, ...]
    policy_restaurada: bool
    mensagem_restauracao: str = ""
    texto_explicativo: str = TEXTO_EXPLICATIVO_DLQ
    concluido: bool = True
    mensagem: str = ""
    erro_original: Optional[str] = None


class SelecaoAssinaturaInvalida(ValueError):
    """Erro de seleção inválida de Assinatura_SNS (cenário/destino desconhecidos)."""


class ServicoDlqSns:
    """Orquestra o teste de DLQ do SNS com Falha_Entrega_Controlada (Req. 8.1-8.11).

    Expõe :meth:`simular_falha`, usado pelo endpoint ``POST /api/dlq/simular-falha``.
    """

    def __init__(
        self,
        *,
        gerenciador: GerenciadorFalhaControlada,
        gateway: SnsGateway,
        verificador: VerificadorEntrega,
        registro: RegistroObservacoesSns,
        resolver_arn_topico: ResolvedorArnTopico,
        resolver_url_fila: ResolvedorUrlFila,
        fonte_timeout_dlq: FonteTimeoutDlq,
        fonte_timeout_entrega: Optional[Callable[[], int]] = None,
        agora: Optional[Callable[[], datetime]] = None,
    ) -> None:
        """Inicializa o serviço de teste de DLQ.

        Args:
            gerenciador: :class:`GerenciadorFalhaControlada` para o round-trip de
                Access_Policy_Fila (salvar/aplicar Deny/restaurar) (Req. 8.2, 8.8).
            gateway: :class:`SnsGateway` para publicar a mensagem de teste (Req. 8.3).
            verificador: :class:`VerificadorEntrega` para verificar as demais
                assinaturas (filas de destino) e a DLQ compatível (Req. 8.4, 8.5).
            registro: :class:`RegistroObservacoesSns` onde a presença na DLQ é
                registrada como Evento_Observado (Req. 8.6).
            resolver_arn_topico: resolve o ARN de um tópico pelo nome.
            resolver_url_fila: resolve a URL de uma fila (destino ou DLQ) pelo nome.
            fonte_timeout_dlq: callable que devolve o Timeout_Verificacao_DLQ
                vigente (Config_Simulacao), em segundos (Req. 8.5).
            fonte_timeout_entrega: callable que devolve o Timeout_Verificacao_Entrega
                vigente, aplicado à verificação das demais assinaturas (Req. 8.4);
                quando ``None``, usa o padrão da constante.
            agora: fábrica opcional do horário atual, usada no ``app_time`` do
                envelope (injeção para testes).
        """
        self._gerenciador = gerenciador
        self._gateway = gateway
        self._verificador = verificador
        self._registro = registro
        self._resolver_arn_topico = resolver_arn_topico
        self._resolver_url_fila = resolver_url_fila
        self._fonte_timeout_dlq = fonte_timeout_dlq
        self._fonte_timeout_entrega = fonte_timeout_entrega
        self._agora = agora if agora is not None else (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def simular_falha(
        self,
        cenario: Cenario,
        destino: str,
        id_pedido: str,
    ) -> ResultadoDlq:
        """Executa o teste de DLQ com Falha_Entrega_Controlada (Req. 8.1-8.11).

        Seleciona a Assinatura_SNS pelo par (cenário, destino), aplica o ``Deny``
        temporário à fila alvo, publica a mensagem de teste, verifica as demais
        assinaturas e a DLQ compatível e, **sempre**, restaura a Access_Policy_Fila
        ao final (Req. 8.8). Em erro de publicação/verificação, o resultado traz a
        causa em pt-BR e o erro original, após a restauração garantida.

        Args:
            cenario: cenário da assinatura selecionada (STANDARD ou FIFO).
            destino: destino da assinatura alvo (``destino_1``/``2``/``3``).
            id_pedido: ID_Pedido da mensagem de teste (chave de correlação).

        Returns:
            :class:`ResultadoDlq` com o desfecho completo do teste.

        Raises:
            SelecaoAssinaturaInvalida: se o par (cenário, destino) não identificar
                uma Assinatura_SNS do laboratório.
        """
        topico, topic_arn, fila_alvo, demais_filas, dlq = self._selecionar_assinatura(
            cenario, destino
        )
        queue_url_alvo = self._resolver_url_fila(fila_alvo)

        # Prepara a Falha_Entrega_Controlada: salva a policy original ANTES de
        # qualquer alteração e aplica o Deny temporário (Req. 8.2, 8.8).
        policy_original = self._gerenciador.salvar_policy_original(queue_url_alvo)
        self._gerenciador.aplicar_deny_temporario(queue_url_alvo, topic_arn)

        message_id_teste: Optional[str] = None
        estado_dlq = EstadoEntrega.NAO_CONFIRMADO
        dlq_message_id: Optional[str] = None
        demais: tuple[ResultadoDemaisAssinatura, ...] = ()
        erro_original: Optional[str] = None
        concluido = True

        try:
            message_id_teste = self._publicar_teste(
                cenario, topic_arn, topico, destino, id_pedido
            )
            demais = self._verificar_demais_assinaturas(
                cenario, demais_filas, id_pedido
            )
            estado_dlq, dlq_message_id = self._verificar_dlq(cenario, dlq, id_pedido)
        except Exception as erro:  # noqa: BLE001 — repassa a causa após restaurar
            concluido = False
            erro_original = repr(erro)
        finally:
            # Restauração garantida da Access_Policy_Fila (Req. 8.8), inclusive em
            # erro de publicação/verificação.
            restauracao = self._gerenciador.restaurar_policy(
                queue_url_alvo, policy_original
            )

        return self._montar_resultado(
            cenario=cenario,
            topico=topico,
            destino=destino,
            fila_alvo=fila_alvo,
            dlq=dlq,
            id_pedido=id_pedido,
            message_id_teste=message_id_teste,
            estado_dlq=estado_dlq,
            dlq_message_id=dlq_message_id,
            demais=demais,
            restauracao=restauracao,
            concluido=concluido,
            erro_original=erro_original,
        )

    # ------------------------------------------------------------------
    # Seleção da Assinatura_SNS (cenário + destino)
    # ------------------------------------------------------------------
    def _selecionar_assinatura(
        self, cenario: Cenario, destino: str
    ) -> tuple[str, str, str, tuple[str, ...], str]:
        """Resolve a assinatura selecionada e o tópico/filas/DLQ relacionados (Req. 8.1).

        Returns:
            Tupla ``(topico, topic_arn, fila_alvo, demais_filas, dlq)``, onde
            ``fila_alvo`` é a fila de destino da assinatura selecionada (a que terá
            o recebimento negado), ``demais_filas`` são as outras duas filas do
            mesmo tópico (demais assinaturas) e ``dlq`` é a DLQ compatível.

        Raises:
            SelecaoAssinaturaInvalida: se o destino não existir no cenário.
        """
        if destino not in _INDICE_DESTINO:
            raise SelecaoAssinaturaInvalida(
                f"Destino inválido: '{destino}'. Selecione uma Assinatura_SNS "
                f"válida (um dos destinos {', '.join(c.DESTINOS)})."
            )
        filas = _FILAS_POR_CENARIO[cenario]
        indice = _INDICE_DESTINO[destino]
        fila_alvo = filas[indice]
        demais_filas = tuple(f for i, f in enumerate(filas) if i != indice)
        topico = _TOPICO_POR_CENARIO[cenario]
        topic_arn = self._resolver_arn_topico(topico)
        dlq = _DLQ_POR_CENARIO[cenario]
        return topico, topic_arn, fila_alvo, demais_filas, dlq

    # ------------------------------------------------------------------
    # Publicação da mensagem de teste (Req. 8.3)
    # ------------------------------------------------------------------
    def _publicar_teste(
        self,
        cenario: Cenario,
        topic_arn: str,
        topico: str,
        destino: str,
        id_pedido: str,
    ) -> str:
        """Publica a mensagem de teste no tópico correspondente à assinatura (Req. 8.3).

        Registra a publicação como Evento_Observado de Entrega_Publicada e retorna
        o MessageId. No FIFO, usa um MessageGroupId único derivado do ID_Pedido
        (dedup por conteúdo habilitada → sem MessageDeduplicationId).
        """
        payload = PayloadAplicacao(
            id_pedido=id_pedido,
            cenario=cenario,
            destino=destino,
            titulo_destino=c.TITULO_DESTINO.get(destino, destino),
            conteudo=c.TEXTO_NOTIFICACAO_VISUAL,
            app_time=self._agora().isoformat(),
            sequencia=1,
        )
        if cenario is Cenario.FIFO:
            message_id = self._gateway.publicar_fifo(
                topic_arn, payload, f"dlq-{id_pedido}"
            )
        else:
            message_id = self._gateway.publicar_standard(topic_arn, payload)

        self._registro.registrar_publicacao(cenario, topico, id_pedido=id_pedido)
        return message_id

    # ------------------------------------------------------------------
    # Verificação das demais assinaturas (Req. 8.4)
    # ------------------------------------------------------------------
    def _verificar_demais_assinaturas(
        self,
        cenario: Cenario,
        demais_filas: tuple[str, ...],
        id_pedido: str,
    ) -> tuple[ResultadoDemaisAssinatura, ...]:
        """Verifica o resultado de entrega das demais assinaturas do tópico (Req. 8.4).

        As demais assinaturas (as outras duas filas de destino) continuam
        recebendo normalmente, pois apenas a fila alvo teve o recebimento negado.
        Cada confirmação por leitura real correlacionada registra uma
        Entrega_Confirmada como Evento_Observado.
        """
        timeout_entrega = (
            self._fonte_timeout_entrega()
            if self._fonte_timeout_entrega is not None
            else c.TIMEOUT_VERIFICACAO_ENTREGA_PADRAO
        )
        inverso_destino = {indice: dest for dest, indice in _INDICE_DESTINO.items()}
        filas_cenario = _FILAS_POR_CENARIO[cenario]

        resultados: list[ResultadoDemaisAssinatura] = []
        for fila in demais_filas:
            queue_url = self._resolver_url_fila(fila)
            resultado = self._verificador.verificar_entrega(
                queue_url, id_pedido, timeout_s=timeout_entrega
            )
            destino = inverso_destino[filas_cenario.index(fila)]
            if resultado.confirmada:
                self._registro.registrar_confirmacao(
                    cenario, fila, id_pedido=id_pedido
                )
            resultados.append(
                ResultadoDemaisAssinatura(
                    destino=destino,
                    fila_destino=fila,
                    estado=resultado.estado,
                    confirmada=resultado.confirmada,
                    message_id=resultado.message_id,
                )
            )
        return tuple(resultados)

    # ------------------------------------------------------------------
    # Verificação da DLQ compatível (Req. 8.5, 8.6, 8.7)
    # ------------------------------------------------------------------
    def _verificar_dlq(
        self, cenario: Cenario, dlq: str, id_pedido: str
    ) -> tuple[EstadoEntrega, Optional[str]]:
        """Verifica a presença da mensagem de teste na DLQ compatível (Req. 8.5-8.7).

        Aguarda até o Timeout_Verificacao_DLQ (Req. 8.5). Se confirmada, registra a
        presença como Evento_Observado (Req. 8.6) e devolve ``ENTREGA_CONFIRMADA``;
        se o timeout for atingido sem confirmação, devolve ``NAO_CONFIRMADO`` (Req.
        8.7).
        """
        dlq_url = self._resolver_url_fila(dlq)
        timeout_dlq = self._fonte_timeout_dlq()
        resultado = self._verificador.verificar_dlq(
            dlq_url, id_pedido, timeout_s=timeout_dlq
        )
        if resultado.confirmada:
            # Presença na DLQ constatada por leitura real: Evento_Observado (Req. 8.6).
            self._registro.registrar_dlq(cenario, dlq, id_pedido=id_pedido)
            return EstadoEntrega.ENTREGA_CONFIRMADA, resultado.message_id
        return EstadoEntrega.NAO_CONFIRMADO, None

    # ------------------------------------------------------------------
    # Montagem do resultado
    # ------------------------------------------------------------------
    def _montar_resultado(
        self,
        *,
        cenario: Cenario,
        topico: str,
        destino: str,
        fila_alvo: str,
        dlq: str,
        id_pedido: str,
        message_id_teste: Optional[str],
        estado_dlq: EstadoEntrega,
        dlq_message_id: Optional[str],
        demais: tuple[ResultadoDemaisAssinatura, ...],
        restauracao: ResultadoRestauracao,
        concluido: bool,
        erro_original: Optional[str],
    ) -> ResultadoDlq:
        """Monta o :class:`ResultadoDlq` com o desfecho do teste e da restauração."""
        assinatura = f"{topico} → {fila_alvo}"
        if not concluido:
            mensagem = (
                "Teste de DLQ interrompido: o tópico pode estar indisponível ou a "
                "autenticação com a AWS falhou durante a publicação ou a "
                "verificação. A Access_Policy_Fila foi restaurada ao final. "
                "Consulte o detalhe do erro original."
            )
        elif estado_dlq is EstadoEntrega.ENTREGA_CONFIRMADA:
            mensagem = (
                "Mensagem de teste confirmada na DLQ do SNS (Evento_Observado): o "
                "SNS encaminhou para a DLQ a mensagem que não conseguiu entregar à "
                "assinatura com recebimento negado."
            )
        else:
            mensagem = (
                "A mensagem de teste não foi confirmada na DLQ dentro do "
                "Timeout_Verificacao_DLQ: estado 'Não confirmado'. O encaminhamento "
                "para a DLQ depende da política de reentrega do SNS e pode levar "
                "mais tempo que o limite configurado."
            )

        return ResultadoDlq(
            cenario=cenario,
            tipo=_TIPO_TEXTUAL_POR_CENARIO[cenario],
            topico=topico,
            destino=destino,
            assinatura_selecionada=assinatura,
            fila_destino_afetada=fila_alvo,
            id_pedido=id_pedido,
            message_id_teste=message_id_teste,
            estado_dlq=estado_dlq,
            dlq=dlq,
            dlq_message_id=dlq_message_id,
            demais_assinaturas=demais,
            policy_restaurada=restauracao.sucesso,
            mensagem_restauracao=restauracao.mensagem,
            concluido=concluido,
            mensagem=mensagem,
            erro_original=erro_original,
        )
