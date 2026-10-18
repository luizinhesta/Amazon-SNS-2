/**
 * Área "COMPARAR STANDARD X FIFO" do Dashboard AWS SNS Delivery Lab (Tarefa 15.4).
 *
 * Preenche o ponto de extensão `[data-extension-point="comparar"]` com o painel de
 * comparação lado a lado dos dois testes independentes (Standard e FIFO), consumindo
 * POST /api/comparar. Para cada teste são exibidos (Req. 7.4, 7.5):
 *
 *  - o tipo do tópico (Standard ou FIFO) e o tópico utilizado;
 *  - a ordem de publicação (as três mensagens "Pedido criado", "Compra aprovada",
 *    "Pedido em preparação", com o MessageId de cada uma);
 *  - a ordem de recebimento observada por leitura real, sem reordenar, incluindo o
 *    MessageId lido e o estado "Não confirmado" quando a mensagem não foi
 *    confirmada no Timeout_Verificacao_Entrega (Req. 7.9).
 *
 * Exibe ainda o texto explicativo em pt-BR de que o Topico_Standard NÃO garante
 * ordenação, mesmo quando as mensagens chegam na sequência correta (Req. 7.6), e,
 * em interrupção (tópico indisponível ou falha de autenticação), a causa em pt-BR
 * (Req. 7.8).
 *
 * O botão COMPARAR é desabilitado enquanto o teste correspondente estiver ativo e
 * reabilitado ao concluir, refletindo o estado publicado por GET /api/testes/estado
 * — a fonte de verdade é o servidor (Req. 9.3, 9.4). O polling do estado é local a
 * esta área e encerrável via a função `encerrar()` exportada.
 *
 * Esta tarefa NÃO implementa a atualização periódica (Tarefa 15.5).
 *
 * Contratos consumidos (ver app/api/rotas_sns.py):
 *  - POST /api/comparar      -> RespostaCompararSns
 *  - GET  /api/testes/estado -> RespostaEstadoTestesSns ({ testes_ativos })
 */

import { ApiError } from "../api.js";

// Chave do teste no estado do servidor (ver TESTE_COMPARAR em estado_testes_sns.py).
const CHAVE_TESTE = "comparar";

// Faixa de validação do ID_Pedido, alinhada ao backend (validacao_disparo.py).
const ID_PEDIDO_MIN = 1;
const ID_PEDIDO_MAX = 80;

// Intervalo (ms) do polling que reflete o estado "teste ativo" do servidor no
// botão (Req. 9.3, 9.4), curto o bastante para refletir o fim do teste logo.
const INTERVALO_ESTADO_MS = 2000;

// Texto explicativo em pt-BR exibido mesmo antes de executar (Req. 7.6). O serviço
// também devolve `observacao`; usamos o valor do servidor quando presente.
const OBSERVACAO_PADRAO =
  "O Topico_Standard não garante ordenação: mesmo quando as três mensagens chegam " +
  "na sequência correta, isso é coincidência e não uma garantia. O Topico_FIFO " +
  "preserva a ordem de publicação dentro de um mesmo MessageGroupId.";

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
 * Valida localmente o ID_Pedido, devolvendo a mensagem em pt-BR quando inválido.
 * A validação local evita um ida-e-volta à API; o servidor continua sendo a
 * autoridade da regra (Req. 7.1).
 *
 * @param {string} valor Valor informado.
 * @returns {string|null} Mensagem de erro em pt-BR, ou null quando válido.
 */
function validarIdPedido(valor) {
  const tamanho = valor.length;
  if (tamanho < ID_PEDIDO_MIN || tamanho > ID_PEDIDO_MAX) {
    return `ID_Pedido inválido: informe de ${ID_PEDIDO_MIN} a ${ID_PEDIDO_MAX} caracteres.`;
  }
  return null;
}

/**
 * Monta a lista "ordem de publicação" de um teste: as três mensagens na ordem em
 * que foram publicadas, com a sequência, o conteúdo e o MessageId (Req. 7.4).
 *
 * @param {Array<object>} mensagens Lista de MensagemComparacaoSns.
 * @returns {HTMLElement}
 */
