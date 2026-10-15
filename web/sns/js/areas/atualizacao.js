/**
 * Atualização periódica das estatísticas e indicadores de estado do Dashboard
 * AWS SNS Delivery Lab (Tarefa 15.5 — Req. 13.1 a 13.6).
 *
 * Responsabilidades deste módulo:
 *
 *  1. Rodar um ciclo periódico que, ao final de cada intervalo configurável,
 *     chama `atualizarEstatisticas()` (exportada pela Tarefa 15.2) SEM recarregar
 *     a página (Req. 13.1, 13.2). O ciclo é agendado com `setTimeout` encadeado
 *     (e não `setInterval`) para que cada atualização só comece após a anterior
 *     concluir, evitando sobreposição quando a rede está lenta.
 *
 *  2. Oferecer um controle para ajustar o intervalo de atualização dentro da
 *     faixa de 5 a 300 segundos (padrão 10s). Valores fora da faixa são
 *     rejeitados, o intervalo anterior é preservado e uma mensagem em pt-BR com a
 *     faixa válida é exibida (Req. 13.3). O ajuste é local ao Dashboard: controla
 *     apenas a cadência do polling do cliente, sem alterar recursos no backend.
 *
 *  3. Reaproveitar a lógica da Tarefa 15.2 para o horário da última atualização
 *     bem-sucedida (Req. 13.4) e para a preservação dos últimos dados válidos com
 *     indicação de que podem estar desatualizados em caso de falha (Req. 13.5).
 *     Além disso, exibe aqui o momento da última tentativa periódica e se ela foi
 *     bem-sucedida ou falhou.
 *
 *  4. Exibir o indicador textual distinto Entrega_Publicada × Entrega_Confirmada
 *     (Req. 13.6), deixando claro o que cada estado significa.
 *
 * O start/stop do ciclo é integrado pelo orquestrador (`main.js`): inicia ao
 * autenticar e para no logout, para não deixar timers órfãos.
 */

import {
  atualizarEstatisticas,
  obterIntervaloAtualizacaoConfig,
  FAIXA_INTERVALO_ATUALIZACAO,
} from "./estatisticas.js";

/** Faixa válida do intervalo de atualização, em segundos (Req. 13.2, 13.3). */
const INTERVALO_MIN_SEGUNDOS = FAIXA_INTERVALO_ATUALIZACAO.min;
const INTERVALO_MAX_SEGUNDOS = FAIXA_INTERVALO_ATUALIZACAO.max;
const INTERVALO_PADRAO_SEGUNDOS = FAIXA_INTERVALO_ATUALIZACAO.padrao;

/** Cria um elemento com classe e, opcionalmente, texto. */
function el(tag, className, texto) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (texto !== undefined) {
    node.textContent = texto;
  }
  return node;
}

/**
 * Valida um intervalo informado contra a faixa de 5 a 300 segundos (Req. 13.3).
 *
 * @param {unknown} valor Valor informado pelo usuário.
 * @returns {{ aceito: boolean, valor: number }} Resultado da validação; quando
 *   rejeitado, `valor` é NaN e cabe ao chamador preservar o intervalo anterior.
 */
function validarIntervalo(valor) {
  const n = Number(valor);
  if (!Number.isFinite(n) || !Number.isInteger(n)) {
    return { aceito: false, valor: NaN };
  }
  if (n < INTERVALO_MIN_SEGUNDOS || n > INTERVALO_MAX_SEGUNDOS) {
    return { aceito: false, valor: NaN };
  }
  return { aceito: true, valor: n };
}

/**
 * Formata o horário de uma tentativa periódica em pt-BR (data e hora com
 * segundos), usando o fuso do navegador (Req. 13.4).
 *
 * @param {Date} data Momento da tentativa.
 * @returns {string} Horário formatado.
 */
function formatarHorario(data) {
  const formatador = new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZoneName: "short",
  });
  return formatador.format(data);
}

/**
 * Cria o controlador da atualização periódica das estatísticas.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 * @returns {{ iniciar: () => void, parar: () => void, destruir: () => void }}
 *   API usada pelo orquestrador para ligar/desligar o ciclo.
 */
