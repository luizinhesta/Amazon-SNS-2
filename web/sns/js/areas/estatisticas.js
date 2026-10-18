/**
 * Estatísticas e configuração da visão geral do AWS SNS Delivery Lab (Tarefa 15.2).
 *
 * Preenche o ponto de extensão `[data-extension-point="overview-stats"]` da área
 * de visão geral com:
 *
 *  1. Estatísticas separadas por cenário Standard e FIFO (Req. 3.4-3.8, 3.10):
 *     - publicadas por tópico;
 *     - Entrega_Confirmada por fila de destino;
 *     - presentes por DLQ.
 *     Todos os contadores são inteiros ≥ 0 e exibem 0 quando ausentes. O horário
 *     da última atualização bem-sucedida (data/hora/fuso) aparece aqui e também no
 *     cabeçalho (`#last-update`). Em falha/timeout, os últimos valores são
 *     preservados e uma indicação visível de falha é mostrada (Req. 3.9).
 *
 *  2. Configuração com rótulos distintos de Config_Aplicada e Config_Simulacao
 *     (Req. 2.1-2.6). Os parâmetros de Config_Simulacao são ajustáveis dentro das
 *     faixas (Req. 2.7); valores fora da faixa são rejeitados preservando o valor
 *     anterior e exibindo a faixa válida em pt-BR (Req. 2.8). Para a Config_Aplicada
 *     é exibida a orientação de que a mudança só ocorre no Console AWS (Req. 2.9).
 *
 * Também exibe um indicador textual Entrega_Publicada × Entrega_Confirmada na
 * legenda das estatísticas (Req. 13.6).
 *
 * Esta tarefa NÃO implementa disparos, comparação, DLQ nem a atualização periódica
 * (Tarefas 15.3-15.5). A função `atualizarEstatisticas` é exportada para que a
 * Tarefa 15.5 possa reutilizá-la no ciclo periódico.
 *
 * Contratos consumidos (ver app/api/rotas_sns.py):
 *  - GET  /api/estatisticas     -> RespostaEstatisticasSns
 *  - GET  /api/config           -> RespostaConfigSns
 *  - PUT  /api/config/simulacao -> RespostaAjusteConfigSimulacaoSns
 */

import { ApiError } from "../api.js";

/** Mapeia o nome do parâmetro de Config_Simulacao ao campo aceito pelo PUT. */
const CAMPO_AJUSTE_POR_PARAMETRO = {
  Timeout_Verificacao_Entrega: "timeout_verificacao_entrega_segundos",
  Timeout_Verificacao_DLQ: "timeout_verificacao_dlq_segundos",
};

/** Nome do parâmetro de Config_Simulacao que carrega o intervalo de atualização. */
const NOME_PARAMETRO_INTERVALO = "Intervalo de atualização";

/**
 * Faixa válida do intervalo de atualização periódica, em segundos (Req. 13.2).
 * Mantida alinhada às constantes do backend (INTERVALO_ATUALIZACAO_MIN/MAX/PADRAO).
 * A Tarefa 15.5 (`atualizacao.js`) reutiliza esta faixa para validar o ajuste.
 */
export const FAIXA_INTERVALO_ATUALIZACAO = Object.freeze({
  min: 5,
  max: 300,
  padrao: 10,
});

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
 * Formata o horário ISO 8601 da última atualização bem-sucedida em uma string
 * legível em pt-BR com data, hora (com segundos) e fuso (Req. 3.8).
 *
 * @param {string|null} iso Horário em ISO 8601 (ou null quando ainda não houve).
 * @returns {string} Texto formatado ou um aviso de que ainda não houve atualização.
 */
