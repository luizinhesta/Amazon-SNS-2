"""Verificação de inicialização dos recursos AWS do laboratório SNS (Tarefa 9.1).

Antes de disponibilizar o **Dashboard**, o Sistema confirma que **todos** os
recursos AWS esperados do laboratório AWS SNS Delivery Lab **existem** e estão
**acessíveis** pela IAM_Role_EC2 (Req. 1.9):

- os **dois tópicos** SNS (``Topico_Standard`` e ``Topico_FIFO``);
- as **seis assinaturas** (três por tópico, apontando para as filas de destino);
- as **seis filas de destino** SQS (três Standard e três FIFO);
- as **duas DLQs** (``DLQ_SNS_Standard`` e ``DLQ_SNS_FIFO``);
- a **IAM Role** da EC2 (``IAM_Role_EC2``);
- a **instância EC2** que hospeda a aplicação.

O módulo recebe o sufixo ``_sns`` (``verificacao_inicializacao_sns.py``) para
conviver, sem colisão, com a verificação de inicialização de outro contexto do
repositório (``verificacao_inicializacao.py``).

Princípios de design desta verificação (ver ``requirements.md`` e ``design.md``,
seção "Verificacao_Inicializacao"):

- **Somente leitura; nunca cria/modifica/exclui recursos.** A verificação usa
  apenas operações de leitura (``get_topic_attributes``, ``get_queue_url``/
  ``get_queue_attributes``, ``list_subscriptions_by_topic``, ``get_role``,
  ``describe_instances``). Nenhuma operação de escrita, criação ou exclusão é
  executada (Req. 1.10).
- **Timeout de 10 s por recurso.** Cada verificação de recurso individual é
  limitada a ``TIMEOUT_VERIFICACAO_RECURSO_SEGUNDOS`` (10 s). Ao exceder, o
  recurso é tratado como inacessível, preservando a causa (Req. 1.9).
- **Preserva o erro original da AWS.** Quando um recurso está ausente ou
  inacessível, o erro original retornado pela AWS/boto3 é preservado no resultado
  e encadeado na exceção (``raise ... from``) para a camada superior registrar
  (Req. 1.11).
- **Interrompe sem alterar recursos.** Ao encontrar o primeiro recurso
  indisponível, a verificação para imediatamente (*fail-fast*) e sinaliza a
  falha; como ela só lê, interromper não deixa nenhum recurso alterado (Req. 1.11).
- **Identifica o recurso por nome e tipo em pt-BR.** O recurso indisponível é
  identificado pelo seu nome e pelo seu tipo em pt-BR (ex.: ``tópico SNS``,
  ``fila de destino``, ``DLQ``, ``IAM Role``, ``instância EC2``), e uma mensagem
  pronta para o Dashboard é produzida em português (Req. 1.11).
- **Clientes boto3 injetáveis para testabilidade.** Os clientes de SNS, SQS, IAM
  e EC2 são injetáveis, permitindo testar com mocks/fakes — recursos presentes e
  ausentes — sem acessar a AWS. Em produção, os clientes são criados pela cadeia
  de provedores padrão do boto3 (IAM Role da EC2), sem Access Keys (Req. 12.1,
  12.2).

Referências de requisitos: 1.9, 1.10, 1.11.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturoTimeoutError
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import boto3

from app.dominio import constantes_sns as c
from app.observabilidade.log_estruturado import log_evento


class TipoRecurso(str, Enum):
    """Tipo de recurso AWS verificado, com rótulo legível em pt-BR.

    O ``value`` é usado para identificar o recurso indisponível por tipo nas
    mensagens exibidas no Dashboard (Req. 1.11).
    """

    TOPICO = "tópico SNS"
    ASSINATURA = "assinatura SNS"
    FILA_DESTINO = "fila de destino"
    DLQ = "DLQ"
    IAM_ROLE = "IAM Role"
    INSTANCIA_EC2 = "instância EC2"


@dataclass(frozen=True)
class StatusRecurso:
    """Resultado da verificação de um único recurso AWS.

    Attributes:
        tipo: :class:`TipoRecurso` do recurso.
        nome: Nome do recurso (ex.: ``delivery-standard``, ``i-0abc123``).
        disponivel: ``True`` se o recurso existe e está acessível; ``False`` caso
            contrário.
        erro_original: Erro original retornado pela AWS/boto3 (ou ``TimeoutError``
            quando a verificação excede o timeout) quando o recurso está
            indisponível; ``None`` quando disponível (Req. 1.11).
    """

    tipo: TipoRecurso
    nome: str
    disponivel: bool
    erro_original: Optional[BaseException] = None

    @property
    def descricao_pt_br(self) -> str:
        """Descreve o recurso por tipo e nome em pt-BR (ex.: ``tópico SNS 'x'``)."""
        return f"{self.tipo.value} '{self.nome}'"


@dataclass(frozen=True)
class RelatorioInicializacao:
    """Resultado agregado da verificação de inicialização.

    Como a verificação é *fail-fast* (interrompe no primeiro recurso indisponível),
    ``recursos`` contém os recursos checados até o ponto da interrupção, terminando
    no recurso que falhou quando ``sucesso`` é ``False``.

    Attributes:
        sucesso: ``True`` somente se todos os recursos esperados estão disponíveis.
        recursos: Status de cada recurso checado, na ordem de verificação.
        recurso_indisponivel: O primeiro recurso indisponível encontrado, ou
            ``None`` quando todos estão disponíveis.
        mensagem_pt_br: Mensagem pronta para o Dashboard, em pt-BR, identificando o
            recurso indisponível por nome e tipo quando ``sucesso`` é ``False``
            (Req. 1.11).
    """

    sucesso: bool
    recursos: tuple[StatusRecurso, ...] = field(default_factory=tuple)
    recurso_indisponivel: Optional[StatusRecurso] = None
    mensagem_pt_br: str = ""

    @property
    def erro_original(self) -> Optional[BaseException]:
        """Erro original da AWS do recurso indisponível, se houver (Req. 1.11)."""
        if self.recurso_indisponivel is None:
            return None
        return self.recurso_indisponivel.erro_original


class FalhaVerificacaoInicializacaoSns(Exception):
    """Sinaliza que a verificação de inicialização do laboratório SNS falhou.

    Levantada por :func:`verificar_recursos` quando ``interromper_em_falha`` é
    ``True`` e algum recurso esperado está ausente ou inacessível. Interromper a
    inicialização impede a disponibilização do Dashboard antes de os recursos
    estarem prontos; como a verificação só executa leituras, a interrupção não
    altera nenhum recurso AWS (Req. 1.10, 1.11).

    O erro original da AWS é preservado em :attr:`erro_original` e encadeado via
    ``raise ... from`` para não perder a causa (Req. 1.11).

    Attributes:
        relatorio: O :class:`RelatorioInicializacao` que descreve a falha, incluindo
            o recurso indisponível e a mensagem em pt-BR.
    """

    def __init__(self, relatorio: RelatorioInicializacao) -> None:
        self.relatorio = relatorio
        super().__init__(relatorio.mensagem_pt_br)

    @property
    def erro_original(self) -> Optional[BaseException]:
        """Atalho para o erro original da AWS do recurso indisponível."""
        return self.relatorio.erro_original


# ---------------------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------------------
def _mensagem_indisponivel_pt_br(recurso: StatusRecurso) -> str:
    """Monta a mensagem em pt-BR para um recurso indisponível (Req. 1.11).

    Identifica o recurso por nome e tipo e inclui o detalhe do erro original da AWS
    quando disponível, para orientar o estudante a corrigir a configuração manual no
    Console AWS.
    """
    base = (
        "Inicialização interrompida: o recurso "
        f"{recurso.descricao_pt_br} está ausente ou inacessível. "
        "Verifique se ele foi criado manualmente no Console AWS (região "
        f"{c.REGIAO_AWS}) e se a IAM Role da EC2 tem permissão de acesso."
    )
    if recurso.erro_original is not None:
        base += f" Detalhe do erro original da AWS: {recurso.erro_original!r}."
    return base


# ---------------------------------------------------------------------------
# Verificador de inicialização
# ---------------------------------------------------------------------------
class VerificacaoInicializacaoSns:
    """Verifica existência e acessibilidade dos recursos AWS do laboratório SNS.

    Expõe as duas operações do design:

    - :meth:`verificar_recurso` ``(tipo, nome, timeout_s=10) -> StatusRecurso``;
    - :meth:`verificar_recursos` ``() -> RelatorioInicializacao``.

    Todas as verificações são **somente leitura** e **nunca** criam, modificam ou
    excluem recursos (Req. 1.10). Os clientes boto3 são injetáveis para testes; em
    produção, são resolvidos pela cadeia padrão do boto3 (IAM Role da EC2), sem
    Access Keys (Req. 12.1, 12.2).
    """

    def __init__(
        self,
        *,
        cliente_sns: Optional[Any] = None,
        cliente_sqs: Optional[Any] = None,
        cliente_iam: Optional[Any] = None,
        cliente_ec2: Optional[Any] = None,
        regiao: str = c.REGIAO_AWS,
        nome_iam_role: str,
        id_instancia_ec2: str,
        timeout_recurso_s: int = c.TIMEOUT_VERIFICACAO_RECURSO_SEGUNDOS,
    ) -> None:
        """Inicializa o verificador.

        Args:
            cliente_sns: cliente SNS boto3 (injete um simulado em testes). ``None``
                cria o cliente padrão sem Access Keys.
            cliente_sqs: cliente SQS boto3 (injete um simulado em testes).
            cliente_iam: cliente IAM boto3 (injete um simulado em testes).
            cliente_ec2: cliente EC2 boto3 (injete um simulado em testes).
            regiao: região AWS do laboratório (padrão ``us-east-1``).
            nome_iam_role: nome da IAM_Role_EC2 a verificar (``get_role``).
            id_instancia_ec2: id da instância EC2 a verificar (``describe_instances``).
            timeout_recurso_s: timeout em segundos por recurso (padrão 10 s, Req.
                1.9).
        """
        # Importante: NÃO passamos aws_access_key_id/aws_secret_access_key.
        # O boto3 resolve as credenciais temporárias pela IAM Role da EC2
        # através da cadeia de provedores padrão (Req. 12.1, 12.2).
        self._sns = cliente_sns if cliente_sns is not None else boto3.client(
            "sns", region_name=regiao
        )
        self._sqs = cliente_sqs if cliente_sqs is not None else boto3.client(
            "sqs", region_name=regiao
        )
        self._iam = cliente_iam if cliente_iam is not None else boto3.client(
            "iam", region_name=regiao
        )
        self._ec2 = cliente_ec2 if cliente_ec2 is not None else boto3.client(
            "ec2", region_name=regiao
        )
        self._regiao = regiao
        self._nome_iam_role = nome_iam_role
        self._id_instancia_ec2 = id_instancia_ec2
        self._timeout_recurso_s = timeout_recurso_s
        # Cache de ARNs de tópico resolvidos por nome, para a checagem de assinaturas.
        self._arn_por_topico: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Verificação de um único recurso (com timeout)
    # ------------------------------------------------------------------
    def verificar_recurso(
        self,
        tipo: TipoRecurso,
        nome: str,
        timeout_s: Optional[int] = None,
    ) -> StatusRecurso:
        """Verifica a existência/acessibilidade de UM recurso (somente leitura).

        Aplica o timeout de ``timeout_s`` segundos (padrão 10 s) à leitura: se a
        operação de leitura exceder o tempo, o recurso é marcado como indisponível,
        preservando um ``TimeoutError`` como erro original (Req. 1.9, 1.11).

        Qualquer erro da AWS (recurso ausente, acesso negado) é capturado e
        preservado no :class:`StatusRecurso`, sem ser mascarado (Req. 1.11).

        Args:
            tipo: :class:`TipoRecurso` do recurso.
            nome: nome do recurso (ex.: ``delivery-standard``, ``i-0abc123``).
            timeout_s: timeout em segundos; ``None`` usa o padrão do verificador.

        Returns:
            :class:`StatusRecurso` indicando disponibilidade e, em falha, o erro
            original da AWS (ou ``TimeoutError``).
        """
        prazo = self._timeout_recurso_s if timeout_s is None else timeout_s
        leitura = self._leitura_por_tipo(tipo)

        try:
            self._executar_com_timeout(lambda: leitura(nome), prazo)
        except FuturoTimeoutError as timeout:
            erro = TimeoutError(
                f"A verificação do recurso excedeu o timeout de {prazo}s."
            )
            erro.__cause__ = timeout
            return StatusRecurso(
                tipo=tipo, nome=nome, disponivel=False, erro_original=erro
            )
        except Exception as erro:  # noqa: BLE001 — preservamos o erro (Req. 1.11)
            return StatusRecurso(
                tipo=tipo, nome=nome, disponivel=False, erro_original=erro
            )
        return StatusRecurso(tipo=tipo, nome=nome, disponivel=True)

    @staticmethod
    def _executar_com_timeout(funcao: Callable[[], Any], timeout_s: int) -> Any:
        """Executa ``funcao`` com um limite de tempo (``timeout_s`` segundos).

        Usa um executor de thread única para impor o timeout por recurso sem exigir
        suporte a timeout do cliente boto3 (Req. 1.9). Repassa qualquer exceção
        levantada pela ``funcao`` e levanta ``TimeoutError`` ao exceder o prazo.
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(funcao)
            # result(timeout) levanta concurrent.futures.TimeoutError ao exceder.
            return futuro.result(timeout=timeout_s)

    def _leitura_por_tipo(self, tipo: TipoRecurso) -> Callable[[str], Any]:
        """Mapeia o tipo de recurso para a sua operação de leitura correspondente."""
        return {
            TipoRecurso.TOPICO: self._ler_topico,
            TipoRecurso.ASSINATURA: self._ler_assinaturas_topico,
            TipoRecurso.FILA_DESTINO: self._ler_fila,
            TipoRecurso.DLQ: self._ler_fila,
            TipoRecurso.IAM_ROLE: self._ler_iam_role,
            TipoRecurso.INSTANCIA_EC2: self._ler_instancia_ec2,
        }[tipo]

    # ------------------------------------------------------------------
    # Operações de leitura por recurso (todas somente leitura — Req. 1.10)
    # ------------------------------------------------------------------
    def _ler_topico(self, nome_topico: str) -> str:
        """Resolve o ARN do tópico (ListTopics) e confirma o acesso (GetTopicAttributes).

        Lista os tópicos existentes (operação de leitura) para encontrar o ARN cujo
        nome corresponde ao esperado; em seguida lê os atributos do tópico para
        confirmar a acessibilidade. Memoiza o ARN para a checagem de assinaturas.
        Levanta exceção se o tópico não existir ou não estiver acessível.
        """
        arn = self._resolver_arn_topico(nome_topico)
        # Confirma a acessibilidade do tópico (leitura dos atributos).
        self._sns.get_topic_attributes(TopicArn=arn)
        return arn

    def _resolver_arn_topico(self, nome_topico: str) -> str:
        """Encontra o ARN de um tópico pelo nome, paginando ListTopics (leitura)."""
        if nome_topico in self._arn_por_topico:
            return self._arn_por_topico[nome_topico]

        next_token: Optional[str] = None
        while True:
            if next_token is None:
                resposta = self._sns.list_topics()
            else:
                resposta = self._sns.list_topics(NextToken=next_token)
            for topico in resposta.get("Topics", []) or []:
                arn = topico.get("TopicArn", "")
                # O nome do tópico é o último segmento do ARN (após o ':').
                if arn.rsplit(":", 1)[-1] == nome_topico:
                    self._arn_por_topico[nome_topico] = arn
                    return arn
            next_token = resposta.get("NextToken")
            if not next_token:
                break

        raise LookupError(
            f"Tópico SNS '{nome_topico}' não encontrado na região {self._regiao}."
        )

    def _ler_assinaturas_topico(self, nome_topico: str) -> None:
        """Confirma que o tópico possui as três assinaturas esperadas (ListSubscriptions).

        Lista as assinaturas confirmadas do tópico (operação de leitura) e exige que
        existam ao menos três assinaturas confirmadas para as três filas de destino
        do cenário. Levanta exceção quando faltam assinaturas confirmadas.
        """
        arn = self._resolver_arn_topico(nome_topico)
        assinaturas = self._listar_assinaturas(arn)
        confirmadas = [
            a
            for a in assinaturas
            if (a.get("SubscriptionArn", "") or "").startswith("arn:")
        ]
        esperadas = len(c.FILAS_DESTINO_POR_TOPICO.get(nome_topico, ()))
        if len(confirmadas) < esperadas:
            raise LookupError(
                f"O tópico '{nome_topico}' possui {len(confirmadas)} assinatura(s) "
                f"confirmada(s), mas são esperadas {esperadas} (uma por fila de "
                "destino do cenário)."
            )

    def _listar_assinaturas(self, topic_arn: str) -> list[dict[str, Any]]:
        """Lista as assinaturas de um tópico paginando ListSubscriptionsByTopic (leitura)."""
        assinaturas: list[dict[str, Any]] = []
        next_token: Optional[str] = None
        while True:
            if next_token is None:
                resposta = self._sns.list_subscriptions_by_topic(TopicArn=topic_arn)
            else:
                resposta = self._sns.list_subscriptions_by_topic(
                    TopicArn=topic_arn, NextToken=next_token
                )
            assinaturas.extend(resposta.get("Subscriptions", []) or [])
            next_token = resposta.get("NextToken")
            if not next_token:
                break
        return assinaturas

    def _ler_fila(self, nome_fila: str) -> None:
        """Resolve a URL (GetQueueUrl) e lê os atributos (GetQueueAttributes) da fila.

        Ambas são operações de leitura: nenhuma criação, modificação ou exclusão
        ocorre (Req. 1.10). Levanta exceção se a fila não existir ou a IAM Role não
        tiver acesso.
        """
        url = self._sqs.get_queue_url(QueueName=nome_fila)["QueueUrl"]
        self._sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])

    def _ler_iam_role(self, nome_role: str) -> None:
        """Confirma a existência/acessibilidade da IAM Role (GetRole — leitura)."""
        self._iam.get_role(RoleName=nome_role)

    def _ler_instancia_ec2(self, id_instancia: str) -> None:
        """Confirma a existência/acessibilidade da instância EC2 (DescribeInstances).

        ``DescribeInstances`` é somente leitura. Levanta exceção quando a instância
        não é encontrada (nenhuma reserva retornada) ou o acesso é negado.
        """
        resposta = self._ec2.describe_instances(InstanceIds=[id_instancia])
        reservas = resposta.get("Reservations", []) or []
        instancias = [i for r in reservas for i in (r.get("Instances", []) or [])]
        if not instancias:
            raise LookupError(
                f"Instância EC2 '{id_instancia}' não encontrada na região "
                f"{self._regiao}."
            )

    # ------------------------------------------------------------------
    # Verificação completa (fail-fast)
    # ------------------------------------------------------------------
    def verificar_recursos(
        self, *, interromper_em_falha: bool = True
    ) -> RelatorioInicializacao:
        """Verifica TODOS os recursos esperados do laboratório, em ordem determinística.

        Checa, **somente por leitura** e em ordem fixa (Req. 1.9):

        1. os dois tópicos SNS;
        2. as seis assinaturas (três por tópico);
        3. as seis filas de destino SQS;
        4. as duas DLQs;
        5. a IAM Role da EC2;
        6. a instância EC2.

        A verificação é *fail-fast*: para no **primeiro** recurso indisponível, pois
        não há motivo para seguir — e, por só ler, interromper não altera nenhum
        recurso (Req. 1.10, 1.11).

        Em caso de recurso indisponível, o relatório identifica o recurso por **nome
        e tipo**, preserva o **erro original** da AWS e produz uma **mensagem em
        pt-BR** pronta para o Dashboard (Req. 1.11). Quando ``interromper_em_falha``
        é ``True`` (padrão), levanta :class:`FalhaVerificacaoInicializacaoSns`;
        quando ``False``, apenas devolve o relatório com ``sucesso=False``.

        Args:
            interromper_em_falha: Se ``True`` (padrão), levanta
                :class:`FalhaVerificacaoInicializacaoSns` ao primeiro recurso
                indisponível; se ``False``, retorna o relatório sem levantar.

        Returns:
            :class:`RelatorioInicializacao` com ``sucesso=True`` quando todos os
            recursos estão disponíveis.

        Raises:
            FalhaVerificacaoInicializacaoSns: quando há recurso indisponível e
                ``interromper_em_falha`` é ``True``. O erro original fica em
                :attr:`FalhaVerificacaoInicializacaoSns.erro_original`.
        """
        verificados: list[StatusRecurso] = []

        # Ordem determinística de verificação (tipo, nome).
        plano: list[tuple[TipoRecurso, str]] = []
        plano += [(TipoRecurso.TOPICO, nome) for nome in c.TOPICOS]
        plano += [(TipoRecurso.ASSINATURA, nome) for nome in c.TOPICOS]
        plano += [(TipoRecurso.FILA_DESTINO, nome) for nome in c.FILAS_DESTINO]
        plano += [(TipoRecurso.DLQ, nome) for nome in c.DLQS]
        plano += [(TipoRecurso.IAM_ROLE, self._nome_iam_role)]
        plano += [(TipoRecurso.INSTANCIA_EC2, self._id_instancia_ec2)]

        for tipo, nome in plano:
            status = self.verificar_recurso(tipo, nome)
            verificados.append(status)
            if not status.disponivel:
                return self._falha(status, verificados, interromper_em_falha)

        log_evento(
            logging.INFO,
            "verificacao_inicializacao_ok",
            total_recursos=len(verificados),
        )
        return RelatorioInicializacao(
            sucesso=True,
            recursos=tuple(verificados),
            recurso_indisponivel=None,
            mensagem_pt_br=(
                "Todos os recursos AWS esperados estão disponíveis e acessíveis."
            ),
        )

    def _falha(
        self,
        recurso: StatusRecurso,
        verificados: list[StatusRecurso],
        interromper_em_falha: bool,
    ) -> RelatorioInicializacao:
        """Monta o relatório de falha, registra o erro original e, se pedido, interrompe."""
        relatorio = RelatorioInicializacao(
            sucesso=False,
            recursos=tuple(verificados),
            recurso_indisponivel=recurso,
            mensagem_pt_br=_mensagem_indisponivel_pt_br(recurso),
        )
        # Registra o erro original retornado pela AWS (Req. 1.11).
        log_evento(
            logging.ERROR,
            "verificacao_inicializacao_falhou",
            tipo_recurso=recurso.tipo.value,
            nome_recurso=recurso.nome,
            erro_original=recurso.erro_original,
        )
        if interromper_em_falha:
            # Encadeia o erro original da AWS para não perder a causa (Req. 1.11).
            raise FalhaVerificacaoInicializacaoSns(relatorio) from recurso.erro_original
        return relatorio
