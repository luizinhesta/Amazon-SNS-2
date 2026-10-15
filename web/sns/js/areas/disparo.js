/**
 * Formulário de disparo compartilhado pelas áreas "DISPARAR SNS STANDARD" e
 * "DISPARAR SNS FIFO" do Dashboard AWS SNS Delivery Lab (Tarefa 15.3).
 *
 * As duas áreas de disparo compartilham a mesma estrutura de interação:
 *
 *  1. Um formulário com validação em pt-BR do ID_Pedido (1-80 caracteres) e, no
 *     cenário FIFO, do MessageGroupId (1-128 caracteres). O MessageDeduplicationId
 *     NÃO é solicitado: a Deduplicacao_Por_Conteudo do Topico_FIFO está habilitada,
 *     de modo que o SNS o deriva do conteúdo (Req. 5.4). (Req. 4.1, 5.1, 5.2, 5.3)
 *  2. O botão de disparo é desabilitado enquanto o teste correspondente estiver
 *     ativo e reabilitado ao concluir, refletindo o estado publicado por
 *     GET /api/testes/estado — a fonte de verdade é o servidor (Req. 9.3, 9.4).
 *  3. Após a publicação, exibe tópico, tipo, ID_Pedido, (MessageGroupId no FIFO),
 *     MessageId e os três destinos (Destino_1/2/3) com o estado derivado
 *     Entrega_Confirmada/Não confirmado, além da notificação APENAS visual
 *     "Seu pedido foi aprovado e está sendo preparado" (Req. 4.4, 4.5, 5.7).
 *  4. Ao rejeitar a validação (local ou do servidor), preserva os valores
 *     informados e aponta os campos inválidos em pt-BR (Req. 4.7, 5.9).
 *
 * Exibe também o indicador textual distinto Entrega_Publicada × Entrega_Confirmada
 * por mensagem (Req. 13.6): "Entrega_Publicada" é a aceitação da publicação pelo
 * SNS (MessageId); "Entrega_Confirmada" é a leitura real na fila de destino,
 * correlacionada pelo ID_Pedido.
 *
 * Esta tarefa NÃO implementa a comparação, a DLQ nem a atualização periódica
 * (Tarefas 15.4 e 15.5). O polling do estado dos botões é local a este formulário
 * e encerrável via a função retornada por `montarFormularioDisparo`.
 *
 * Contratos consumidos (ver app/api/rotas_sns.py):
 *  - POST /api/disparar/standard -> RespostaDisparoSns
 *  - POST /api/disparar/fifo     -> RespostaDisparoSns
 *  - GET  /api/testes/estado     -> RespostaEstadoTestesSns ({ testes_ativos })
 */

import { ApiError } from "../api.js";

// Faixas de validação alinhadas às constantes do backend (validacao_disparo.py).
const ID_PEDIDO_MIN = 1;
const ID_PEDIDO_MAX = 80;
const MESSAGE_GROUP_ID_MIN = 1;
const MESSAGE_GROUP_ID_MAX = 128;

// Intervalo (ms) do polling que reflete o estado "teste ativo" do servidor nos
// botões (Req. 9.3, 9.4). Curto o bastante para refletir o fim do teste logo.
const INTERVALO_ESTADO_MS = 2000;

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
 * A validação local evita um ida-e-volta à API e espelha a regra do servidor,
 * que continua sendo a autoridade (Req. 4.1, 5.1).
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
 * Valida localmente o MessageGroupId (apenas FIFO), devolvendo a mensagem em pt-BR
 * quando inválido. FIFO sem MessageGroupId é sempre rejeitado (Req. 5.2, 11.5).
 *
 * @param {string} valor Valor informado.
 * @returns {string|null} Mensagem de erro em pt-BR, ou null quando válido.
 */
function validarMessageGroupId(valor) {
  const tamanho = valor.length;
  if (tamanho < MESSAGE_GROUP_ID_MIN) {
    return (
      "MessageGroupId é obrigatório para publicação FIFO: informe de " +
      `${MESSAGE_GROUP_ID_MIN} a ${MESSAGE_GROUP_ID_MAX} caracteres.`
    );
  }
  if (tamanho > MESSAGE_GROUP_ID_MAX) {
    return `MessageGroupId inválido: informe de ${MESSAGE_GROUP_ID_MIN} a ${MESSAGE_GROUP_ID_MAX} caracteres.`;
  }
  return null;
}