export function criarAtualizacaoPeriodica(ctx) {
  // Ponto de extensão reutilizado da visão geral; o controle é anexado abaixo das
  // estatísticas, dentro do mesmo bloco de "Estatísticas e configuração".
  const alvo = ctx.container.querySelector('[data-extension-point="overview-stats"]');

  const estado = {
    intervaloSegundos: INTERVALO_PADRAO_SEGUNDOS,
    timerId: null,
    ativo: false,
    atualizando: false,
    elementos: null,
  };

  /**
   * Desenha o painel de controle da atualização periódica (campo de intervalo,
   * mensagem de validação, status da última tentativa e legenda de estados).
   */
  function renderizarPainel() {
    if (!alvo || estado.elementos) {
      return;
    }

    const sec = el("section", "atualizacao-section");
    sec.setAttribute("aria-labelledby", "atualizacao-heading");

    const titulo = Object.assign(
      el("h4", "atualizacao-heading", "Atualização periódica das estatísticas"),
      { id: "atualizacao-heading" }
    );
    sec.appendChild(titulo);

    sec.appendChild(
      el(
        "p",
        "atualizacao-hint",
        "As estatísticas são atualizadas automaticamente ao final de cada intervalo, " +
          "sem recarregar a página. Ajuste o intervalo dentro da faixa indicada."
      )
    );

    // --- Campo de intervalo (Req. 13.2, 13.3) ---
    const idInput = "atualizacao-intervalo";
    const idMsg = `${idInput}-msg`;

    const campo = el("div", "atualizacao-campo");

    const label = el(
      "label",
      "atualizacao-label",
      `Intervalo de atualização (${INTERVALO_MIN_SEGUNDOS}–${INTERVALO_MAX_SEGUNDOS} segundos)`
    );
    label.setAttribute("for", idInput);
    campo.appendChild(label);

    const input = el("input", "atualizacao-input");
    input.type = "number";
    input.id = idInput;
    input.min = String(INTERVALO_MIN_SEGUNDOS);
    input.max = String(INTERVALO_MAX_SEGUNDOS);
    input.step = "1";
    input.value = String(estado.intervaloSegundos);
    input.setAttribute("inputmode", "numeric");
    input.setAttribute("aria-describedby", idMsg);
    campo.appendChild(input);

    const botao = el("button", "btn btn-primary atualizacao-aplicar", "Aplicar intervalo");
    botao.type = "button";
    campo.appendChild(botao);

    sec.appendChild(campo);

    // Mensagem de validação (faixa válida em rejeição). role=alert para anúncio
    // imediato por leitores de tela (Req. 13.3).
    const mensagem = el("p", "atualizacao-msg");
    mensagem.id = idMsg;
    mensagem.setAttribute("role", "alert");
    mensagem.setAttribute("aria-live", "assertive");
    mensagem.hidden = true;
    sec.appendChild(mensagem);

    // Status da última tentativa periódica (Req. 13.4, 13.5). aria-live=polite
    // para não interromper o usuário a cada ciclo.
    const status = el("p", "atualizacao-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = "Atualização periódica ainda não iniciada.";
    sec.appendChild(status);

    // Indicador textual distinto Entrega_Publicada × Entrega_Confirmada (Req. 13.6).
    const legenda = el("p", "atualizacao-legenda");
    legenda.append(
      "Indicadores de estado por mensagem — ",
      "Entrega_Publicada: o SNS aceitou a publicação (MessageId). ",
      "Entrega_Confirmada: a mensagem foi lida na fila de destino, correlacionada pelo ID_Pedido."
    );
    sec.appendChild(legenda);

    alvo.appendChild(sec);

    estado.elementos = { input, botao, mensagem, status };

    // Liga o botão ao ajuste do intervalo.
    botao.addEventListener("click", () => aplicarIntervalo(input.value));
    // Enter no campo também aplica, sem submeter formulário algum.
    input.addEventListener("keydown", (evento) => {
      if (evento.key === "Enter") {
        evento.preventDefault();
        aplicarIntervalo(input.value);
      }
    });
  }

  /**
   * Exibe uma mensagem no painel (sucesso ou rejeição), aplicando a classe de
   * estado correspondente.
   *
   * @param {boolean} aceito Se a ação foi aceita.
   * @param {string} texto Texto em pt-BR a exibir.
   */
  function mostrarMensagem(aceito, texto) {
    const { mensagem } = estado.elementos;
    mensagem.textContent = texto;
    mensagem.classList.toggle("is-erro", !aceito);
    mensagem.classList.toggle("is-ok", aceito);
    mensagem.hidden = false;
  }

  /**
   * Aplica um novo intervalo de atualização, validando a faixa (Req. 13.3). Ao
   * rejeitar, preserva o intervalo anterior (inclusive restaurando o valor do
   * campo) e exibe a faixa válida em pt-BR.
   *
   * @param {string|number} valorInformado Valor digitado pelo usuário.
   */
  function aplicarIntervalo(valorInformado) {
    const bruto = String(valorInformado).trim();
    const resultado = validarIntervalo(bruto);

    if (!resultado.aceito) {
      // Rejeitado: preserva o intervalo anterior e informa a faixa válida.
      estado.elementos.input.value = String(estado.intervaloSegundos);
      mostrarMensagem(
        false,
        `Intervalo inválido. Informe um número inteiro entre ${INTERVALO_MIN_SEGUNDOS} e ` +
          `${INTERVALO_MAX_SEGUNDOS} segundos. O intervalo anterior ` +
          `(${estado.intervaloSegundos} segundos) foi preservado.`
      );
      return;
    }

    estado.intervaloSegundos = resultado.valor;
    estado.elementos.input.value = String(resultado.valor);
    mostrarMensagem(
      true,
      `Intervalo de atualização definido para ${resultado.valor} segundos.`
    );

    // Reinicia o agendamento para que o novo intervalo passe a valer já no
    // próximo ciclo, sem recarregar a página (Req. 13.1).
    if (estado.ativo) {
      reagendar();
    }
  }

  /** Cancela o próximo ciclo agendado, se houver. */
  function cancelarTimer() {
    if (estado.timerId !== null) {
      window.clearTimeout(estado.timerId);
      estado.timerId = null;
    }
  }

  /** Reagenda o próximo ciclo a partir do intervalo atual. */
  function reagendar() {
    cancelarTimer();
    estado.timerId = window.setTimeout(executarCiclo, estado.intervaloSegundos * 1000);
  }

  /**
   * Executa um ciclo: dispara a atualização das estatísticas e, ao concluir,
   * registra o horário/estado da tentativa e reagenda o próximo ciclo.
   *
   * A preservação dos últimos dados válidos e a indicação de falha em caso de
   * erro/timeout são responsabilidade de `atualizarEstatisticas()` (Req. 13.5);
   * aqui apenas registramos o resultado da tentativa periódica.
   */
  async function executarCiclo() {
    if (!estado.ativo || estado.atualizando) {
      return;
    }
    estado.atualizando = true;
    const { status } = estado.elementos || {};
    try {
      await atualizarEstatisticas();
      if (status) {
        status.classList.remove("is-erro");
        status.textContent =
          `Última atualização periódica em ${formatarHorario(new Date())}.`;
      }
    } catch {
      // atualizarEstatisticas() já trata e exibe a falha nas estatísticas; aqui
      // apenas sinalizamos que a tentativa periódica não teve êxito (Req. 13.5).
      if (status) {
        status.classList.add("is-erro");
        status.textContent =
          `A última tentativa de atualização (${formatarHorario(new Date())}) falhou. ` +
          "Os dados exibidos podem estar desatualizados.";
      }
    } finally {
      estado.atualizando = false;
      if (estado.ativo) {
        reagendar();
      }
    }
  }

  return {
    /**
     * Inicia o ciclo periódico. Desenha o painel (uma vez), sincroniza o intervalo
     * com o valor vindo do backend (quando disponível) e agenda o primeiro ciclo.
     */
    iniciar() {
      if (estado.ativo) {
        return;
      }
      renderizarPainel();
      if (!estado.elementos) {
        // Sem ponto de extensão disponível: nada a fazer.
        return;
      }

      // Alinha o intervalo inicial ao valor informado pelo backend em
      // Config_Simulacao ("Intervalo de atualização"), caindo para o padrão
      // quando ainda não disponível ou fora da faixa.
      const doBackend = obterIntervaloAtualizacaoConfig();
      const validado = validarIntervalo(doBackend);
      if (validado.aceito) {
        estado.intervaloSegundos = validado.valor;
        estado.elementos.input.value = String(validado.valor);
      }

      estado.ativo = true;
      reagendar();
    },

    /** Para o ciclo periódico, cancelando qualquer atualização agendada. */
    parar() {
      estado.ativo = false;
      cancelarTimer();
    },

    /** Para o ciclo e remove o painel do DOM (usado em reinicializações). */
    destruir() {
      this.parar();
      if (estado.elementos && alvo) {
        const sec = alvo.querySelector(".atualizacao-section");
        if (sec) {
          sec.remove();
        }
      }
      estado.elementos = null;
    },
  };
}
