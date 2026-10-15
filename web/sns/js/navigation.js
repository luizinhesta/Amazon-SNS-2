/**
 * Navegação entre as áreas do Dashboard AWS SNS Delivery Lab (Tarefa 15.1).
 *
 * As áreas são: overview (visão geral + arquitetura) e as quatro ações principais
 * do laboratório — standard ("DISPARAR SNS STANDARD"), fifo ("DISPARAR SNS FIFO"),
 * comparar ("COMPARAR STANDARD X FIFO") e dlq ("TESTAR DLQ DO SNS").
 *
 * Cada botão de navegação tem `data-area` e cada seção de conteúdo tem o id
 * `<area>-area` e o mesmo `data-area`, o que mantém a navegação desacoplada do
 * conteúdo que as Tarefas 15.2 a 15.5 preencherão.
 */

/** Identificadores das áreas, na ordem exibida na navegação. */
export const AREAS = ["overview", "standard", "fifo", "comparar", "dlq"];

/**
 * Inicializa a navegação por abas entre as áreas.
 *
 * @param {object} [options]
 * @param {(area: string) => void} [options.onChange] Callback ao trocar de área;
 *   recebe o identificador da área ativada. As áreas usam isso para carregar/
 *   atualizar seus dados sob demanda (Tarefas 15.2-15.5).
 * @returns {{ activate: (area: string) => void, current: () => string }}
 */
export function setupNavigation({ onChange } = {}) {
  const navItems = Array.from(document.querySelectorAll(".nav-item"));
  const sections = Array.from(document.querySelectorAll(".area"));
  let areaAtual = AREAS[0];

  /**
   * Ativa uma área: destaca o botão, exibe a seção correspondente e oculta as
   * demais. Áreas desconhecidas são ignoradas.
   *
   * @param {string} area Identificador da área a ativar.
   */
  function activate(area) {
    if (!AREAS.includes(area)) {
      return;
    }
    areaAtual = area;

    navItems.forEach((item) => {
      const ativo = item.dataset.area === area;
      item.classList.toggle("is-active", ativo);
      item.setAttribute("aria-current", ativo ? "page" : "false");
    });

    sections.forEach((section) => {
      const ativa = section.dataset.area === area;
      section.classList.toggle("is-active", ativa);
      section.hidden = !ativa;
    });

    if (typeof onChange === "function") {
      onChange(area);
    }
  }

  navItems.forEach((item) => {
    item.addEventListener("click", () => activate(item.dataset.area));
  });

  return {
    activate,
    current: () => areaAtual,
  };
}