function formatarUltimaAtualizacao(iso) {
  if (!iso) {
    return "Última atualização: ainda não houve atualização bem-sucedida.";
  }
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) {
    // Em caso de valor inesperado, exibe o próprio ISO para não perder informação.
    return `Última atualização bem-sucedida: ${iso}`;
  }
  // Usa o locale pt-BR com o fuso do navegador e inclui o nome do fuso (timeZoneName).
  // Observação: `dateStyle`/`timeStyle` NÃO podem ser combinados com `timeZoneName`
  // (a especificação do Intl.DateTimeFormat proíbe, e navegadores como o Chrome
  // lançam `TypeError: Invalid option`). Por isso usamos campos explícitos.
  const formatador = new Intl.DateTimeFormat("pt-BR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
  return `Última atualização bem-sucedida: ${formatador.format(data)}`;
}

/**
 * Garante que um contador seja apresentado como inteiro ≥ 0, usando 0 quando o
 * valor está ausente ou é inválido (Req. 3.10).
 *
 * @param {unknown} valor Valor recebido da API.
 * @returns {number} Inteiro não-negativo.
 */
function inteiroNaoNegativo(valor) {
  const n = Number(valor);
  if (!Number.isFinite(n) || n < 0) {
    return 0;
  }
  return Math.floor(n);
}

/**
 * Monta a lista de contadores (nome → valor) de um grupo de estatísticas, sempre
 * identificando cada recurso e exibindo 0 quando ausente (Req. 3.4-3.6, 3.10).
 *
 * @param {string} titulo Rótulo do grupo (ex.: "Publicadas por tópico").
 * @param {Array<{nome: string, valor: number}>} contadores Lista de contadores.
 * @returns {HTMLElement}
 */
function montarGrupoContadores(titulo, contadores) {
  const grupo = el("div", "stat-group");
  grupo.appendChild(el("h5", "stat-group-title", titulo));

  const lista = Array.isArray(contadores) ? contadores : [];
  if (lista.length === 0) {
    // Sem recursos informados: exibe uma linha neutra em vez de uma lista vazia.
    grupo.appendChild(el("p", "stat-empty", "Sem recursos informados (valor 0)."));
    return grupo;
  }

  const ul = el("ul", "stat-list");
  lista.forEach((contador) => {
    const li = el("li", "stat-item");
    li.appendChild(el("span", "stat-name", contador && contador.nome ? contador.nome : "—"));
    li.appendChild(
      el("span", "stat-value", String(inteiroNaoNegativo(contador && contador.valor)))
    );
    ul.appendChild(li);
  });
  grupo.appendChild(ul);
  return grupo;
}

/**
 * Monta o cartão de estatísticas de um cenário (Standard ou FIFO), separado e
 * rotulado (Req. 3.7), com os três grupos de contadores.
 *
 * @param {object|null} cenario Dados do cenário (ou null quando ausente).
 * @param {string} rotuloPadrao Rótulo a usar quando a API não informa um.
 * @returns {HTMLElement}
 */
function montarCartaoCenario(cenario, rotuloPadrao) {
  const card = el("article", "stat-card");
  const rotulo = (cenario && cenario.rotulo) || rotuloPadrao;
  card.setAttribute("aria-label", `Estatísticas do ${rotulo}`);

  card.appendChild(el("h4", "stat-card-title", rotulo));

  card.appendChild(
    montarGrupoContadores(
      "Publicadas por tópico (Entrega_Publicada)",
      cenario ? cenario.publicadas_por_topico : []
    )
  );
  card.appendChild(
    montarGrupoContadores(
      "Entrega_Confirmada por fila de destino",
      cenario ? cenario.confirmadas_por_fila : []
    )
  );
  card.appendChild(
    montarGrupoContadores(
      "Presentes por DLQ do SNS",
      cenario ? cenario.presentes_por_dlq : []
    )
  );

  return card;
}

/**
 * Desenha o bloco de estatísticas (dois cenários lado a lado) dentro do container.
 *
 * @param {object} estatisticas RespostaEstatisticasSns (ou últimos dados preservados).
 * @param {HTMLElement} container Elemento onde as estatísticas são desenhadas.
 */
