/**
 * Orquestrador do Dashboard AWS SNS Delivery Lab (Tarefa 15.1).
 *
 * Monta a estrutura/esqueleto: controla a transição login -> painel autenticado,
 * inicializa a navegação entre as áreas e injeta o contexto compartilhado (cliente
 * da API e container de cada área) nos módulos de área.
 *
 * As áreas são:
 *  - overview  : visão geral + representação visual da arquitetura (Tarefa 15.1/15.2);
 *  - standard  : "DISPARAR SNS STANDARD" (Tarefa 15.3);
 *  - fifo      : "DISPARAR SNS FIFO" (Tarefa 15.3);
 *  - comparar  : "COMPARAR STANDARD X FIFO" (Tarefa 15.4);
 *  - dlq       : "TESTAR DLQ DO SNS" (Tarefa 15.4).
 *
 * A atualização periódica das estatísticas (Tarefa 15.5) e os detalhes de cada
 * ação (15.2-15.4) são conectados nos respectivos módulos de área, usando o
 * contexto injetado aqui. Esta tarefa apenas garante que a página carrega sem
 * erros de JS e expõe os pontos de extensão.
 */

import { api } from "./api.js";
import { setupLogin } from "./auth.js";
import { setupNavigation } from "./navigation.js";

import { criarAtualizacaoPeriodica } from "./areas/atualizacao.js";
import * as overview from "./areas/overview.js";
import * as standard from "./areas/standard.js";
import * as fifo from "./areas/fifo.js";
import * as comparar from "./areas/comparar.js";
import * as dlq from "./areas/dlq.js";

/** Mapa de área -> módulo e id do container, para inicialização e extensão. */
const AREA_MODULES = {
  overview: { module: overview, containerId: "overview-area" },
  standard: { module: standard, containerId: "standard-area" },
  fifo: { module: fifo, containerId: "fifo-area" },
  comparar: { module: comparar, containerId: "comparar-area" },
  dlq: { module: dlq, containerId: "dlq-area" },
};

function mostrarDashboard() {
  document.getElementById("login-screen").hidden = true;
  document.getElementById("dashboard").hidden = false;
}

function mostrarLogin() {
  document.getElementById("dashboard").hidden = true;
  document.getElementById("login-screen").hidden = false;
}

/**
 * Inicializa cada módulo de área uma única vez, passando o contexto compartilhado.
 * As áreas usam este contexto como ponto de extensão (Tarefas 15.2-15.5).
 */
function inicializarAreas() {
  Object.values(AREA_MODULES).forEach(({ module, containerId }) => {
    const container = document.getElementById(containerId);
    if (module && typeof module.init === "function") {
      module.init({ api, container });
    }
  });
}

/**
 * Encerra os recursos vivos de cada área que exponha `encerrar()` (ex.: o polling
 * do estado dos botões de disparo da Tarefa 15.3), evitando timers órfãos após o
 * logout.
 */
function encerrarAreas() {
  Object.values(AREA_MODULES).forEach(({ module }) => {
    if (module && typeof module.encerrar === "function") {
      module.encerrar();
    }
  });
}

/**
 * Liga os cartões de ação da visão geral (elementos com `data-goto-area`) à
 * navegação, de modo que clicar em "DISPARAR SNS STANDARD", "DISPARAR SNS FIFO",
 * "COMPARAR STANDARD X FIFO" ou "TESTAR DLQ DO SNS" ative a área correspondente.
 *
 * @param {{ activate: (area: string) => void }} nav Controlador de navegação.
 * @returns {() => void} Função que remove os listeners (usada no logout).
 */
function conectarAtalhosAcoes(nav) {
  const cartoes = Array.from(document.querySelectorAll("[data-goto-area]"));
  const handler = (evento) => {
    const area = evento.currentTarget.dataset.gotoArea;
    if (area) {
      nav.activate(area);
    }
  };
  cartoes.forEach((cartao) => cartao.addEventListener("click", handler));
  return () => cartoes.forEach((cartao) => cartao.removeEventListener("click", handler));
}

function iniciarPainel() {
  mostrarDashboard();
  const nav = setupNavigation();
  inicializarAreas();

  const desconectarAtalhos = conectarAtalhosAcoes(nav);

  // Atualização periódica das estatísticas (Tarefa 15.5 — Req. 13.1-13.6). O
  // ciclo roda sobre a área de visão geral (onde o bloco de estatísticas vive) e
  // inicia agora, ao autenticar; é parado no logout, abaixo em `encerrar()`.
  const atualizacaoPeriodica = criarAtualizacaoPeriodica({
    api,
    container: document.getElementById(AREA_MODULES.overview.containerId),
  });
  atualizacaoPeriodica.iniciar();

  return {
    /** Encerra os recursos vivos do painel (chamado no logout). */
    encerrar() {
      desconectarAtalhos();
      // Encerra o polling de estado dos botões de disparo (Tarefa 15.3).
      encerrarAreas();
      // Para a atualização periódica e remove seu painel (Tarefa 15.5).
      atualizacaoPeriodica.destruir();
    },
    nav,
  };
}

function main() {
  let painel = null;

  const login = setupLogin({
    onAuthenticated: () => {
      painel = iniciarPainel();
    },
  });

  document.getElementById("logout-button").addEventListener("click", () => {
    if (painel) {
      painel.encerrar();
      painel = null;
    }
    login.reset();
    mostrarLogin();
  });
}

document.addEventListener("DOMContentLoaded", main);
