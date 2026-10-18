/**
 * Área "TESTAR DLQ DO SNS" do Dashboard AWS SNS Delivery Lab (Tarefa 15.4).
 *
 * Preenche o ponto de extensão `[data-extension-point="dlq"]` com o painel de teste
 * de DLQ do SNS, consumindo POST /api/dlq/simular-falha. O fluxo é a
 * Falha_Entrega_Controlada: reversível, segura e SEMPRE manual (Req. 8.10).
 *
 * O painel oferece (Req. 8.*):
 *  - seleção de uma Assinatura_SNS específica, identificada por cenário
 *    (Standard/FIFO) e destino (destino_1/2/3), além de um ID_Pedido de teste
 *    (Req. 8.1). Os rótulos das filas de destino são enriquecidos, quando possível,
 *    com os nomes reais vindos de GET /api/arquitetura;
 *  - o botão "SIMULAR FALHA DE ENTREGA", de acionamento manual (Req. 8.1, 8.10);
 *  - a exibição do resultado na DLQ como Evento_Observado quando a mensagem é
 *    confirmada na DLQ compatível (Req. 8.6) e o estado "Não confirmado" ao esgotar
 *    o Timeout_Verificacao_DLQ (Req. 8.7);
 *  - o resultado das demais assinaturas do mesmo tópico (Req. 8.4);
 *  - a confirmação de que a Access_Policy_Fila foi restaurada e, em falha, a
 *    orientação em pt-BR para restaurar manualmente pelo Console AWS (Req. 8.8, 8.9);
 *  - o texto explicativo em pt-BR sobre a DLQ do SNS, configurada na assinatura
 *    (Req. 8.11).
 *
 * O botão "SIMULAR FALHA DE ENTREGA"/TESTAR DLQ é desabilitado enquanto o teste
 * estiver ativo e reabilitado ao concluir, refletindo GET /api/testes/estado — a
 * fonte de verdade é o servidor (Req. 9.3, 9.4). O polling é local a esta área e
 * encerrável via a função `encerrar()` exportada.
 *
 * Esta tarefa NÃO implementa a atualização periódica (Tarefa 15.5).
 *
 * Contratos consumidos (ver app/api/rotas_sns.py):
 *  - POST /api/dlq/simular-falha -> RespostaSimularFalhaDlqSns
 *  - GET  /api/arquitetura       -> RespostaArquiteturaSns (assinaturas, filas)
 *  - GET  /api/testes/estado     -> RespostaEstadoTestesSns ({ testes_ativos })
 */

import { ApiError } from "../api.js";

// Chave do teste no estado do servidor (ver TESTE_DLQ em estado_testes_sns.py).
const CHAVE_TESTE = "dlq";

// Faixa de validação do ID_Pedido, alinhada ao backend (validacao_disparo.py).
const ID_PEDIDO_MIN = 1;
const ID_PEDIDO_MAX = 80;

// Intervalo (ms) do polling que reflete o estado "teste ativo" do servidor no
// botão (Req. 9.3, 9.4).
const INTERVALO_ESTADO_MS = 2000;

// Texto explicativo em pt-BR sobre a DLQ do SNS, exibido sempre (Req. 8.11). O
// serviço também devolve `texto_explicativo`; usamos o do servidor quando presente.
const EXPLICACAO_PADRAO =
  "A DLQ (Dead-Letter Queue) do SNS é configurada na assinatura (Redrive_Policy_SNS) " +
  "e recebe as mensagens que o SNS não conseguiu entregar à fila de destino após as " +
  "tentativas de reenvio. Neste teste, a Access_Policy_Fila da fila selecionada é " +
  "ajustada temporariamente para negar o recebimento vindo do SNS, provocando uma " +
  "falha de entrega controlada; a mensagem é então encaminhada para a DLQ do SNS. A " +
  "alteração é reversível e a policy original é restaurada ao final.";