/**
 * Exibe (ou limpa) a mensagem de erro de um campo, alternando o estado de
 * validade acessível (aria-invalid) do input associado (Req. 4.7, 5.9).
 *
 * @param {HTMLInputElement} input Campo associado.
 * @param {HTMLElement} elementoMsg Elemento onde a mensagem é exibida.
 * @param {string|null} mensagem Mensagem em pt-BR, ou null para limpar.
 */
function marcarCampo(input, elementoMsg, mensagem) {
  if (mensagem) {
    elementoMsg.textContent = mensagem;
    elementoMsg.hidden = false;
    input.setAttribute("aria-invalid", "true");
  } else {
    elementoMsg.textContent = "";
    elementoMsg.hidden = true;
    input.removeAttribute("aria-invalid");
  }
}

/**
 * Monta a legenda textual Entrega_Publicada × Entrega_Confirmada (Req. 13.6).
 *
 * @returns {HTMLElement}
 */
function montarLegendaEstados() {
  const legenda = el("p", "disparo-legenda");
  legenda.append(
    "Entrega_Publicada: o SNS aceitou a publicação (MessageId). ",
    "Entrega_Confirmada: a mensagem foi lida na fila de destino, correlacionada pelo ID_Pedido."
  );
  return legenda;
}

/**
 * Desenha o resultado de um disparo aceito dentro do container de resultado:
 * notificação visual, dados da publicação (tópico, tipo, ID_Pedido, MessageGroupId
 * no FIFO, MessageId) e os três destinos com o estado derivado (Req. 4.4, 4.5, 5.7).
 *
 * @param {object} resposta RespostaDisparoSns (aceito=true).
 * @param {boolean} ehFifo Se o cenário é FIFO (exibe o MessageGroupId).
 * @param {HTMLElement} alvo Container de resultado.
 */
function desenharResultado(resposta, ehFifo, alvo) {
  alvo.innerHTML = "";

  // Notificação APENAS visual (Req. 4.5, 4.6, 5.8). O laboratório não envia SMS
  // nem e-mail reais; este texto é apresentado no Dashboard.
  const notificacao = el("div", "disparo-notificacao");
  notificacao.setAttribute("role", "status");
  notificacao.append(
    el("span", "disparo-notificacao-icone", "✅"),
    el(
      "span",
      "disparo-notificacao-texto",
      resposta.notificacao_visual || "Seu pedido foi aprovado e está sendo preparado"
    )
  );
  alvo.appendChild(notificacao);

  // Dados da publicação (Entrega_Publicada) — Req. 4.4, 5.6, 5.7.
  const resumo = el("dl", "disparo-resumo");
  const linha = (rotulo, valor) => {
    resumo.appendChild(el("dt", "disparo-resumo-rotulo", rotulo));
    resumo.appendChild(el("dd", "disparo-resumo-valor", valor != null && valor !== "" ? String(valor) : "—"));
  };
  linha("Tópico", resposta.topico);
  linha("Tipo", resposta.tipo);
  linha("ID_Pedido", resposta.id_pedido);
  if (ehFifo) {
    linha("MessageGroupId", resposta.message_group_id);
  }
  linha("MessageId (Entrega_Publicada)", resposta.message_id);
  alvo.appendChild(resumo);

  // Legenda Entrega_Publicada × Entrega_Confirmada (Req. 13.6).
  alvo.appendChild(montarLegendaEstados());

  // Os três destinos com o estado derivado por leitura real (Req. 4.4, 5.7).
  const tituloDestinos = el("h4", "disparo-destinos-titulo", "Destinos (verificação por leitura real)");
  alvo.appendChild(tituloDestinos);

  const lista = el("ul", "disparo-destinos");
  const destinos = Array.isArray(resposta.destinos) ? resposta.destinos : [];
  if (destinos.length === 0) {
    alvo.appendChild(el("p", "disparo-vazio", "Nenhum destino verificado."));
  } else {
    destinos.forEach((destino) => {
      const item = el("li", "disparo-destino");
      const confirmada = Boolean(destino && destino.confirmada);
      item.classList.add(confirmada ? "is-confirmada" : "is-nao-confirmada");

      const cabecalho = el("div", "disparo-destino-head");
      cabecalho.appendChild(
        el("span", "disparo-destino-titulo", (destino && destino.titulo_destino) || (destino && destino.destino) || "—")
      );
      // Estado derivado: Entrega_Confirmada ou "Não confirmado" (Req. 6.2, 6.6).
      const estadoTexto = (destino && destino.estado) || (confirmada ? "Entrega_Confirmada" : "Não confirmado");
      const badge = el("span", "disparo-destino-estado", estadoTexto);
      cabecalho.appendChild(badge);
      item.appendChild(cabecalho);

      const detalhe = el("p", "disparo-destino-detalhe");
      detalhe.append(`Fila: ${(destino && destino.fila_destino) || "—"}`);
      if (destino && destino.message_id) {
        detalhe.append(` · MessageId: ${destino.message_id}`);
      }
      item.appendChild(detalhe);

      lista.appendChild(item);
    });
    alvo.appendChild(lista);
  }

  alvo.hidden = false;
}

