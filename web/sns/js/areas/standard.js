/**
 * Área "DISPARAR SNS STANDARD" do Dashboard AWS SNS Delivery Lab (Tarefa 15.3).
 *
 * Preenche o ponto de extensão `[data-extension-point="standard"]` com o
 * formulário de disparo Standard (ID_Pedido 1-80 caracteres) e validação em
 * pt-BR. Após a publicação, exibe tópico, tipo, ID_Pedido, MessageId e os três
 * destinos (Destino_1/2/3) com o estado derivado Entrega_Confirmada/Não
 * confirmado, além da notificação APENAS visual "Seu pedido foi aprovado e está
 * sendo preparado" (Req. 4.1, 4.4, 4.5, 4.7). O botão é desabilitado enquanto o
 * teste estiver ativo e reabilitado ao concluir, refletindo GET /api/testes/estado
 * (Req. 9.3, 9.4).
 *
 * A estrutura e a lógica de interação são compartilhadas com a área FIFO pelo
 * módulo `disparo.js`; aqui apenas configuramos o cenário Standard (sem FIFO).
 */

import { montarFormularioDisparo } from "./disparo.js";

let contexto = null;
let encerrarFormulario = null;

/**
 * Inicializa a área de disparo Standard.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function init(ctx) {
  contexto = ctx;
  // Monta o formulário Standard e guarda a função de limpeza do polling de estado.
  encerrarFormulario = montarFormularioDisparo({
    ctx,
    pontoExtensao: "standard",
    ehFifo: false,
    chaveTeste: "disparar_standard",
    disparar: (requisicao) => ctx.api.dispararStandard(requisicao),
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