// As seis Assinatura_SNS do laboratório (dois cenários × três destinos). O
// backend identifica a assinatura por cenário + destino (ver SimularFalhaDlqSns).
const CENARIOS = [
  { valor: "standard", rotulo: "Standard", tipo: "Standard" },
  { valor: "fifo", rotulo: "FIFO", tipo: "FIFO" },
];
const DESTINOS = [
  { valor: "destino_1", rotulo: "Destino_1 (confirmação da compra)" },
  { valor: "destino_2", rotulo: "Destino_2 (preparo na cozinha)" },
  { valor: "destino_3", rotulo: "Destino_3 (coleta pelo motoboy)" },
];

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
 * Carrega os nomes reais das filas de destino de GET /api/arquitetura para
 * enriquecer os rótulos do seletor. Em falha, devolve um mapa vazio: o seletor
 * ainda funciona com os rótulos padrão. Não lança erro.
 *
 * @param {object} api Cliente da API_Backend.
 * @returns {Promise<Record<string, string[]>>} Mapa tipo ("Standard"/"FIFO") →
 *   lista ordenada de nomes de fila de destino.
 */
async function carregarFilasPorTipo(api) {
  const mapa = { Standard: [], FIFO: [] };
  try {
    const dados = await api.obterArquitetura();
    const filas = Array.isArray(dados && dados.filas_destino)
      ? dados.filas_destino
      : [];
    filas.forEach((fila) => {
      if (fila && (fila.tipo === "Standard" || fila.tipo === "FIFO")) {
        mapa[fila.tipo].push(fila.nome);
      }
    });
  } catch {
    // Sem dados reais: o seletor usa apenas os rótulos padrão.
  }
  return mapa;
}

/**
 * Preenche o seletor de Assinatura_SNS com as seis opções (cenário × destino),
 * usando os nomes reais das filas quando disponíveis. O value de cada opção é
 * "cenario|destino", desmembrado na submissão.
 *
 * @param {HTMLSelectElement} select Elemento select do seletor.
 * @param {Record<string, string[]>} filasPorTipo Mapa tipo → nomes de fila.
 */
function preencherSeletor(select, filasPorTipo) {
  select.innerHTML = "";
  CENARIOS.forEach((cenario) => {
    const grupo = document.createElement("optgroup");
    grupo.label = `Assinaturas ${cenario.rotulo}`;
    const filas = filasPorTipo[cenario.tipo] || [];
    DESTINOS.forEach((destino, indice) => {
      const option = document.createElement("option");
      option.value = `${cenario.valor}|${destino.valor}`;
      // Enriquecemos o rótulo com o nome real da fila, quando disponível.
      const nomeFila = filas[indice];
      option.textContent = nomeFila
        ? `${cenario.rotulo} · ${destino.rotulo} → ${nomeFila}`
        : `${cenario.rotulo} · ${destino.rotulo}`;
      grupo.appendChild(option);
    });
    select.appendChild(grupo);
  });
}

/**
 * Monta a lista das demais assinaturas do mesmo tópico, com o estado derivado por
 * leitura real (Entrega_Confirmada / Não confirmado) — Req. 8.4.
 *
 * @param {Array<object>} demais Lista de DemaisAssinaturaDlqSns.
 * @returns {HTMLElement}
 */
function montarDemaisAssinaturas(demais) {
  const bloco = el("div", "dlq-demais");
  bloco.appendChild(
    el("h5", "dlq-sub", "Demais assinaturas do mesmo tópico")
  );
  const itens = Array.isArray(demais) ? demais : [];
  if (itens.length === 0) {
    bloco.appendChild(
      el("p", "dlq-vazio", "Nenhuma outra assinatura verificada.")
    );
    return bloco;
  }
  const lista = el("ul", "dlq-demais-lista");
  itens.forEach((assinatura) => {
    const confirmada = Boolean(assinatura && assinatura.confirmada);
    const item = el("li", "dlq-demais-item");
    item.classList.add(confirmada ? "is-confirmada" : "is-nao-confirmada");

    const cabecalho = el("div", "dlq-demais-head");
    cabecalho.appendChild(
      el(
        "span",
        "dlq-demais-dest",
        (assinatura && assinatura.destino) || "—"
      )
    );
    const estadoTexto =
      (assinatura && assinatura.estado) ||
      (confirmada ? "Entrega_Confirmada" : "Não confirmado");
    cabecalho.appendChild(el("span", "dlq-estado", estadoTexto));
    item.appendChild(cabecalho);

    const detalhe = el("p", "dlq-demais-detalhe");
    detalhe.append(`Fila: ${(assinatura && assinatura.fila_destino) || "—"}`);
    if (assinatura && assinatura.message_id) {
      detalhe.append(` · MessageId: ${assinatura.message_id}`);
    }
    item.appendChild(detalhe);
    lista.appendChild(item);
  });
  bloco.appendChild(lista);
  return bloco;
}