/**
 * Desenha uma falha de publicação (o SNS não aceitou), preservando os valores já
 * informados no formulário e exibindo o erro original repassado (Req. 4.8, 5.10).
 *
 * @param {object} resposta RespostaDisparoSns (falha_publicacao=true).
 * @param {HTMLElement} alvo Container de resultado.
 */
function desenharFalhaPublicacao(resposta, alvo) {
  alvo.innerHTML = "";
  const box = el("div", "disparo-falha");
  box.setAttribute("role", "alert");
  box.appendChild(el("strong", "disparo-falha-titulo", "Falha na publicação"));
  box.appendChild(
    el(
      "p",
      "disparo-falha-msg",
      resposta.mensagem ||
        "A publicação não foi aceita pelo SNS; nenhuma entrega foi confirmada."
    )
  );
  if (resposta.erro_original) {
    const detalhe = el("p", "disparo-falha-erro");
    detalhe.append("Erro original da AWS: ");
    detalhe.appendChild(el("code", null, resposta.erro_original));
    box.appendChild(detalhe);
  }
  alvo.appendChild(box);
  alvo.hidden = false;
}

/**
 * Monta o formulário de disparo (Standard ou FIFO) dentro do ponto de extensão da
 * área, liga a submissão à API e inicia o polling do estado do botão.
 *
 * @param {object} opcoes Configuração do formulário.
 * @param {{ api: object, container: HTMLElement }} opcoes.ctx Contexto compartilhado.
 * @param {string} opcoes.pontoExtensao Seletor data-extension-point da área.
 * @param {boolean} opcoes.ehFifo Se o formulário é do cenário FIFO.
 * @param {string} opcoes.chaveTeste Chave do teste no estado do servidor
 *   (ex.: "disparar_standard" ou "disparar_fifo"), para refletir o botão.
 * @param {(req: object) => Promise<object>} opcoes.disparar Método da API a chamar.
 * @returns {() => void} Função que encerra o polling (usada no logout/limpeza).
 */