function montarOrdemPublicacao(mensagens) {
  const lista = el("ol", "cmp-ordem cmp-ordem-pub");
  lista.setAttribute("aria-label", "Ordem de publicação");
  const itens = Array.isArray(mensagens) ? mensagens : [];
  if (itens.length === 0) {
    lista.appendChild(el("li", "cmp-vazio", "Sem mensagens publicadas."));
    return lista;
  }
  itens.forEach((mensagem) => {
    const item = el("li", "cmp-ordem-item");
    item.appendChild(el("span", "cmp-ordem-conteudo", mensagem.conteudo || "—"));
    const detalhe = el("span", "cmp-ordem-detalhe");
    detalhe.append("MessageId: ");
    detalhe.appendChild(el("code", null, mensagem.message_id || "—"));
    item.appendChild(detalhe);
    lista.appendChild(item);
  });
  return lista;
}

/**
 * Monta a lista "ordem de recebimento" de um teste: as mensagens na ordem exata em
 * que foram lidas nas filas de destino, SEM reordenar. Cada posição não confirmada
 * aparece com o estado "Não confirmado" (Req. 7.4, 7.7, 7.9).
 *
 * @param {Array<object>} recebimentos Lista de ItemRecebimentoSns.
 * @returns {HTMLElement}
 */
function montarOrdemRecebimento(recebimentos) {
  const lista = el("ol", "cmp-ordem cmp-ordem-rec");
  lista.setAttribute("aria-label", "Ordem de recebimento");
  const itens = Array.isArray(recebimentos) ? recebimentos : [];
  if (itens.length === 0) {
    lista.appendChild(
      el("li", "cmp-vazio", "Nenhuma mensagem confirmada por leitura real.")
    );
    return lista;
  }
  itens.forEach((recebido) => {
    const confirmada = Boolean(recebido && recebido.confirmada);
    const item = el("li", "cmp-ordem-item");
    item.classList.add(confirmada ? "is-confirmada" : "is-nao-confirmada");

    const cabecalho = el("div", "cmp-rec-head");
    cabecalho.appendChild(
      el("span", "cmp-ordem-conteudo", (recebido && recebido.conteudo) || "—")
    );
    // Estado derivado: Entrega_Confirmada ou "Não confirmado" (Req. 7.9).
    const estadoTexto =
      (recebido && recebido.estado) ||
      (confirmada ? "Entrega_Confirmada" : "Não confirmado");
    cabecalho.appendChild(el("span", "cmp-estado", estadoTexto));
    item.appendChild(cabecalho);

    if (recebido && recebido.message_id) {
      const detalhe = el("span", "cmp-ordem-detalhe");
      detalhe.append("MessageId: ");
      detalhe.appendChild(el("code", null, recebido.message_id));
      item.appendChild(detalhe);
    }
    lista.appendChild(item);
  });
  return lista;
}

/**
 * Monta a coluna de um dos dois testes (Standard ou FIFO) do painel lado a lado.
 *
 * @param {object} teste ResultadoTesteComparacaoSns.
 * @returns {HTMLElement}
 */
function montarColunaTeste(teste) {
  const coluna = el("article", "cmp-coluna");
  const tipo = (teste && teste.tipo) || "—";
  coluna.setAttribute("aria-label", `Resultado do teste ${tipo}`);

  const header = el("header", "cmp-coluna-head");
  header.appendChild(el("h4", "cmp-coluna-tipo", tipo));
  if (teste && teste.topico) {
    header.appendChild(el("span", "cmp-coluna-topico", teste.topico));
  }
  coluna.appendChild(header);

  // Dados de correlação (ID_Pedido e, no FIFO, o MessageGroupId único).
  const meta = el("dl", "cmp-meta");
  const linha = (rotulo, valor) => {
    meta.appendChild(el("dt", "cmp-meta-rotulo", rotulo));
    meta.appendChild(
      el("dd", "cmp-meta-valor", valor != null && valor !== "" ? String(valor) : "—")
    );
  };
  linha("ID_Pedido", teste && teste.id_pedido);
  if (teste && teste.message_group_id) {
    linha("MessageGroupId", teste.message_group_id);
  }
  coluna.appendChild(meta);

  coluna.appendChild(el("h5", "cmp-sub", "Ordem de publicação"));
  coluna.appendChild(montarOrdemPublicacao(teste && teste.ordem_publicacao));

  coluna.appendChild(el("h5", "cmp-sub", "Ordem de recebimento (leitura real)"));
  coluna.appendChild(montarOrdemRecebimento(teste && teste.ordem_recebimento));

  return coluna;
}