function desenharEstatisticas(estatisticas, container) {
  container.innerHTML = "";

  // Indicador textual Entrega_Publicada × Entrega_Confirmada (Req. 13.6): deixa
  // claro que "publicadas" é aceitação do SNS e "confirmadas" é leitura real.
  const legenda = el("p", "stat-legenda");
  legenda.append(
    "Entrega_Publicada: o SNS aceitou a publicação (MessageId). ",
    "Entrega_Confirmada: a mensagem foi lida na fila de destino, correlacionada pelo ID_Pedido."
  );
  container.appendChild(legenda);

  const grade = el("div", "stat-grid");
  grade.appendChild(
    montarCartaoCenario(estatisticas && estatisticas.standard, "Cenário Standard")
  );
  grade.appendChild(
    montarCartaoCenario(estatisticas && estatisticas.fifo, "Cenário FIFO")
  );
  container.appendChild(grade);
}

/**
 * Monta uma linha de parâmetro de Config_Aplicada (somente leitura), com rótulo
 * distinto e a orientação de que a mudança só ocorre no Console AWS (Req. 2.6, 2.9).
 *
 * @param {object} parametro ParametroConfigSns de Config_Aplicada.
 * @returns {HTMLElement}
 */
function montarLinhaConfigAplicada(parametro) {
  const linha = el("div", "config-item config-item-aplicada");

  const cabecalho = el("div", "config-item-head");
  cabecalho.appendChild(el("span", "config-nome", parametro.nome || "—"));
  cabecalho.appendChild(el("span", "config-rotulo config-rotulo-aplicada", parametro.rotulo || "Config_Aplicada"));
  linha.appendChild(cabecalho);

  const valorTexto =
    parametro.unidade != null && parametro.unidade !== ""
      ? `${parametro.valor} ${parametro.unidade}`
      : String(parametro.valor);
  linha.appendChild(el("p", "config-valor", valorTexto));

  return linha;
}

/**
 * Monta uma linha de parâmetro de Config_Simulacao (ajustável), com o campo de
 * ajuste limitado à faixa (Req. 2.7) e uma área para mensagem de rejeição (Req. 2.8).
 *
 * @param {object} parametro ParametroConfigSns de Config_Simulacao.
 * @param {(parametro: object, valor: number, elementos: object) => void} aoAjustar
 *   Callback acionado ao confirmar um ajuste.
 * @returns {HTMLElement}
 */
function montarLinhaConfigSimulacao(parametro, aoAjustar) {
  const campoAjuste = CAMPO_AJUSTE_POR_PARAMETRO[parametro.nome];
  const linha = el("div", "config-item config-item-simulacao");

  const cabecalho = el("div", "config-item-head");
  cabecalho.appendChild(el("span", "config-nome", parametro.nome || "—"));
  cabecalho.appendChild(
    el("span", "config-rotulo config-rotulo-simulacao", parametro.rotulo || "Config_Simulacao")
  );
  linha.appendChild(cabecalho);

  // Identificadores únicos e previsíveis para associar label/input/mensagem.
  const idInput = `config-sim-${(parametro.nome || "param").replace(/\s+/g, "-")}`;
  const idMsg = `${idInput}-msg`;

  const corpo = el("div", "config-sim-corpo");

  // Quando o parâmetro não é ajustável por este endpoint (ex.: "Intervalo de
  // atualização", tratado pela Tarefa 15.5), exibe apenas o valor e a faixa.
  if (!campoAjuste) {
    const unidade = parametro.unidade ? ` ${parametro.unidade}` : "";
    corpo.appendChild(
      el(
        "p",
        "config-valor",
        `${parametro.valor}${unidade} (faixa ${parametro.faixa_minima}–${parametro.faixa_maxima}${unidade})`
      )
    );
    linha.appendChild(corpo);
    return linha;
  }

  const grupoCampo = el("div", "config-sim-campo");

  const label = el("label", "config-sim-label", `Novo valor (${parametro.faixa_minima}–${parametro.faixa_maxima}`);
  if (parametro.unidade) {
    label.append(` ${parametro.unidade}`);
  }
  label.append(")");
  label.setAttribute("for", idInput);
  grupoCampo.appendChild(label);

  const input = el("input", "config-sim-input");
  input.type = "number";
  input.id = idInput;
  input.min = String(parametro.faixa_minima);
  input.max = String(parametro.faixa_maxima);
  input.step = "1";
  input.value = String(parametro.valor);
  input.setAttribute("inputmode", "numeric");
  input.setAttribute("aria-describedby", idMsg);
  grupoCampo.appendChild(input);

  const botao = el("button", "btn btn-primary config-sim-aplicar", "Aplicar");
  botao.type = "button";
  grupoCampo.appendChild(botao);

  corpo.appendChild(grupoCampo);

  // Área de mensagem (sucesso ou faixa válida em rejeição). role=alert para que
  // leitores de tela anunciem a rejeição imediatamente (Req. 2.8).
  const mensagem = el("p", "config-sim-msg");
  mensagem.id = idMsg;
  mensagem.setAttribute("role", "alert");
  mensagem.setAttribute("aria-live", "assertive");
  mensagem.hidden = true;
  corpo.appendChild(mensagem);

  linha.appendChild(corpo);

  const elementos = { input, mensagem, botao, valorAnterior: parametro.valor };

  botao.addEventListener("click", () => {
    const bruto = input.value.trim();
    // Validação local amigável: evita enviar quando o campo está vazio.
    if (bruto === "") {
      mostrarMensagemConfig(
        mensagem,
        false,
        `Informe um valor entre ${parametro.faixa_minima} e ${parametro.faixa_maxima}` +
          `${parametro.unidade ? " " + parametro.unidade : ""}.`
      );
      input.value = String(elementos.valorAnterior);
      return;
    }
    const valor = Number(bruto);
    aoAjustar(parametro, valor, elementos);
  });

  return linha;
}

