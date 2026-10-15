"""Estado em memória dos testes ativos do laboratório AWS SNS Delivery Lab (Tarefa 13.1).

O Dashboard deve manter **desabilitado** o botão de um teste **enquanto esse teste
estiver ativo** e **reabilitá-lo** quando o teste concluir ou for interrompido
(Req. 9.3, 9.4). Como a decisão de habilitar/desabilitar precisa ser consistente
mesmo com múltiplos clientes do Dashboard, o **estado "teste ativo" é mantido do
lado servidor** e exposto por ``GET /api/testes/estado``; o Dashboard apenas
reflete o estado publicado pela API_Backend.

Este módulo mantém, de forma thread-safe, o conjunto de testes atualmente em
execução, identificados por uma chave estável (``disparar_standard``,
``disparar_fifo``, ``comparar``, ``dlq``). Cada endpoint de teste:

1. marca o teste como ativo ao iniciar (:meth:`iniciar`);
2. executa a publicação/verificação;
3. marca o teste como concluído ao finalizar — inclusive em caso de erro —
   (:meth:`concluir`), para que o botão seja reabilitado (Req. 9.4).

O context manager :meth:`em_execucao` garante o passo 3 mesmo quando a execução
levanta exceção, evitando que um teste fique "travado" como ativo após uma falha.

Decisões de design:

- **Fonte de verdade no servidor (Req. 9.3, 9.4).** O Dashboard não decide
  sozinho; ele consulta ``GET /api/testes/estado`` e desabilita os botões dos
  testes marcados como ativos.
- **Reentrância negada por teste.** Enquanto um teste está ativo, uma nova
  tentativa de iniciá-lo é recusada por :meth:`iniciar` (retorna ``False``),
  reforçando no servidor a regra de acionamento manual único, sem loops nem
  disparos concorrentes do mesmo teste (Req. 9.1, 9.2).
- **Thread-safe.** O conjunto interno é protegido por um ``threading.Lock``,
  pois a API_Backend atende requisições concorrentes.

Referências de requisitos: 9.1, 9.2, 9.3, 9.4.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

# Chaves estáveis dos testes acionáveis pelo Dashboard (uma por botão). Mantidas
# como constantes para o Dashboard e os testes referenciarem sem divergência.
TESTE_DISPARAR_STANDARD: str = "disparar_standard"
TESTE_DISPARAR_FIFO: str = "disparar_fifo"
TESTE_COMPARAR: str = "comparar"
TESTE_DLQ: str = "dlq"

# Conjunto de testes conhecidos; usado para montar o estado completo (todos os
# botões), inclusive os inativos, no endpoint de estado.
TESTES_CONHECIDOS: tuple[str, ...] = (
    TESTE_DISPARAR_STANDARD,
    TESTE_DISPARAR_FIFO,
    TESTE_COMPARAR,
    TESTE_DLQ,
)


class EstadoTestesSns:
    """Guarda, de forma thread-safe, quais testes estão ativos (botões desabilitados).

    Cada teste é identificado por uma chave estável (ver as constantes
    ``TESTE_*``). Um teste ativo mantém o botão correspondente desabilitado no
    Dashboard (Req. 9.3); ao concluir ou ser interrompido, o botão é reabilitado
    (Req. 9.4).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ativos: set[str] = set()

    def iniciar(self, teste: str) -> bool:
        """Marca um teste como ativo (desabilita o botão) — Req. 9.3.

        Returns:
            ``True`` se o teste passou de inativo para ativo; ``False`` se o teste
            já estava ativo (nesse caso, uma nova execução concorrente é recusada,
            reforçando o acionamento manual único — Req. 9.1, 9.2).
        """
        with self._lock:
            if teste in self._ativos:
                return False
            self._ativos.add(teste)
            return True

    def concluir(self, teste: str) -> None:
        """Marca um teste como concluído/interrompido (reabilita o botão) — Req. 9.4."""
        with self._lock:
            self._ativos.discard(teste)

    def ativo(self, teste: str) -> bool:
        """Indica se um teste específico está ativo."""
        with self._lock:
            return teste in self._ativos

    def ativos(self) -> frozenset[str]:
        """Devolve um snapshot imutável do conjunto de testes ativos."""
        with self._lock:
            return frozenset(self._ativos)

    def estado(self) -> dict[str, bool]:
        """Mapa de cada teste conhecido para ``True`` quando ativo (botão desabilitado).

        Inclui todos os testes conhecidos (mesmo os inativos, com ``False``), para
        que o Dashboard reflita o estado completo dos quatro botões (Req. 9.3, 9.4).
        """
        with self._lock:
            return {teste: (teste in self._ativos) for teste in TESTES_CONHECIDOS}

    @contextmanager
    def em_execucao(self, teste: str) -> Iterator[None]:
        """Context manager que garante a reabilitação do botão ao final (Req. 9.4).

        Marca o teste como ativo na entrada (assumindo que :meth:`iniciar` já
        autorizou a execução) e, no ``finally``, marca como concluído — inclusive
        quando o bloco levanta exceção —, de modo que uma falha nunca deixe o botão
        travado como desabilitado.
        """
        with self._lock:
            self._ativos.add(teste)
        try:
            yield
        finally:
            self.concluir(teste)
