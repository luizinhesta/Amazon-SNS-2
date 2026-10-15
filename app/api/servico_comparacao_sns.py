"""Serviço de comparação Standard x FIFO (Tarefa 13.2).

Orquestra o fluxo acionado pelo endpoint ``POST /api/comparar`` do Dashboard,
executando **dois testes independentes** — um no Topico_Standard e um no
Topico_FIFO — para evidenciar, de forma didaticamente honesta, a diferença de
garantia de ordenação entre os dois tipos de tópico (Req. 7.1).

Fluxo de cada teste:

1. **Publicação sequencial das três mensagens** "Pedido criado", "Compra
   aprovada" e "Pedido em preparação" (:data:`app.dominio.constantes_sns.
   MENSAGENS_COMPARACAO`), nessa ordem, via :class:`SnsGateway` (Req. 7.2, 7.3).
   No FIFO, as três mensagens usam um **único MessageGroupId** (Req. 7.3) e, como
   a Deduplicacao_Por_Conteudo está habilitada, nenhum MessageDeduplicationId é
   enviado — mas, como os três conteúdos são distintos, não há colisão de
   deduplicação. Cada mensagem recebe uma ``sequencia`` (1, 2, 3) no envelope,
   usada apenas para rotular a ordem de publicação.
2. **Registro de Entrega_Publicada** de cada mensagem com o MessageId retornado,
   como Evento_Observado, no registro de observações que alimenta
   ``/api/estatisticas`` (Req. 7.4).
3. **Observação da ordem de recebimento** por **leitura real** de uma fila de
   destino do cenário (Destino_1), correlacionando pelo ID_Pedido. A ordem de
   recebimento é apresentada **exatamente** na ordem em que as mensagens foram
   lidas, **sem reordenar nem simular** mensagens fora de ordem (Req. 7.7, 11.1).
   A cada mensagem correlacionada lida, registra-se um Evento_Observado de
   Entrega_Confirmada (Req. 7.4).
4. **Estado "Não confirmado"** para cada uma das três mensagens que **não** forem
   confirmadas na fila de destino dentro do Timeout_Verificacao_Entrega (Req. 7.9).

O resultado reúne, para cada teste, a ordem de publicação, a ordem de recebimento,
o MessageId de cada mensagem e o tipo do tópico, para o Dashboard exibir os dois
testes **lado a lado** (Req. 7.4, 7.5), acompanhados do texto explicativo em pt-BR
de que o Topico_Standard **não garante ordenação**, mesmo quando as mensagens
chegam na sequência correta (Req. 7.6).

Interrupção com causa em pt-BR (Req. 7.8): se um tópico estiver indisponível ou a
autenticação falhar durante a comparação (erro repassado pelo SnsGateway na
publicação ou pelo gateway de leitura na verificação), o serviço **interrompe** o
teste e devolve um resultado de interrupção com a causa em pt-BR, sem mascarar o
erro original da AWS.

Decisões de design:

- **Leitura direta da fila para observar a ordem.** O :class:`VerificadorEntrega`
  (usado no disparo) devolve apenas a *primeira* mensagem correlacionada, o que
  não permite observar a **sequência** das três mensagens. Por isso a comparação
  lê a fila de destino diretamente pelo :class:`SqsLeituraGateway`, repetindo a
  leitura até coletar as três mensagens do ID_Pedido ou atingir o
  Timeout_Verificacao_Entrega, preservando a ordem exata de leitura (Req. 7.7,
  11.1). A leitura é **não destrutiva** (nunca ``DeleteMessage``).
- **Injeção de dependências.** O SnsGateway, o gateway de leitura, os resolvedores
  de ARN do tópico e de URL das filas, a fonte de Timeout_Verificacao_Entrega, o
  relógio e a espera entre tentativas são injetados, permitindo testes de
  integração sem AWS real.
- **Lógica pura reutilizada.** A apresentação da ordem FIFO reusa
  :func:`app.dominio.apresentacao_ordem_fifo.agrupar_ordem_recebimento_fifo`
  (apresenta sem reordenar). O estado "Não confirmado" reusa o enum
  :class:`EstadoEntrega`.

Referências de requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from app.acesso.sns_gateway import SnsGateway
from app.acesso.sqs_leitura_gateway_sns import (
    MensagemVisualizada,
    SqsLeituraGateway,
    VISIBILITY_TIMEOUT_CURTO_PADRAO,
)
from app.dominio import constantes_sns as c
from app.dominio.apresentacao_ordem_fifo import (
    MensagemLidaFifo,
    agrupar_ordem_recebimento_fifo,
)
from app.dominio.envelope_mensagem import (
    CAMPO_CONTEUDO,
    PayloadAplicacao,
    extrair_id_pedido,
)
from app.dominio.tipos_sns import Cenario, EstadoEntrega
from app.observabilidade.registro_observacoes_sns import RegistroObservacoesSns

import json

# Resolvedores injetáveis: nome do tópico → ARN e nome da fila → URL. Em produção
# são resolvidos via boto3; em testes, por fakes.
ResolvedorArnTopico = Callable[[str], str]
ResolvedorUrlFila = Callable[[str], str]
# Fonte do Timeout_Verificacao_Entrega vigente (Config_Simulacao) em segundos.
FonteTimeoutEntrega = Callable[[], int]

# Texto explicativo em pt-BR exibido na comparação: o Topico_Standard NÃO garante
# ordenação, mesmo quando as mensagens chegam na sequência correta (Req. 7.6).
TEXTO_OBSERVACAO_ORDENACAO: str = (
    "O Topico_Standard não garante ordenação das mensagens: mesmo quando elas "
    "chegam na sequência correta neste teste, isso é apenas uma possibilidade, não "
    "uma garantia. Já o Topico_FIFO garante a ordenação das mensagens dentro de um "
    "mesmo MessageGroupId. Esta comparação apresenta a ordem de recebimento "
    "observada por leitura real das filas de destino, sem reordenar nem simular "
    "mensagens fora de ordem."
)


@dataclass(frozen=True)
class MensagemComparacao:
    """Uma das três mensagens de um teste de comparação (Req. 7.4).

    Attributes:
        sequencia: ordem de publicação (1, 2, 3).
        conteudo: conteúdo da mensagem ("Pedido criado", etc.).
        message_id: MessageId retornado pelo SNS na publicação.
    """

    sequencia: int
    conteudo: str
    message_id: str


@dataclass(frozen=True)
class ItemRecebimento:
    """Uma mensagem observada na ordem de recebimento de um teste (Req. 7.4, 7.9).

    Attributes:
        conteudo: conteúdo da mensagem lida, ou ``None`` quando não confirmada.
        message_id: MessageId lido na fila, quando confirmada.
        estado: ``Entrega_Confirmada`` quando lida, ``Não confirmado`` caso
            contrário (Req. 7.9).
        confirmada: ``True`` se e somente se houve leitura real correlacionada.
    """

    conteudo: Optional[str]
    message_id: Optional[str]
    estado: EstadoEntrega
    confirmada: bool


@dataclass(frozen=True)
class ResultadoTesteComparacao:
    """Resultado de um dos dois testes independentes (Standard ou FIFO).

    Attributes:
        cenario: cenário do teste (STANDARD ou FIFO).
        tipo: tipo textual do tópico ("Standard" ou "FIFO").
        topico: nome do tópico utilizado.
        id_pedido: ID_Pedido correlacionado neste teste.
        message_group_id: MessageGroupId único usado (apenas FIFO).
        ordem_publicacao: as três mensagens na ordem de publicação (Req. 7.4).
        ordem_recebimento: as mensagens observadas na ordem de recebimento, sem
            reordenar; mensagens não confirmadas aparecem como "Não confirmado"
            (Req. 7.4, 7.7, 7.9).
    """

    cenario: Cenario
    tipo: str
    topico: str
    id_pedido: str
    message_group_id: Optional[str]
    ordem_publicacao: tuple[MensagemComparacao, ...]
    ordem_recebimento: tuple[ItemRecebimento, ...]


@dataclass(frozen=True)
class ResultadoComparacao:
    """Resultado completo da comparação Standard x FIFO (Req. 7.5, 7.6, 7.8).

    Attributes:
        concluido: ``True`` quando os dois testes rodaram sem interrupção.
        standard: resultado do teste Standard (``None`` se interrompido antes).
        fifo: resultado do teste FIFO (``None`` se interrompido antes).
        observacao: texto explicativo em pt-BR sobre a ausência de garantia de
            ordenação no Standard (Req. 7.6).
        interrompido: ``True`` quando a comparação foi interrompida (Req. 7.8).
        mensagem: mensagem em pt-BR; vazia em sucesso e, em interrupção, indicando
            a causa (tópico indisponível ou falha de autenticação) (Req. 7.8).
        erro_original: representação do erro original da AWS em interrupção.
    """

    concluido: bool
    standard: Optional[ResultadoTesteComparacao]
    fifo: Optional[ResultadoTesteComparacao]
    observacao: str = TEXTO_OBSERVACAO_ORDENACAO
    interrompido: bool = False
    mensagem: str = ""
    erro_original: Optional[str] = None


# Metadados estáticos por cenário (tópico, tipo textual, filas de destino).
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


class ServicoComparacaoSns:
    """Orquestra os dois testes independentes da comparação Standard x FIFO.

    Expõe :meth:`comparar`, usado pelo endpoint ``POST /api/comparar``.
    """

    def __init__(
        self,
        *,
        gateway: SnsGateway,
        leitura: SqsLeituraGateway,
        registro: RegistroObservacoesSns,
        resolver_arn_topico: ResolvedorArnTopico,
        resolver_url_fila: ResolvedorUrlFila,
        fonte_timeout_entrega: FonteTimeoutEntrega,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        pausa_entre_tentativas_s: float = 0.0,
        agora: Optional[Callable[[], datetime]] = None,
    ) -> None:
        """Inicializa o serviço de comparação.

        Args:
            gateway: :class:`SnsGateway` para publicar (repassa o erro original da
                AWS em falha — Req. 7.8).
            leitura: :class:`SqsLeituraGateway` de leitura não destrutiva para
                observar a ordem de recebimento (Req. 7.7).
            registro: :class:`RegistroObservacoesSns` onde Entrega_Publicada e
                Entrega_Confirmada viram observações para ``/api/estatisticas``.
            resolver_arn_topico: resolve o ARN de um tópico pelo nome.
            resolver_url_fila: resolve a URL de uma fila de destino pelo nome.
            fonte_timeout_entrega: callable que devolve o Timeout_Verificacao_Entrega
                vigente (Config_Simulacao), em segundos (Req. 7.9).
            relogio: relógio monotônico injetável (determinismo em testes).
            dormir: função de espera entre tentativas (injeção para testes).
            pausa_entre_tentativas_s: pausa entre leituras quando ainda falta
                coletar mensagens e há orçamento de tempo.
            agora: fábrica opcional do horário atual, usada no ``app_time`` do
                envelope (injeção para testes).
        """
        self._gateway = gateway
        self._leitura = leitura
        self._registro = registro
        self._resolver_arn_topico = resolver_arn_topico
        self._resolver_url_fila = resolver_url_fila
        self._fonte_timeout_entrega = fonte_timeout_entrega
        self._relogio = relogio
        self._dormir = dormir
        self._pausa_entre_tentativas_s = pausa_entre_tentativas_s
        self._agora = agora if agora is not None else (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def comparar(
        self,
        id_pedido: str,
        message_group_id: Optional[str] = None,
    ) -> ResultadoComparacao:
        """Executa os dois testes independentes (Standard e FIFO) e compara (Req. 7.1-7.9).

        O teste Standard é executado primeiro, seguido do teste FIFO (um único
        MessageGroupId). Se um tópico estiver indisponível ou a autenticação falhar
        em qualquer etapa, a comparação é **interrompida** com a causa em pt-BR,
        sem mascarar o erro original (Req. 7.8).

        Args:
            id_pedido: ID_Pedido usado para correlacionar as três mensagens em
                ambos os cenários.
            message_group_id: MessageGroupId único do teste FIFO; quando ``None``,
                um valor derivado do ID_Pedido é usado (Req. 7.3).

        Returns:
            :class:`ResultadoComparacao` com os dois testes lado a lado ou a
            indicação de interrupção com a causa.
        """
        mgid = message_group_id or f"comparacao-{id_pedido}"

        resultado_standard: Optional[ResultadoTesteComparacao] = None
        resultado_fifo: Optional[ResultadoTesteComparacao] = None
        try:
            resultado_standard = self._executar_teste(
                Cenario.STANDARD, id_pedido, message_group_id=None
            )
            resultado_fifo = self._executar_teste(
                Cenario.FIFO, id_pedido, message_group_id=mgid
            )
        except Exception as erro:  # noqa: BLE001 — interrompe com a causa (Req. 7.8)
            return self._resultado_interrompido(
                resultado_standard, resultado_fifo, erro
            )

        return ResultadoComparacao(
            concluido=True,
            standard=resultado_standard,
            fifo=resultado_fifo,
        )

    # ------------------------------------------------------------------
    # Execução de um teste (Standard ou FIFO)
    # ------------------------------------------------------------------
    def _executar_teste(
        self,
        cenario: Cenario,
        id_pedido: str,
        message_group_id: Optional[str],
    ) -> ResultadoTesteComparacao:
        """Publica as três mensagens sequenciais e observa a ordem de recebimento.

        Publica "Pedido criado", "Compra aprovada" e "Pedido em preparação" nessa
        ordem (Req. 7.2, 7.3), registra cada Entrega_Publicada (Req. 7.4) e observa
        a ordem de recebimento por leitura real correlacionada pelo ID_Pedido, sem
        reordenar (Req. 7.7). As mensagens não confirmadas dentro do
        Timeout_Verificacao_Entrega aparecem como "Não confirmado" (Req. 7.9).
        """
        topico = _TOPICO_POR_CENARIO[cenario]
        topic_arn = self._resolver_arn_topico(topico)

        ordem_publicacao = self._publicar_sequencia(
            cenario, topic_arn, topico, id_pedido, message_group_id
        )

        ordem_recebimento = self._observar_ordem_recebimento(
            cenario, id_pedido
        )

        return ResultadoTesteComparacao(
            cenario=cenario,
            tipo=_TIPO_TEXTUAL_POR_CENARIO[cenario],
            topico=topico,
            id_pedido=id_pedido,
            message_group_id=message_group_id,
            ordem_publicacao=ordem_publicacao,
            ordem_recebimento=ordem_recebimento,
        )

    def _publicar_sequencia(
        self,
        cenario: Cenario,
        topic_arn: str,
        topico: str,
        id_pedido: str,
        message_group_id: Optional[str],
    ) -> tuple[MensagemComparacao, ...]:
        """Publica as três mensagens em sequência e retorna a ordem de publicação.

        Cada mensagem carrega uma ``sequencia`` crescente (1, 2, 3) e o conteúdo da
        posição correspondente de :data:`MENSAGENS_COMPARACAO`. No FIFO, todas usam
        o mesmo ``message_group_id`` (Req. 7.3). Qualquer falha de publicação
        propaga o erro original da AWS, para que :meth:`comparar` interrompa com a
        causa (Req. 7.8).
        """
        publicadas: list[MensagemComparacao] = []
        for indice, conteudo in enumerate(c.MENSAGENS_COMPARACAO):
            sequencia = indice + 1
            payload = PayloadAplicacao(
                id_pedido=id_pedido,
                cenario=cenario,
                destino=c.DESTINO_1,
                titulo_destino=c.TITULO_DESTINO[c.DESTINO_1],
                conteudo=conteudo,
                app_time=self._agora().isoformat(),
                sequencia=sequencia,
            )
            if cenario is Cenario.FIFO:
                message_id = self._gateway.publicar_fifo(
                    topic_arn, payload, message_group_id
                )
            else:
                message_id = self._gateway.publicar_standard(topic_arn, payload)

            # Evento_Observado de Entrega_Publicada com o MessageId (Req. 7.4).
            self._registro.registrar_publicacao(cenario, topico, id_pedido=id_pedido)
            publicadas.append(
                MensagemComparacao(
                    sequencia=sequencia, conteudo=conteudo, message_id=message_id
                )
            )
        return tuple(publicadas)

    # ------------------------------------------------------------------
    # Observação da ordem de recebimento (leitura real, sem reordenar)
    # ------------------------------------------------------------------
    def _observar_ordem_recebimento(
        self, cenario: Cenario, id_pedido: str
    ) -> tuple[ItemRecebimento, ...]:
        """Lê a fila de destino do cenário e devolve a ordem de recebimento observada.

        Lê de forma não destrutiva a fila Destino_1 do cenário, repetidamente, até
        coletar as três mensagens correlacionadas pelo ID_Pedido ou atingir o
        Timeout_Verificacao_Entrega. A ordem de recebimento é apresentada
        **exatamente** na ordem de leitura, sem reordenar (Req. 7.7, 11.1). Para o
        FIFO, a apresentação reusa :func:`agrupar_ordem_recebimento_fifo` (que
        também preserva a ordem). As posições não confirmadas aparecem como "Não
        confirmado" (Req. 7.9).

        Cada mensagem correlacionada registra um Evento_Observado de
        Entrega_Confirmada (Req. 7.4).
        """
        fila = _FILAS_POR_CENARIO[cenario][0]  # Destino_1 do cenário
        queue_url = self._resolver_url_fila(fila)
        timeout_s = self._fonte_timeout_entrega()
        total_esperado = len(c.MENSAGENS_COMPARACAO)

        lidas = self._ler_correlacionadas(
            queue_url, id_pedido, total_esperado, timeout_s
        )

        # Registra uma Entrega_Confirmada por mensagem correlacionada lida (Req. 7.4).
        for _ in lidas:
            self._registro.registrar_confirmacao(cenario, fila, id_pedido=id_pedido)

        if cenario is Cenario.FIFO:
            conteudos_mids = self._ordem_recebimento_fifo(lidas, id_pedido)
        else:
            conteudos_mids = [
                (self._conteudo(m), m.message_id or None) for m in lidas
            ]

        itens: list[ItemRecebimento] = [
            ItemRecebimento(
                conteudo=conteudo,
                message_id=message_id,
                estado=EstadoEntrega.ENTREGA_CONFIRMADA,
                confirmada=True,
            )
            for conteudo, message_id in conteudos_mids
        ]

        # Completa com "Não confirmado" para cada mensagem não observada dentro do
        # Timeout_Verificacao_Entrega (Req. 7.9).
        faltantes = total_esperado - len(itens)
        for _ in range(max(faltantes, 0)):
            itens.append(
                ItemRecebimento(
                    conteudo=None,
                    message_id=None,
                    estado=EstadoEntrega.NAO_CONFIRMADO,
                    confirmada=False,
                )
            )
        return tuple(itens)

    def _ler_correlacionadas(
        self,
        queue_url: str,
        id_pedido: str,
        total_esperado: int,
        timeout_s: int,
    ) -> list[MensagemVisualizada]:
        """Lê a fila até coletar ``total_esperado`` correlacionadas ou esgotar o timeout.

        Acumula, **na ordem de leitura**, as mensagens cujo ID_Pedido correlaciona
        com ``id_pedido``, ignorando e preservando as demais (não destrutivo). Um
        recebimento vazio apenas provoca nova tentativa, sem erro (Req. 10.6).
        Qualquer erro da AWS propaga intacto, para interromper a comparação com a
        causa (Req. 7.8).
        """
        inicio = self._relogio()
        coletadas: list[MensagemVisualizada] = []
        vistos_message_ids: set[str] = set()

        while True:
            mensagens = self._leitura.receber_para_visualizacao(
                queue_url,
                wait_time_seconds=c.LONG_POLLING_MAX,
                visibility_timeout_s=VISIBILITY_TIMEOUT_CURTO_PADRAO,
            )
            for mensagem in mensagens:
                if self._correlaciona(mensagem, id_pedido):
                    # Evita contabilizar a mesma mensagem duas vezes caso a leitura
                    # não destrutiva a devolva novamente antes do fim do teste.
                    if mensagem.message_id and mensagem.message_id in vistos_message_ids:
                        continue
                    if mensagem.message_id:
                        vistos_message_ids.add(mensagem.message_id)
                    coletadas.append(mensagem)

            if len(coletadas) >= total_esperado:
                return coletadas[:total_esperado]

            if (self._relogio() - inicio) >= timeout_s:
                return coletadas

            if self._pausa_entre_tentativas_s > 0:
                self._dormir(self._pausa_entre_tentativas_s)

    def _ordem_recebimento_fifo(
        self, lidas: list[MensagemVisualizada], id_pedido: str
    ) -> list[tuple[Optional[str], Optional[str]]]:
        """Apresenta a ordem FIFO reusando a lógica pura, sem reordenar (Req. 11.1)."""
        mensagens_fifo = [
            MensagemLidaFifo(
                message_group_id=id_pedido,
                conteudo=self._conteudo(m) or "",
                message_id=m.message_id or None,
                id_pedido=id_pedido,
            )
            for m in lidas
        ]
        grupos = agrupar_ordem_recebimento_fifo(mensagens_fifo)
        resultado: list[tuple[Optional[str], Optional[str]]] = []
        for grupo in grupos:
            for conteudo, message_id in zip(grupo.ordem_recebimento, grupo.message_ids):
                resultado.append((conteudo or None, message_id))
        return resultado

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    @staticmethod
    def _correlaciona(mensagem: MensagemVisualizada, id_pedido: str) -> bool:
        """Indica se a mensagem lida correlaciona com o ID_Pedido do teste."""
        envelope = {
            "Message": mensagem.body,
            "MessageAttributes": dict(mensagem.message_attributes),
        }
        return extrair_id_pedido(envelope) == id_pedido

    @staticmethod
    def _conteudo(mensagem: MensagemVisualizada) -> Optional[str]:
        """Extrai o ``conteudo`` do envelope SNS recebido na fila de destino.

        O corpo é o envelope padrão do SNS, cujo campo ``Message`` carrega o JSON
        do payload de aplicação. Quando o corpo é o próprio payload (como nos
        clientes simulados dos testes), o conteúdo é lido diretamente.
        """
        corpo = mensagem.body
        if not isinstance(corpo, str) or corpo == "":
            return None
        try:
            externo = json.loads(corpo)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(externo, dict):
            return None

        # Envelope SNS: o payload de aplicação está em "Message" (string JSON).
        interno = externo.get("Message")
        if isinstance(interno, str) and interno:
            try:
                payload = json.loads(interno)
            except (json.JSONDecodeError, ValueError):
                payload = None
            if isinstance(payload, dict) and CAMPO_CONTEUDO in payload:
                return str(payload[CAMPO_CONTEUDO])

        # Corpo é o próprio payload de aplicação.
        if CAMPO_CONTEUDO in externo:
            return str(externo[CAMPO_CONTEUDO])
        return None

    def _resultado_interrompido(
        self,
        standard: Optional[ResultadoTesteComparacao],
        fifo: Optional[ResultadoTesteComparacao],
        erro: Exception,
    ) -> ResultadoComparacao:
        """Monta o resultado de interrupção com a causa em pt-BR (Req. 7.8)."""
        return ResultadoComparacao(
            concluido=False,
            standard=standard,
            fifo=fifo,
            interrompido=True,
            mensagem=(
                "Comparação interrompida: o tópico pode estar indisponível ou a "
                "autenticação com a AWS falhou. Nenhum resultado parcial deve ser "
                "interpretado como garantia de ordenação. Consulte o detalhe do "
                "erro original."
            ),
            erro_original=repr(erro),
        )