/**
 * Exibe uma mensagem de configuração (sucesso ou rejeição) na área indicada,
 * aplicando a classe de estado correspondente.
 *
 * @param {HTMLElement} elemento Elemento de mensagem.
 * @param {boolean} aceito Se o ajuste foi aceito.
 * @param {string} texto Texto em pt-BR a exibir.
 */
function mostrarMensagemConfig(elemento, aceito, texto) {
  elemento.textContent = texto;
  elemento.classList.toggle("is-erro", !aceito);
  elemento.classList.toggle("is-ok", aceito);
  elemento.hidden = false;
}

/**
 * Desenha o bloco de configuração (Config_Aplicada e Config_Simulacao) dentro do
 * container, ligando os campos de ajuste ao PUT /api/config/simulacao.
 *
 * @param {object} config RespostaConfigSns.
 * @param {object} ctx Contexto compartilhado ({ api }).
 * @param {HTMLElement} container Elemento onde a configuração é desenhada.
 * @param {() => void} aoAjustarComSucesso Callback após um ajuste aceito (reatualiza).
 */
function desenharConfig(config, ctx, container, aoAjustarComSucesso) {
  container.innerHTML = "";

  const aplicada = Array.isArray(config && config.config_aplicada)
    ? config.config_aplicada
    : [];
  const simulacao = Array.isArray(config && config.config_simulacao)
    ? config.config_simulacao
    : [];

  // --- Config_Simulacao (ajustável) ---
  const blocoSim = el("section", "config-bloco");
  blocoSim.setAttribute("aria-label", "Parâmetros de simulação (Config_Simulacao)");
  blocoSim.appendChild(el("h4", "config-bloco-title", "Config_Simulacao (ajustável)"));
  blocoSim.appendChild(
    el(
      "p",
      "config-bloco-hint",
      "Parâmetros usados apenas pela lógica de simulação da aplicação. Ajuste dentro da faixa indicada."
    )
  );

  /**
   * Envia o ajuste de um parâmetro ao backend e trata a resposta (aceito/rejeitado),
   * preservando o valor anterior quando rejeitado (Req. 2.8).
   */
  async function ajustar(parametro, valor, elementos) {
    const campo = CAMPO_AJUSTE_POR_PARAMETRO[parametro.nome];
    elementos.botao.disabled = true;
    try {
      const resposta = await ctx.api.ajustarConfigSimulacao({ [campo]: valor });
      const ajuste = (resposta.ajustes || []).find((a) => a.parametro === parametro.nome);

      if (ajuste && ajuste.aceito) {
        elementos.valorAnterior = ajuste.valor_efetivo;
        elementos.input.value = String(ajuste.valor_efetivo);
        mostrarMensagemConfig(
          elementos.mensagem,
          true,
          ajuste.mensagem || `Valor atualizado para ${ajuste.valor_efetivo}.`
        );
        // Reatualiza as estatísticas/config para refletir o novo estado.
        if (typeof aoAjustarComSucesso === "function") {
          aoAjustarComSucesso();
        }
      } else {
        // Rejeitado: restaura o valor anterior e exibe a faixa válida (pt-BR).
        const efetivo = ajuste ? ajuste.valor_efetivo : elementos.valorAnterior;
        elementos.valorAnterior = efetivo;
        elementos.input.value = String(efetivo);
        mostrarMensagemConfig(
          elementos.mensagem,
          false,
          (ajuste && ajuste.mensagem) ||
            `Valor fora da faixa (${parametro.faixa_minima}–${parametro.faixa_maxima}` +
              `${parametro.unidade ? " " + parametro.unidade : ""}). O valor anterior foi preservado.`
        );
      }
    } catch (erro) {
      // Falha de rede/servidor: preserva o valor anterior e indica a falha.
      elementos.input.value = String(elementos.valorAnterior);
      const detalhe =
        erro instanceof ApiError && typeof erro.detail === "string"
          ? ` (${erro.detail})`
          : "";
      mostrarMensagemConfig(
        elementos.mensagem,
        false,
        `Não foi possível ajustar o parâmetro no momento. O valor anterior foi preservado.${detalhe}`
      );
    } finally {
      elementos.botao.disabled = false;
    }
  }

  simulacao.forEach((parametro) => {
    blocoSim.appendChild(montarLinhaConfigSimulacao(parametro, ajustar));
  });
  if (simulacao.length === 0) {
    blocoSim.appendChild(el("p", "stat-empty", "Nenhum parâmetro de simulação disponível."));
  }
  container.appendChild(blocoSim);

  // --- Config_Aplicada (somente leitura) ---
  const blocoAplicada = el("section", "config-bloco");
  blocoAplicada.setAttribute("aria-label", "Parâmetros aplicados na AWS (Config_Aplicada)");
  blocoAplicada.appendChild(el("h4", "config-bloco-title", "Config_Aplicada (somente leitura)"));

  // Orientação em pt-BR de que a Config_Aplicada só muda no Console AWS (Req. 2.9).
  const orientacao = el(
    "p",
    "config-orientacao",
    (config && config.orientacao_config_aplicada) ||
      "Os parâmetros de Config_Aplicada só podem ser alterados manualmente no Console AWS."
  );
  orientacao.setAttribute("role", "note");
  blocoAplicada.appendChild(orientacao);

  aplicada.forEach((parametro) => {
    blocoAplicada.appendChild(montarLinhaConfigAplicada(parametro));
  });
  if (aplicada.length === 0) {
    blocoAplicada.appendChild(el("p", "stat-empty", "Nenhum parâmetro aplicado disponível."));
  }
  container.appendChild(blocoAplicada);
}

