/**
 * Área "DISPARAR SNS FIFO" do Dashboard AWS SNS Delivery Lab (Tarefa 15.3).
 *
 * Preenche o ponto de extensão `[data-extension-point="fifo"]` com o formulário de
 * disparo FIFO (ID_Pedido 1-80 caracteres e MessageGroupId 1-128 caracteres) e
 * validação em pt-BR. O MessageDeduplicationId NÃO é solicitado: a
 * Deduplicacao_Por_Conteudo do Topico_FIFO está habilitada, então o SNS o deriva
 * do conteúdo (Req. 5.4). Após a publicação, exibe tópico, tipo, ID_Pedido,
 * MessageGroupId, MessageId e os três destinos com o estado derivado
 * Entrega_Confirmada/Não confirmado, além da notificação APENAS visual
 * "Seu pedido foi aprovado e está sendo preparado" (Req. 5.1, 5.2, 5.3, 5.7). A
 * área também traz o texto em pt-BR de que a ordenação FIFO é garantida dentro de
 * um mesmo MessageGroupId (Req. 11.4). O botão é desabilitado enquanto o teste
 * estiver ativo e reabilitado ao concluir, refletindo GET /api/testes/estado
 * (Req. 9.3, 9.4).
 *
 * A estrutura e a lógica de interação são compartilhadas com a área Standard pelo
 * módulo `disparo.js`; aqui apenas configuramos o cenário FIFO.
 */

import { montarFormularioDisparo } from "./disparo.js";

let contexto = null;
let encerrarFormulario = null;

/**
 * Inicializa a área de disparo FIFO.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function init(ctx) {
  contexto = ctx;
  // Monta o formulário FIFO e guarda a função de limpeza do polling de estado.
  encerrarFormulario = montarFormularioDisparo({
    ctx,
    pontoExtensao: "fifo",
    ehFifo: true,
    chaveTeste: "disparar_fifo",
    disparar: (requisicao) => ctx.api.dispararFifo(requisicao),
  });
}

/**
 * Encerra os recursos vivos da área (polling do estado do botão). Chamado quando o
 * painel é desmontado (logout), em paralelo às demais áreas.
 */
export function encerrar() {
  if (typeof encerrarFormulario === "function") {
    encerrarFormulario();
    encerrarFormulario = null;
  }
}