/**
 * Desenha o resultado da comparação (dois testes lado a lado) ou a interrupção.
 *
 * @param {object} resposta RespostaCompararSns.
 * @param {HTMLElement} alvo Container de resultado.
 */
function desenharResultado(resposta, alvo) {
  alvo.innerHTML = "";

  // Interrupção (tópico indisponível ou autenticação) — Req. 7.8.
  if (resposta && resposta.interrompido) {
    const box = el("div", "cmp-falha");
    box.setAttribute("role", "alert");
    box.appendChild(el("strong", "cmp-falha-titulo", "Comparação interrompida"));
    box.appendChild(
      el(
        "p",
        "cmp-falha-msg",
        resposta.mensagem ||
          "A comparação foi interrompida: um tópico pode estar indisponível ou a " +
            "autenticação falhou."
      )
    );
    if (resposta.erro_original) {
      const detalhe = el("p", "cmp-falha-erro");
      detalhe.append("Erro original da AWS: ");
      detalhe.appendChild(el("code", null, resposta.erro_original));
      box.appendChild(detalhe);
    }
    alvo.appendChild(box);
    alvo.hidden = false;
    return;
  }

  // Painel lado a lado (Standard à esquerda, FIFO à direita) — Req. 7.5.
  const grade = el("div", "cmp-grade");
  if (resposta && resposta.standard) {
    grade.appendChild(montarColunaTeste(resposta.standard));
  }
  if (resposta && resposta.fifo) {
    grade.appendChild(montarColunaTeste(resposta.fifo));
  }
  if (!grade.childElementCount) {
    alvo.appendChild(
      el("p", "cmp-vazio", "A comparação não retornou resultados para exibir.")
    );
    alvo.hidden = false;
    return;
  }
  alvo.appendChild(grade);

  // Texto explicativo pt-BR: o Standard não garante ordenação (Req. 7.6).
  const observacao = el(
    "p",
    "cmp-observacao",
    (resposta && resposta.observacao) || OBSERVACAO_PADRAO
  );
  observacao.setAttribute("role", "note");
  alvo.appendChild(observacao);

  alvo.hidden = false;
}