export function montarFormularioDisparo(opcoes) {
  const { ctx, pontoExtensao, ehFifo, chaveTeste, disparar } = opcoes;
  const alvo = ctx.container.querySelector(`[data-extension-point="${pontoExtensao}"]`);
  if (!alvo) {
    return () => {};
  }

  // Remove o placeholder da Tarefa 15.1, preservando o título da área.
  const placeholder = alvo.querySelector(".area-placeholder");
  if (placeholder) {
    placeholder.remove();
  }

  // Identificadores previsíveis para associar label/input/mensagem.
  const prefixo = ehFifo ? "fifo" : "standard";
  const idInputPedido = `${prefixo}-id-pedido`;
  const idMsgPedido = `${idInputPedido}-msg`;
  const idInputGrupo = `${prefixo}-message-group-id`;
  const idMsgGrupo = `${idInputGrupo}-msg`;

  const form = el("form", "disparo-form");
  form.setAttribute("novalidate", "");
  form.setAttribute(
    "aria-label",
    ehFifo ? "Disparo SNS FIFO" : "Disparo SNS Standard"
  );

  // --- Campo ID_Pedido (ambos os cenários) ---
  const grupoPedido = el("div", "field");
  const labelPedido = el("label", null, `ID_Pedido (${ID_PEDIDO_MIN}–${ID_PEDIDO_MAX} caracteres)`);
  labelPedido.setAttribute("for", idInputPedido);
  const inputPedido = el("input", "disparo-input");
  inputPedido.type = "text";
  inputPedido.id = idInputPedido;
  inputPedido.name = "id_pedido";
  inputPedido.maxLength = ID_PEDIDO_MAX;
  inputPedido.required = true;
  inputPedido.setAttribute("aria-describedby", idMsgPedido);
  const msgPedido = el("p", "disparo-campo-msg");
  msgPedido.id = idMsgPedido;
  msgPedido.setAttribute("role", "alert");
  msgPedido.setAttribute("aria-live", "assertive");
  msgPedido.hidden = true;
  grupoPedido.append(labelPedido, inputPedido, msgPedido);
  form.appendChild(grupoPedido);

  // --- Campo MessageGroupId (apenas FIFO) ---
  let inputGrupo = null;
  let msgGrupo = null;
  if (ehFifo) {
    const grupoGrupo = el("div", "field");
    const labelGrupo = el(
      "label",
      null,
      `MessageGroupId (${MESSAGE_GROUP_ID_MIN}–${MESSAGE_GROUP_ID_MAX} caracteres)`
    );
    labelGrupo.setAttribute("for", idInputGrupo);
    inputGrupo = el("input", "disparo-input");
    inputGrupo.type = "text";
    inputGrupo.id = idInputGrupo;
    inputGrupo.name = "message_group_id";
    inputGrupo.maxLength = MESSAGE_GROUP_ID_MAX;
    inputGrupo.required = true;
    inputGrupo.setAttribute("aria-describedby", `${idMsgGrupo} ${prefixo}-dedup-nota`);
    msgGrupo = el("p", "disparo-campo-msg");
    msgGrupo.id = idMsgGrupo;
    msgGrupo.setAttribute("role", "alert");
    msgGrupo.setAttribute("aria-live", "assertive");
    msgGrupo.hidden = true;
    grupoGrupo.append(labelGrupo, inputGrupo, msgGrupo);
    form.appendChild(grupoGrupo);

    // Nota pt-BR: o MessageDeduplicationId não é solicitado porque a
    // Deduplicacao_Por_Conteudo está habilitada no Topico_FIFO (Req. 5.4).
    const notaDedup = el(
      "p",
      "disparo-nota",
      "O MessageDeduplicationId não é solicitado: a deduplicação por conteúdo está " +
        "habilitada no Topico_FIFO, então o SNS o deriva automaticamente do conteúdo da mensagem."
    );
    notaDedup.id = `${prefixo}-dedup-nota`;
    form.appendChild(notaDedup);

    // Texto pt-BR: a ordenação FIFO é garantida dentro de um MessageGroupId (Req. 11.4).
    const notaOrdenacao = el(
      "p",
      "disparo-nota",
      "A ordenação FIFO é garantida apenas dentro de um mesmo MessageGroupId: " +
        "mensagens com o mesmo MessageGroupId são entregues na ordem de publicação."
    );
    form.appendChild(notaOrdenacao);
  }

  // --- Botão de disparo ---
  const botao = el(
    "button",
    "btn btn-primary disparo-botao",
    ehFifo ? "DISPARAR SNS FIFO" : "DISPARAR SNS STANDARD"
  );
  botao.type = "submit";
  form.appendChild(botao);

  alvo.appendChild(form);

  // --- Área de resultado (resumo + destinos + notificação) ---
  const resultado = el("div", "disparo-resultado");
  resultado.setAttribute("aria-live", "polite");
  resultado.hidden = true;
  alvo.appendChild(resultado);

  // Estado local do formulário: controla o botão entre o teste ativo (servidor) e
  // a submissão em andamento (local), para não reabilitar no meio de um disparo.
  const estado = {
    enviando: false, // submissão deste cliente em andamento
    ativoServidor: false, // teste marcado como ativo no servidor (outro cliente ou este)
    pollId: null,
    encerrado: false,
  };

  /** Reflete no botão o estado combinado (enviando OU ativo no servidor). */
  function atualizarBotao() {
    const desabilitar = estado.enviando || estado.ativoServidor;
    botao.disabled = desabilitar;
    botao.textContent = desabilitar
      ? "Teste em andamento…"
      : ehFifo
        ? "DISPARAR SNS FIFO"
        : "DISPARAR SNS STANDARD";
  }

  /** Consulta GET /api/testes/estado e reflete o botão deste teste (Req. 9.3, 9.4). */
  async function sincronizarEstado() {
    try {
      const dados = await ctx.api.obterEstadoTestes();
      const mapa = (dados && dados.testes_ativos) || {};
      estado.ativoServidor = Boolean(mapa[chaveTeste]);
    } catch {
      // Falha ao consultar o estado não deve travar o botão: assume inativo no
      // servidor e mantém apenas a trava local da submissão em andamento.
      estado.ativoServidor = false;
    }
    if (!estado.encerrado) {
      atualizarBotao();
    }
  }

  /** Valida os campos localmente e devolve se o formulário está válido. */
  function validarLocal() {
    const erroPedido = validarIdPedido(inputPedido.value);
    marcarCampo(inputPedido, msgPedido, erroPedido);

    let erroGrupo = null;
    if (ehFifo) {
      erroGrupo = validarMessageGroupId(inputGrupo.value);
      marcarCampo(inputGrupo, msgGrupo, erroGrupo);
    }
    return !erroPedido && !erroGrupo;
  }

  /** Aplica no formulário os campos inválidos devolvidos pelo servidor (Req. 4.7, 5.9). */
  function aplicarRejeicaoServidor(resposta) {
    const mensagens = (resposta && resposta.mensagens) || {};
    const campos = Array.isArray(resposta && resposta.campos_invalidos)
      ? resposta.campos_invalidos
      : [];
    if (campos.includes("id_pedido")) {
      marcarCampo(inputPedido, msgPedido, mensagens.id_pedido || "ID_Pedido inválido.");
    }
    if (ehFifo && campos.includes("message_group_id")) {
      marcarCampo(inputGrupo, msgGrupo, mensagens.message_group_id || "MessageGroupId inválido.");
    }
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (estado.enviando || estado.ativoServidor) {
      return;
    }

    // Validação local primeiro, preservando os valores informados (Req. 4.7, 5.9).
    if (!validarLocal()) {
      return;
    }

    estado.enviando = true;
    atualizarBotao();
    resultado.hidden = true;

    try {
      const requisicao = ehFifo
        ? { id_pedido: inputPedido.value, message_group_id: inputGrupo.value }
        : { id_pedido: inputPedido.value };
      const resposta = await disparar(requisicao);

      if (resposta && resposta.aceito) {
        desenharResultado(resposta, ehFifo, resultado);
      } else if (resposta && resposta.falha_publicacao) {
        desenharFalhaPublicacao(resposta, resultado);
      } else {
        // Rejeição de validação do servidor: aponta os campos e preserva valores.
        aplicarRejeicaoServidor(resposta);
      }
    } catch (erro) {
      // Falha de rede/servidor: preserva os valores do formulário e indica a falha.
      const detalhe =
        erro instanceof ApiError && typeof erro.detail === "string"
          ? ` (${erro.detail})`
          : "";
      resultado.innerHTML = "";
      const box = el("div", "disparo-falha");
      box.setAttribute("role", "alert");
      box.appendChild(el("strong", "disparo-falha-titulo", "Não foi possível disparar"));
      box.appendChild(
        el(
          "p",
          "disparo-falha-msg",
          `Não foi possível concluir o disparo no momento. Os valores informados foram preservados.${detalhe}`
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

  // Função de limpeza: encerra o polling (usada no logout/reinicialização).
  return function encerrar() {
    estado.encerrado = true;
    if (estado.pollId != null) {
      window.clearInterval(estado.pollId);
      estado.pollId = null;
    }
  };
}
