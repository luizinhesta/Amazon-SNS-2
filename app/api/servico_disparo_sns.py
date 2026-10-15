"""Serviço de disparo de publicação no SNS (Standard e FIFO) — Tarefa 13.1.

Orquestra o fluxo acionado pelos endpoints ``POST /api/disparar/standard`` e
``POST /api/disparar/fifo`` do Dashboard, reunindo os componentes já construídos
em tarefas anteriores sem reimplementar nenhuma regra de domínio:

1. **Validação do payload** (:func:`app.dominio.validacao_disparo.validar_disparo`):
   ID_Pedido de 1 a 80 caracteres e, no FIFO, MessageGroupId de 1 a 128
   caracteres; FIFO sem MessageGroupId é sempre rejeitado. Ao rejeitar, o serviço
   devolve os campos inválidos e as mensagens em pt-BR, **preservando** os valores
   informados, sem publicar nada (Req. 4.1, 4.7, 5.1, 5.2, 5.9, 11.5).
2. **Publicação via SnsGateway** (:meth:`SnsGateway.publicar_standard` /
   :meth:`SnsGateway.publicar_fifo`), que monta o envelope de aplicação
   (:class:`PayloadAplicacao`) com o ID_Pedido e o cenário nos MessageAttributes.
   No FIFO, o MessageGroupId é sempre informado e, como a Deduplicacao_Por_Conteudo
   está habilitada por padrão, o MessageDeduplicationId não é solicitado nem
   enviado (Req. 4.2, 5.5, 5.6, 11.3).
3. **Registro de Entrega_Publicada** com o MessageId retornado pelo SNS, como
   Evento_Observado, no registro de observações que alimenta ``/api/estatisticas``
   (Req. 4.3, 5.6).
4. **Verificação de entrega nas três filas de destino** (Destino_1/2/3) do
   cenário, por leitura real não destrutiva correlacionada pelo ID_Pedido
   (:class:`VerificadorEntrega`). Cada confirmação registra um Evento_Observado de
   Entrega_Confirmada; o Timeout_Verificacao_Entrega vigente vem da
   Config_Simulacao (Req. 4.3, 6.1, 6.3, 6.5).
5. **Falha de publicação**: o erro original da AWS é **repassado** pelo gateway;
   o serviço o registra e devolve uma indicação de falha em pt-BR, sem mascarar a
   causa (Req. 4.8, 5.10).

O cenário é **apenas visual**: o resultado carrega o texto da notificação
"Seu pedido foi aprovado e está sendo preparado" e os três destinos, mas o
laboratório **nunca** envia SMS ou e-mail reais (Req. 4.5, 4.6, 5.8).

Decisões de design:

- **Injeção de dependências.** O SnsGateway, o VerificadorEntrega, os resolvedores
  de ARN do tópico e de URL das filas e a fonte de Timeout_Verificacao são
  injetados, permitindo testes de integração com SNS/Verificador simulados, sem
  AWS real.
- **Lógica pura reutilizada.** A validação, a montagem do envelope e a derivação
  de estado permanecem nos módulos de domínio; este serviço apenas os coordena.

Referências de requisitos: 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 5.5, 5.6, 5.7, 5.8,
5.10, 6.1, 6.3, 6.5, 11.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from app.acesso.sns_gateway import SnsGateway
from app.api.verificador_entrega_sns import VerificadorEntrega
from app.dominio import constantes_sns as c
from app.dominio.envelope_mensagem import PayloadAplicacao
from app.dominio.tipos_sns import Cenario, EstadoEntrega
from app.dominio.validacao_disparo import PayloadDisparo, validar_disparo
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns

# Resolvedores injetáveis: nome do tópico → ARN e nome da fila → URL. Em produção
# são resolvidos via boto3 (list_topics / get_queue_url); em testes, por fakes.
ResolvedorArnTopico = Callable[[str], str]
ResolvedorUrlFila = Callable[[str], str]
# Fonte do Timeout_Verificacao_Entrega vigente (Config_Simulacao) em segundos.
FonteTimeoutEntrega = Callable[[], int]


@dataclass(frozen=True)
class ResultadoDestino:
    """Resultado da verificação de entrega em uma fila de destino do cenário.

    Attributes:
        destino: identificador do destino (``destino_1``/``destino_2``/``destino_3``).
        titulo_destino: título descritivo do destino, em pt-BR (Req. 4.4, 5.7).
        fila_destino: nome da fila de destino verificada.
        estado: estado derivado (``Entrega_Confirmada`` ou ``Não confirmado``).
        confirmada: ``True`` se e somente se houve leitura real correlacionada.
        message_id: MessageId da mensagem lida na fila, quando confirmada.
    """

    destino: str
    titulo_destino: str
    fila_destino: str
    estado: EstadoEntrega
    confirmada: bool
    message_id: Optional[str] = None


@dataclass(frozen=True)
class ResultadoDisparo:
    """Resultado de um disparo de publicação (Standard ou FIFO).

    Reúne o que o Dashboard precisa exibir após a publicação: o tópico, o tipo, o
    ID_Pedido, (o MessageGroupId no FIFO), o MessageId e os três destinos, além da
    notificação visual (Req. 4.4, 4.5, 5.7). Em rejeição de validação ou falha de
    publicação, carrega as mensagens em pt-BR correspondentes.

    Attributes:
        aceito: ``True`` quando o payload foi aceito e a publicação ocorreu.
        cenario: cenário do disparo (STANDARD ou FIFO).
        id_pedido: ID_Pedido informado (preservado).
        topico: nome do tópico utilizado.
        tipo: tipo textual do tópico ("Standard" ou "FIFO").
        message_group_id: MessageGroupId informado (apenas FIFO).
        message_id: MessageId retornado pelo SNS quando a publicação é aceita.
        destinos: resultado da verificação em cada uma das três filas de destino.
        notificacao_visual: texto da notificação apenas visual (Req. 4.5, 5.8).
        falha_publicacao: ``True`` quando a publicação foi tentada mas falhou.
        campos_invalidos: campos reprovados na validação (vazio quando aceito).
        mensagens: mensagens em pt-BR por campo inválido (validação).
        mensagem: mensagem geral em pt-BR (falha de publicação ou sucesso).
        erro_original: representação do erro original da AWS em falha (Req. 4.8).
    """

    aceito: bool
    cenario: Cenario
    id_pedido: str
    topico: Optional[str] = None
    tipo: Optional[str] = None
    message_group_id: Optional[str] = None
    message_id: Optional[str] = None
    destinos: tuple[ResultadoDestino, ...] = field(default_factory=tuple)
    notificacao_visual: str = ""
    falha_publicacao: bool = False
    campos_invalidos: tuple[str, ...] = field(default_factory=tuple)
    mensagens: dict[str, str] = field(default_factory=dict)
    mensagem: str = ""
    erro_original: Optional[str] = None


# Mapeamento estático de cenário → metadados do laboratório (tópico, tipo textual,
# filas de destino na ordem Destino_1..3 e DLQ compatível).
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


class ServicoDisparoSns:
    """Orquestra validação, publicação, registro e verificação de entrega.

    Reúne os componentes das tarefas anteriores e expõe :meth:`disparar`, usado
    pelos endpoints ``POST /api/disparar/standard`` e ``POST /api/disparar/fifo``.
    """

    def __init__(
        self,
        *,
        gateway: SnsGateway,
        verificador: VerificadorEntrega,
        registro: RegistroObservacoesSns,
        resolver_arn_topico: ResolvedorArnTopico,
        resolver_url_fila: ResolvedorUrlFila,
        fonte_timeout_entrega: FonteTimeoutEntrega,
        agora: Optional[Callable[[], datetime]] = None,
    ) -> None:
        """Inicializa o serviço de disparo.

        Args:
            gateway: :class:`SnsGateway` para publicar (repassa o erro original da
                AWS em falha — Req. 4.8, 5.10).
            verificador: :class:`VerificadorEntrega` para confirmar entregas por
                leitura real correlacionada pelo ID_Pedido (Req. 6.1, 6.3).
            registro: :class:`RegistroObservacoesSns` onde Entrega_Publicada e
                Entrega_Confirmada viram observações para ``/api/estatisticas``.
            resolver_arn_topico: resolve o ARN de um tópico pelo nome.
            resolver_url_fila: resolve a URL de uma fila de destino pelo nome.
            fonte_timeout_entrega: callable que devolve o Timeout_Verificacao_Entrega
                vigente (Config_Simulacao), em segundos (Req. 6.5).
            agora: fábrica opcional do horário atual (injeção para testes), usada no
                ``app_time`` do envelope.
        """
        self._gateway = gateway
        self._verificador = verificador
        self._registro = registro
        self._resolver_arn_topico = resolver_arn_topico
        self._resolver_url_fila = resolver_url_fila
        self._fonte_timeout_entrega = fonte_timeout_entrega
        self._agora = agora if agora is not None else (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def disparar(
        self,
        cenario: Cenario,
        id_pedido: str,
        message_group_id: Optional[str] = None,
    ) -> ResultadoDisparo:
        """Executa o disparo completo para um cenário (Standard ou FIFO).

        Fluxo: valida o payload; se rejeitado, devolve o resultado de rejeição sem
        publicar (Req. 4.7, 5.9). Caso aceito, publica via SnsGateway, registra a
        Entrega_Publicada com o MessageId (Req. 4.3, 5.6) e dispara a verificação de
        entrega nas três filas de destino (Req. 4.3, 6.1, 6.3). Em falha de
        publicação, registra o erro original e devolve a indicação de falha em
        pt-BR (Req. 4.8, 5.10).
        """
        payload_disparo = PayloadDisparo(
            cenario=cenario,
            id_pedido=id_pedido,
            message_group_id=message_group_id,
        )
        validacao = validar_disparo(payload_disparo)
        if not validacao.aceito:
            return self._resultado_rejeitado(cenario, payload_disparo, validacao)

        topico = _TOPICO_POR_CENARIO[cenario]
        try:
            message_id = self._publicar(cenario, topico, id_pedido, message_group_id)
        except Exception as erro:  # noqa: BLE001 — repassamos a causa (Req. 4.8, 5.10)
            return self._resultado_falha_publicacao(
                cenario, id_pedido, topico, message_group_id, erro
            )

        # Evento_Observado de Entrega_Publicada com o MessageId (Req. 4.3, 5.6).
        self._registro.registrar_publicacao(cenario, topico, id_pedido=id_pedido)

        destinos = self._verificar_entregas(cenario, id_pedido)

        return ResultadoDisparo(
            aceito=True,
            cenario=cenario,
            id_pedido=id_pedido,
            topico=topico,
            tipo=_TIPO_TEXTUAL_POR_CENARIO[cenario],
            message_group_id=message_group_id if cenario is Cenario.FIFO else None,
            message_id=message_id,
            destinos=destinos,
            notificacao_visual=c.TEXTO_NOTIFICACAO_VISUAL,
            mensagem="Publicação aceita pelo SNS (Entrega_Publicada).",
        )

    # ------------------------------------------------------------------
    # Etapas internas
    # ------------------------------------------------------------------
    def _publicar(
        self,
        cenario: Cenario,
        topico: str,
        id_pedido: str,
        message_group_id: Optional[str],
    ) -> str:
        """Publica no tópico do cenário e retorna o MessageId (Req. 4.2, 5.5).

        Monta um envelope de aplicação por destino não é necessário na publicação:
        o fan-out é feito pelo SNS. Publica um único envelope com o ID_Pedido e o
        cenário nos MessageAttributes; o Destino_1 é usado como título de
        referência do envelope (o texto visual é o mesmo do laboratório).
        """
        topic_arn = self._resolver_arn_topico(topico)
        payload = self._montar_payload(cenario, id_pedido)
        if cenario is Cenario.FIFO:
            # FIFO sempre com MessageGroupId; dedup por conteúdo habilitada → sem
            # MessageDeduplicationId (Req. 5.5, 11.3). O gateway rejeita FIFO sem
            # MessageGroupId antes da chamada (Req. 11.5), já garantido pela validação.
            return self._gateway.publicar_fifo(topic_arn, payload, message_group_id)
        return self._gateway.publicar_standard(topic_arn, payload)

    def _montar_payload(self, cenario: Cenario, id_pedido: str) -> PayloadAplicacao:
        """Monta o envelope de aplicação da publicação (Req. 4.2, 6.3)."""
        return PayloadAplicacao(
            id_pedido=id_pedido,
            cenario=cenario,
            destino=c.DESTINO_1,
            titulo_destino=c.TITULO_DESTINO[c.DESTINO_1],
            conteudo=c.TEXTO_NOTIFICACAO_VISUAL,
            app_time=self._agora().isoformat(),
            sequencia=1,
        )

    def _verificar_entregas(
        self, cenario: Cenario, id_pedido: str
    ) -> tuple[ResultadoDestino, ...]:
        """Verifica a entrega nas três filas de destino do cenário (Req. 4.3, 6.1, 6.3).

        Para cada fila (Destino_1..3), lê de forma não destrutiva correlacionando
        pelo ID_Pedido, aplicando o Timeout_Verificacao_Entrega vigente. Cada
        confirmação registra um Evento_Observado de Entrega_Confirmada com a fila e
        o ID_Pedido (Req. 6.3).
        """
        timeout_s = self._fonte_timeout_entrega()
        filas = _FILAS_POR_CENARIO[cenario]
        resultados: list[ResultadoDestino] = []
        for destino, fila in zip(c.DESTINOS, filas):
            queue_url = self._resolver_url_fila(fila)
            verificacao = self._verificador.verificar_entrega(
                queue_url, id_pedido, timeout_s=timeout_s
            )
            if verificacao.confirmada:
                self._registro.registrar_confirmacao(
                    cenario, fila, id_pedido=id_pedido
                )
            resultados.append(
                ResultadoDestino(
                    destino=destino,
                    titulo_destino=c.TITULO_DESTINO[destino],
                    fila_destino=fila,
                    estado=verificacao.estado,
                    confirmada=verificacao.confirmada,
                    message_id=verificacao.message_id,
                )
            )
        return tuple(resultados)

    # ------------------------------------------------------------------
    # Montagem de resultados de rejeição/falha
    # ------------------------------------------------------------------
    def _resultado_rejeitado(
        self,
        cenario: Cenario,
        payload: PayloadDisparo,
        validacao,
    ) -> ResultadoDisparo:
        """Monta o resultado de rejeição de validação, preservando os valores (Req. 4.7, 5.9)."""
        return ResultadoDisparo(
            aceito=False,
            cenario=cenario,
            id_pedido=payload.id_pedido,
            topico=_TOPICO_POR_CENARIO[cenario],
            tipo=_TIPO_TEXTUAL_POR_CENARIO[cenario],
            message_group_id=(
                payload.message_group_id if cenario is Cenario.FIFO else None
            ),
            campos_invalidos=validacao.campos_invalidos,
            mensagens=dict(validacao.mensagens),
            mensagem=(
                "Disparo rejeitado: há campos inválidos. Corrija os campos "
                "indicados e tente novamente."
            ),
        )

    def _resultado_falha_publicacao(
        self,
        cenario: Cenario,
        id_pedido: str,
        topico: str,
        message_group_id: Optional[str],
        erro: Exception,
    ) -> ResultadoDisparo:
        """Monta o resultado de falha de publicação, preservando o erro original (Req. 4.8, 5.10)."""
        return ResultadoDisparo(
            aceito=False,
            cenario=cenario,
            id_pedido=id_pedido,
            topico=topico,
            tipo=_TIPO_TEXTUAL_POR_CENARIO[cenario],
            message_group_id=message_group_id if cenario is Cenario.FIFO else None,
            falha_publicacao=True,
            mensagem=(
                "Falha ao publicar no tópico "
                f"'{topico}'. A publicação não foi aceita pelo SNS; nenhuma "
                "entrega foi confirmada. Consulte o detalhe do erro original."
            ),
            erro_original=repr(erro),
        )