/**
 * Inicializa a área de comparação Standard x FIFO: monta o formulário, liga a
 * submissão à API e inicia o polling do estado do botão.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function init(ctx) {
  // O container pode SER o próprio ponto de extensão ou contê-lo como descendente.
  const alvo = ctx.container.matches('[data-extension-point="comparar"]')
    ? ctx.container
    : ctx.container.querySelector('[data-extension-point="comparar"]');
  if (!alvo) {
    return;
  }

  // Remove o placeholder da Tarefa 15.1, preservando o título da área.
  const placeholder = alvo.querySelector(".area-placeholder");
  if (placeholder) {
    placeholder.remove();
  }

  // Texto explicativo pt-BR exibido já de início, antes mesmo de comparar (Req. 7.6).
  const intro = el("p", "cmp-intro", OBSERVACAO_PADRAO);
  alvo.appendChild(intro);

  const idInput = "comparar-id-pedido";
  const idMsg = `${idInput}-msg`;

  const form = el("form", "cmp-form");
  form.setAttribute("novalidate", "");
  form.setAttribute("aria-label", "Comparação Standard x FIFO");

  const campo = el("div", "field");
  const label = el(
    "label",
    null,
    `ID_Pedido (${ID_PEDIDO_MIN}–${ID_PEDIDO_MAX} caracteres)`
  );
  label.setAttribute("for", idInput);
  const input = el("input", "cmp-input");
  input.type = "text";
  input.id = idInput;
  input.name = "id_pedido";
  input.maxLength = ID_PEDIDO_MAX;
  input.required = true;
  input.setAttribute("aria-describedby", idMsg);
  const msg = el("p", "cmp-campo-msg");
  msg.id = idMsg;
  msg.setAttribute("role", "alert");
  msg.setAttribute("aria-live", "assertive");
  msg.hidden = true;
  campo.append(label, input, msg);
  form.appendChild(campo);

  const nota = el(
    "p",
    "cmp-nota",
    "A comparação executa dois testes independentes, publicando as mesmas três " +
      "mensagens em sequência. O teste FIFO usa um único MessageGroupId. A ordem de " +
      "recebimento é observada por leitura real, sem reordenar."
  );
  form.appendChild(nota);

  const botao = el("button", "btn btn-primary cmp-botao", "COMPARAR STANDARD X FIFO");
  botao.type = "submit";
  form.appendChild(botao);

  alvo.appendChild(form);

  const resultado = el("div", "cmp-resultado");
  resultado.setAttribute("aria-live", "polite");
  resultado.hidden = true;
  alvo.appendChild(resultado);

  // Estado local: controla o botão entre a submissão em andamento (local) e o
  // teste marcado como ativo no servidor (Req. 9.3, 9.4).
  const estado = {
    enviando: false,
    ativoServidor: false,
    pollId: null,
    encerrado: false,
  };

  /** Reflete no botão o estado combinado (enviando OU ativo no servidor). */
  function atualizarBotao() {
    const desabilitar = estado.enviando || estado.ativoServidor;
    botao.disabled = desabilitar;
    botao.textContent = desabilitar
      ? "Comparação em andamento…"
      : "COMPARAR STANDARD X FIFO";
  }

  /** Consulta GET /api/testes/estado e reflete o botão deste teste (Req. 9.3, 9.4). */
  async function sincronizarEstado() {
    try {
      const dados = await ctx.api.obterEstadoTestes();
      const mapa = (dados && dados.testes_ativos) || {};
      estado.ativoServidor = Boolean(mapa[CHAVE_TESTE]);
    } catch {
      // Falha ao consultar o estado não deve travar o botão: assume inativo no
      // servidor e mantém apenas a trava local da submissão em andamento.
      estado.ativoServidor = false;
    }
    if (!estado.encerrado) {
      atualizarBotao();
    }
  }

  /** Valida o campo localmente, preservando o valor informado. */
  function validarLocal() {
    const erro = validarIdPedido(input.value);
    if (erro) {
      msg.textContent = erro;
      msg.hidden = false;
      input.setAttribute("aria-invalid", "true");
      return false;
    }
    msg.textContent = "";
    msg.hidden = true;
    input.removeAttribute("aria-invalid");
    return true;
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (estado.enviando || estado.ativoServidor) {
      return;
    }
    if (!validarLocal()) {
      return;
    }

    estado.enviando = true;
    atualizarBotao();
    resultado.hidden = true;

    try {
      const resposta = await ctx.api.comparar({ id_pedido: input.value });
      desenharResultado(resposta, resultado);
    } catch (erro) {
      // Falha de rede/servidor: preserva o valor informado e indica a falha.
      const detalhe =
        erro instanceof ApiError && typeof erro.detail === "string"
          ? ` (${erro.detail})`
          : "";
      resultado.innerHTML = "";
      const box = el("div", "cmp-falha");
      box.setAttribute("role", "alert");
      box.appendChild(
        el("strong", "cmp-falha-titulo", "Não foi possível comparar")
      );
      box.appendChild(
        el(
          "p",
          "cmp-falha-msg",
          `Não foi possível concluir a comparação no momento. O valor informado foi preservado.${detalhe}`
        )
      );
      resultado.appendChild(box);
      resultado.hidden = false;
    } finally {
      estado.enviando = false;
      // Sincroniza imediatamente com o servidor para refletir o fim do teste.
      await sincronizarEstado();
    }
  });

  // Inicia o polling do estado do botão e faz uma primeira sincronização.
  sincronizarEstado();
  estado.pollId = window.setInterval(sincronizarEstado, INTERVALO_ESTADO_MS);

  // Guarda a função de limpeza para o encerramento da área (logout).
  encerrarPolling = function encerrar() {
    estado.encerrado = true;
    if (estado.pollId != null) {
      window.clearInterval(estado.pollId);
      estado.pollId = null;
    }
  };
}

// Referência para a função de limpeza do polling, exposta via `encerrar()`.
let encerrarPolling = null;

/**
 * Encerra os recursos vivos da área (polling do estado do botão). Chamado quando o
 * painel é desmontado (logout), em paralelo às demais áreas.
 */
export function encerrar() {
  if (typeof encerrarPolling === "function") {
    encerrarPolling();
    encerrarPolling = null;
  }
}
