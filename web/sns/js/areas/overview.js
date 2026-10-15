/**
 * Área "Visão geral" do Dashboard AWS SNS Delivery Lab.
 *
 * Esqueleto montado na Tarefa 15.1 e preenchido na Tarefa 15.2. O conteúdo
 * detalhado — estatísticas separadas por cenário (publicadas por tópico,
 * Entrega_Confirmada por fila, presentes por DLQ), horário da última atualização e
 * parâmetros de Config_Aplicada/Config_Simulacao — é desenhado pelo módulo
 * `estatisticas.js` dentro do ponto de extensão
 * `[data-extension-point="overview-stats"]` desta área (Req. 3.4-3.10, 2.*).
 *
 * A representação visual da arquitetura (dois tópicos, seis assinaturas, seis
 * filas de destino e duas DLQs) é montada por `arquitetura.js`, consumindo
 * GET /api/arquitetura (Req. 3.1, 3.2, 3.3).
 */

import { renderizarArquitetura } from "./arquitetura.js";
import { renderizarEstatisticasConfig } from "./estatisticas.js";

let contexto = null;

/**
 * Inicializa a área de visão geral.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export function init(ctx) {
  contexto = ctx;
  // Carrega e desenha a arquitetura visual uma única vez (Tarefa 15.1).
  renderizarArquitetura(contexto);
  // Desenha as estatísticas por cenário e a configuração (Tarefa 15.2).
  renderizarEstatisticasConfig(contexto);
}