/**
 * Desenha o resultado do teste de DLQ (ou a seleção inválida/interrupção).
 *
 * @param {object} resposta RespostaSimularFalhaDlqSns.
 * @param {HTMLElement} alvo Container de resultado.
 */
function desenharResultado(resposta, alvo) {
  alvo.innerHTML = "";

  // Seleção inválida ou interrupção (nenhuma policy alterada no caso de seleção
  // inválida; erro original repassado em interrupção) — Req. 8.1, 8.3.
  if (resposta && resposta.concluido === false && !resposta.message_id_teste) {
    const box = el("div", "dlq-falha");
    box.setAttribute("role", "alert");
    box.appendChild(
      el("strong", "dlq-falha-titulo", "Não foi possível executar o teste de DLQ")
    );
    box.appendChild(
      el(
        "p",
        "dlq-falha-msg",
        resposta.mensagem ||
          "Verifique a seleção da Assinatura_SNS (cenário e destino) e tente novamente."
      )
    );
    if (resposta.erro_original) {
      const detalhe = el("p", "dlq-falha-erro");
      detalhe.append("Erro original da AWS: ");
      detalhe.appendChild(el("code", null, resposta.erro_original));
      box.appendChild(detalhe);
    }
    // Mesmo em falha, reafirma a situação da policy quando informada (Req. 8.9).
    if (resposta.policy_restaurada === false && resposta.mensagem_restauracao) {
      box.appendChild(el("p", "dlq-restauracao-manual", resposta.mensagem_restauracao));
    }
    alvo.appendChild(box);
    alvo.hidden = false;
    return;
  }

  // Resumo da assinatura selecionada e da publicação de teste.
  const resumo = el("dl", "dlq-resumo");
  const linha = (rotulo, valor) => {
    resumo.appendChild(el("dt", "dlq-resumo-rotulo", rotulo));
    resumo.appendChild(
      el("dd", "dlq-resumo-valor", valor != null && valor !== "" ? String(valor) : "—")
    );
  };
  linha("Assinatura selecionada", resposta && resposta.assinatura_selecionada);
  linha("Tipo", resposta && resposta.tipo);
  linha("Tópico", resposta && resposta.topico);
  linha("Fila de destino afetada", resposta && resposta.fila_destino_afetada);
  linha("ID_Pedido", resposta && resposta.id_pedido);
  linha("MessageId (teste)", resposta && resposta.message_id_teste);
  alvo.appendChild(resumo);

  // Resultado na DLQ como Evento_Observado / "Não confirmado" (Req. 8.6, 8.7).
  const confirmadaDlq = resposta && resposta.estado_dlq === "Entrega_Confirmada";
  const painelDlq = el("div", "dlq-painel");
  painelDlq.classList.add(confirmadaDlq ? "is-confirmada" : "is-nao-confirmada");
  const cabecalhoDlq = el("div", "dlq-painel-head");
  cabecalhoDlq.appendChild(
    el("span", "dlq-painel-titulo", `DLQ do SNS: ${(resposta && resposta.dlq) || "—"}`)
  );
  cabecalhoDlq.appendChild(
    el("span", "dlq-estado", (resposta && resposta.estado_dlq) || "Não confirmado")
  );
  painelDlq.appendChild(cabecalhoDlq);
  const detalheDlq = el("p", "dlq-painel-detalhe");
  if (confirmadaDlq) {
    detalheDlq.append(
      "Evento_Observado: a mensagem de teste foi confirmada por leitura real na DLQ."
    );
    if (resposta.dlq_message_id) {
      detalheDlq.append(` MessageId na DLQ: `);
      detalheDlq.appendChild(el("code", null, resposta.dlq_message_id));
    }
  } else {
    detalheDlq.append(
      "A mensagem não foi confirmada na DLQ dentro do Timeout_Verificacao_DLQ " +
        "(estado \u201cNão confirmado\u201d)."
    );
  }
  painelDlq.appendChild(detalheDlq);
  alvo.appendChild(painelDlq);

  // Demais assinaturas do mesmo tópico (Req. 8.4).
  alvo.appendChild(montarDemaisAssinaturas(resposta && resposta.demais_assinaturas));

  // Confirmação de policy restaurada ou orientação de restauração manual (Req. 8.8, 8.9).
  const restaurada = Boolean(resposta && resposta.policy_restaurada);
  const boxPolicy = el("div", restaurada ? "dlq-policy is-ok" : "dlq-policy is-erro");
  boxPolicy.setAttribute("role", restaurada ? "status" : "alert");
  if (restaurada) {
    boxPolicy.append(
      "✅ Access_Policy_Fila restaurada: a alteração temporária foi revertida " +
        "integralmente ao final do teste."
    );
  } else {
    boxPolicy.appendChild(
      el("strong", "dlq-policy-titulo", "Atenção: a Access_Policy_Fila não foi restaurada")
    );
    boxPolicy.appendChild(
      el(
        "p",
        "dlq-policy-msg",
        (resposta && resposta.mensagem_restauracao) ||
          `Restaure manualmente pelo Console AWS a Access_Policy_Fila da fila ` +
            `${(resposta && resposta.fila_destino_afetada) || "afetada"}.`
      )
    );
  }
  alvo.appendChild(boxPolicy);

  // Texto explicativo pt-BR sobre a DLQ do SNS (Req. 8.11).
  const explicacao = el(
    "p",
    "dlq-explicacao",
    (resposta && resposta.texto_explicativo) || EXPLICACAO_PADRAO
  );
  explicacao.setAttribute("role", "note");
  alvo.appendChild(explicacao);

  alvo.hidden = false;
}