/**
 * Exibe/oculta a indicação de falha de atualização das estatísticas (Req. 3.9),
 * preservando os últimos valores já desenhados.
 *
 * @param {HTMLElement} elemento Elemento da indicação de falha.
 * @param {boolean} visivel Se a indicação deve aparecer.
 * @param {string} [texto] Texto da indicação quando visível.
 */
function indicarFalhaAtualizacao(elemento, visivel, texto) {
  if (!elemento) {
    return;
  }
  if (visivel) {
    elemento.textContent =
      texto ||
      "Não foi possível atualizar as estatísticas. Os últimos valores foram preservados.";
    elemento.hidden = false;
  } else {
    elemento.hidden = true;
    elemento.textContent = "";
  }
}

/**
 * Atualiza o rótulo do horário da última atualização bem-sucedida, tanto no bloco
 * de estatísticas quanto no cabeçalho (`#last-update`), quando disponível.
 *
 * @param {string|null} iso Horário em ISO 8601 do último sucesso.
 * @param {HTMLElement} elementoLocal Elemento do rótulo no bloco de estatísticas.
 */
function atualizarRotuloHorario(iso, elementoLocal) {
  const texto = formatarUltimaAtualizacao(iso);
  if (elementoLocal) {
    elementoLocal.textContent = texto;
  }
  const cabecalho = document.getElementById("last-update");
  if (cabecalho) {
    cabecalho.textContent = iso ? texto : "";
  }
}

/**
 * Estado interno da área de estatísticas: guarda os últimos dados válidos para
 * preservá-los em caso de falha/timeout (Req. 3.9) e os elementos renderizados.
 */
const estado = {
  ctx: null,
  elementos: null,
  ultimaEstatisticaValida: null,
  ultimaAtualizacaoValida: null,
  // Último intervalo de atualização informado pelo backend (Config_Simulacao),
  // consumido pela atualização periódica da Tarefa 15.5 (Req. 13.2).
  intervaloAtualizacaoConfig: null,
};

/**
 * Devolve o intervalo de atualização (em segundos) informado pelo backend em
 * Config_Simulacao, ou `null` quando ainda não foi carregado. A Tarefa 15.5 usa
 * este valor para iniciar o ciclo periódico com o mesmo padrão do backend.
 *
 * @returns {number|null}
 */
export function obterIntervaloAtualizacaoConfig() {
  return estado.intervaloAtualizacaoConfig;
}

/**
 * Carrega e desenha as estatísticas, aplicando a regra de preservação dos últimos
 * valores em caso de falha ou timeout (Req. 3.9, 3.10).
 *
 * Exportada para que a Tarefa 15.5 reutilize no ciclo de atualização periódica.
 *
 * @returns {Promise<void>}
 */
export async function atualizarEstatisticas() {
  if (!estado.ctx || !estado.elementos) {
    return;
  }
  const { api } = estado.ctx;
  const { blocoEstatisticas, horario, falha } = estado.elementos;

  try {
    const dados = await api.obterEstatisticas();

    if (dados && dados.timeout) {
      // Timeout no backend: preserva os últimos dados válidos e indica a falha,
      // mantendo inalterado o horário do último sucesso (Req. 3.9, 14.3).
      indicarFalhaAtualizacao(
        falha,
        true,
        dados.mensagem ||
          "A atualização das estatísticas excedeu o tempo limite. Os dados podem estar desatualizados."
      );
      return;
    }

    // Sucesso: desenha os novos dados e atualiza o horário/último estado válido.
    estado.ultimaEstatisticaValida = dados;
    estado.ultimaAtualizacaoValida = dados ? dados.ultima_atualizacao : null;
    desenharEstatisticas(dados, blocoEstatisticas);
    atualizarRotuloHorario(estado.ultimaAtualizacaoValida, horario);
    indicarFalhaAtualizacao(falha, false);
  } catch (erro) {
    // Falha de rede/servidor: preserva o que já estava desenhado (não redesenha)
    // e exibe a indicação visível de falha (Req. 3.9).
    const detalhe =
      erro instanceof ApiError && typeof erro.detail === "string"
        ? ` (${erro.detail})`
        : "";
    indicarFalhaAtualizacao(
      falha,
      true,
      `Não foi possível atualizar as estatísticas. Os últimos valores foram preservados.${detalhe}`
    );
  }
}

/**
 * Carrega e desenha a configuração (Config_Aplicada e Config_Simulacao). Em falha,
 * exibe uma indicação discreta sem derrubar a página.
 *
 * @returns {Promise<void>}
 */