/**
 * Inicializa a área de teste de DLQ do SNS: monta o seletor e o formulário, liga a
 * submissão à API e inicia o polling do estado do botão.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function init(ctx) {
  // O container pode SER o próprio ponto de extensão ou contê-lo como descendente.
  const alvo = ctx.container.matches('[data-extension-point="dlq"]')
    ? ctx.container
    : ctx.container.querySelector('[data-extension-point="dlq"]');
  if (!alvo) {
    return;
  }

  // Remove o placeholder da Tarefa 15.1, preservando o título da área.
  const placeholder = alvo.querySelector(".area-placeholder");
  if (placeholder) {
    placeholder.remove();
  }

  // Texto explicativo pt-BR exibido já de início, antes mesmo de testar (Req. 8.11).
  const intro = el("p", "dlq-intro", EXPLICACAO_PADRAO);
  intro.setAttribute("role", "note");
  alvo.appendChild(intro);

  const form = el("form", "dlq-form");
  form.setAttribute("novalidate", "");
  form.setAttribute("aria-label", "Teste de DLQ do SNS");

  // --- Seletor de Assinatura_SNS (cenário + destino) — Req. 8.1 ---
  const grupoSelecao = el("div", "field");
  const labelSelecao = el("label", null, "Assinatura_SNS (cenário e destino)");
  labelSelecao.setAttribute("for", "dlq-assinatura");
  const select = document.createElement("select");
  select.id = "dlq-assinatura";
  select.name = "assinatura";
  select.className = "dlq-select";
  select.required = true;
  // Preenche de imediato com os rótulos padrão; enriquece com nomes reais depois.
  preencherSeletor(select, { Standard: [], FIFO: [] });
  grupoSelecao.append(labelSelecao, select);
  form.appendChild(grupoSelecao);

  // --- Campo ID_Pedido de teste — Req. 8.3 ---
  const grupoPedido = el("div", "field");
  const labelPedido = el(
    "label",
    null,
    `ID_Pedido de teste (${ID_PEDIDO_MIN}–${ID_PEDIDO_MAX} caracteres)`
  );
  labelPedido.setAttribute("for", "dlq-id-pedido");
  const inputPedido = el("input", "dlq-input");
  inputPedido.type = "text";
  inputPedido.id = "dlq-id-pedido";
  inputPedido.name = "id_pedido";
  inputPedido.maxLength = ID_PEDIDO_MAX;
  inputPedido.required = true;
  inputPedido.setAttribute("aria-describedby", "dlq-id-pedido-msg");
  const msgPedido = el("p", "dlq-campo-msg");
  msgPedido.id = "dlq-id-pedido-msg";
  msgPedido.setAttribute("role", "alert");
  msgPedido.setAttribute("aria-live", "assertive");
  msgPedido.hidden = true;
  grupoPedido.append(labelPedido, inputPedido, msgPedido);
  form.appendChild(grupoPedido);

  // Nota pt-BR: o teste é sempre manual e reversível (Req. 8.10).
  const nota = el(
    "p",
    "dlq-nota",
    "O teste é executado apenas por acionamento manual. A Access_Policy_Fila é " +
      "ajustada de forma temporária e restaurada ao final; nenhuma fila ou " +
      "assinatura é excluída."
  );
  form.appendChild(nota);

  // Botão de acionamento manual — Req. 8.1, 8.10.
  const botao = el("button", "btn btn-primary dlq-botao", "SIMULAR FALHA DE ENTREGA");
  botao.type = "submit";
  form.appendChild(botao);

  alvo.appendChild(form);

  const resultado = el("div", "dlq-resultado");
  resultado.setAttribute("aria-live", "polite");
  resultado.hidden = true;
  alvo.appendChild(resultado);

  // Enriquece o seletor com os nomes reais das filas (sem bloquear a montagem).
  carregarFilasPorTipo(ctx.api).then((filasPorTipo) => {
    const selecionado = select.value;
    preencherSeletor(select, filasPorTipo);
    if (selecionado) {
      select.value = selecionado;
    }
  });

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
      ? "Teste de DLQ em andamento…"
      : "SIMULAR FALHA DE ENTREGA";
  }

  /** Consulta GET /api/testes/estado e reflete o botão deste teste (Req. 9.3, 9.4). */
  async function sincronizarEstado() {
    try {
      const dados = await ctx.api.obterEstadoTestes();
      const mapa = (dados && dados.testes_ativos) || {};
      estado.ativoServidor = Boolean(mapa[CHAVE_TESTE]);
    } catch {
      estado.ativoServidor = false;
    }
    if (!estado.encerrado) {
      atualizarBotao();
    }
  }

  /** Valida o campo ID_Pedido localmente, preservando o valor informado. */
  function validarLocal() {
    const erro = validarIdPedido(inputPedido.value);
    if (erro) {
      msgPedido.textContent = erro;
      msgPedido.hidden = false;
      inputPedido.setAttribute("aria-invalid", "true");
      return false;
    }
    msgPedido.textContent = "";
    msgPedido.hidden = true;
    inputPedido.removeAttribute("aria-invalid");
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

    // Desmembra "cenario|destino" do valor selecionado.
    const [cenario, destino] = String(select.value || "").split("|");
    if (!cenario || !destino) {
      msgPedido.textContent = "Selecione uma Assinatura_SNS válida (cenário e destino).";
      msgPedido.hidden = false;
      return;
    }

    estado.enviando = true;
    atualizarBotao();
    resultado.hidden = true;

    try {
      const resposta = await ctx.api.simularFalhaDlq({
        cenario,
        destino,
        id_pedido: inputPedido.value,
      });
      desenharResultado(resposta, resultado);
    } catch (erro) {
      // Falha de rede/servidor: preserva os valores informados e indica a falha.
      const detalhe =
        erro instanceof ApiError && typeof erro.detail === "string"
          ? ` (${erro.detail})`
          : "";
      resultado.innerHTML = "";
      const box = el("div", "dlq-falha");
      box.setAttribute("role", "alert");
      box.appendChild(
        el("strong", "dlq-falha-titulo", "Não foi possível testar a DLQ")
      );
      box.appendChild(
        el(
          "p",
          "dlq-falha-msg",
          `Não foi possível concluir o teste de DLQ no momento. Os valores informados foram preservados.${detalhe}`
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