async function atualizarConfig() {
  if (!estado.ctx || !estado.elementos) {
    return;
  }
  const { api } = estado.ctx;
  const { blocoConfig, falhaConfig } = estado.elementos;

  try {
    const config = await api.obterConfig();

    // Captura o intervalo de atualização de Config_Simulacao para a Tarefa 15.5.
    const parametros = Array.isArray(config && config.config_simulacao)
      ? config.config_simulacao
      : [];
    const parametroIntervalo = parametros.find(
      (p) => p && p.nome === NOME_PARAMETRO_INTERVALO
    );
    if (parametroIntervalo) {
      const valor = Number(parametroIntervalo.valor);
      if (Number.isFinite(valor)) {
        estado.intervaloAtualizacaoConfig = Math.floor(valor);
      }
    }

    desenharConfig(config, estado.ctx, blocoConfig, () => {
      // Após um ajuste aceito, reatualiza estatísticas e a própria config.
      atualizarEstatisticas();
      atualizarConfig();
    });
    if (falhaConfig) {
      falhaConfig.hidden = true;
    }
  } catch (erro) {
    if (falhaConfig) {
      const detalhe =
        erro instanceof ApiError && typeof erro.detail === "string"
          ? ` (${erro.detail})`
          : "";
      falhaConfig.textContent =
        `Não foi possível carregar a configuração no momento.${detalhe}`;
      falhaConfig.hidden = false;
    }
  }
}

/**
 * Renderiza o esqueleto do bloco de estatísticas e configuração dentro do ponto de
 * extensão `[data-extension-point="overview-stats"]` e carrega os dados.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function renderizarEstatisticasConfig(ctx) {
  const alvo = ctx.container.querySelector('[data-extension-point="overview-stats"]');
  if (!alvo) {
    return;
  }

  // Remove o placeholder da Tarefa 15.1, preservando o título da seção.
  const placeholder = alvo.querySelector(".area-placeholder");
  if (placeholder) {
    placeholder.remove();
  }

  // --- Estatísticas ---
  const secEstat = el("section", "stats-section");
  secEstat.setAttribute("aria-labelledby", "stats-section-heading");
  secEstat.appendChild(
    Object.assign(el("h4", "stats-section-heading", "Estatísticas por cenário"), {
      id: "stats-section-heading",
    })
  );

  const horario = el("p", "stats-horario");
  horario.setAttribute("role", "status");
  horario.setAttribute("aria-live", "polite");
  horario.textContent = formatarUltimaAtualizacao(null);
  secEstat.appendChild(horario);

  const falha = el("p", "stats-falha");
  falha.setAttribute("role", "alert");
  falha.setAttribute("aria-live", "assertive");
  falha.hidden = true;
  secEstat.appendChild(falha);

  const blocoEstatisticas = el("div", "stats-corpo");
  blocoEstatisticas.setAttribute("aria-live", "polite");
  secEstat.appendChild(blocoEstatisticas);

  alvo.appendChild(secEstat);

  // --- Configuração ---
  const secConfig = el("section", "config-section");
  secConfig.setAttribute("aria-labelledby", "config-section-heading");
  secConfig.appendChild(
    Object.assign(el("h4", "config-section-heading", "Configuração do laboratório"), {
      id: "config-section-heading",
    })
  );

  const falhaConfig = el("p", "stats-falha");
  falhaConfig.setAttribute("role", "alert");
  falhaConfig.setAttribute("aria-live", "assertive");
  falhaConfig.hidden = true;
  secConfig.appendChild(falhaConfig);

  const blocoConfig = el("div", "config-corpo");
  secConfig.appendChild(blocoConfig);

  alvo.appendChild(secConfig);

  // Guarda o contexto e os elementos para as atualizações.
  estado.ctx = ctx;
  estado.elementos = {
    blocoEstatisticas,
    horario,
    falha,
    blocoConfig,
    falhaConfig,
  };

  // Desenha um estado inicial vazio (0 em tudo) para render imediato e sem erro.
  desenharEstatisticas(null, blocoEstatisticas);

  // Carrega os dados reais (estatísticas e configuração) de forma independente.
  atualizarEstatisticas();
  atualizarConfig();
}
