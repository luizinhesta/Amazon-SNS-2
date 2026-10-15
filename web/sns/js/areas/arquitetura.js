/**
 * Representação visual da arquitetura do AWS SNS Delivery Lab (Tarefa 15.1 —
 * Req. 3.1, 3.2, 3.3).
 *
 * Desenha, dentro da área de visão geral, a topologia do laboratório:
 *  - dois tópicos SNS com o respectivo tipo (Standard e FIFO);
 *  - seis assinaturas (três por tópico, no padrão fan-out);
 *  - seis filas de destino (Destino_1..3 por cenário);
 *  - duas DLQs do SNS (uma Standard, uma FIFO).
 *
 * Os dados vêm de GET /api/arquitetura. Enquanto a tarefa 15.1 monta a ESTRUTURA,
 * esta função já consome o endpoint e, em caso de ausência/erro, cai para uma
 * estrutura-base derivada das constantes do laboratório, de modo que a página
 * sempre carregue sem erros de JS. As Tarefas 15.2+ podem enriquecer os cartões
 * com contadores no ponto de extensão de estatísticas.
 */

import { ApiError } from "../api.js";

/**
 * Estrutura-base da arquitetura, usada como fallback quando o endpoint ainda não
 * respondeu ou falhou. Reflete a topologia descrita no design (dois tópicos, três
 * destinos por cenário e uma DLQ por cenário). Mantida mínima e meramente visual.
 */
const ARQUITETURA_PADRAO = {
  topicos: [
    {
      nome: "Topico_Standard",
      tipo: "Standard",
      assinaturas: [
        { destino: "Destino_1", fila: "Destino_1 Standard" },
        { destino: "Destino_2", fila: "Destino_2 Standard" },
        { destino: "Destino_3", fila: "Destino_3 Standard" },
      ],
      dlq: "delivery-sns-dlq-standard",
    },
    {
      nome: "Topico_FIFO",
      tipo: "FIFO",
      assinaturas: [
        { destino: "Destino_1", fila: "Destino_1 FIFO" },
        { destino: "Destino_2", fila: "Destino_2 FIFO" },
        { destino: "Destino_3", fila: "Destino_3 FIFO" },
      ],
      dlq: "delivery-sns-dlq.fifo",
    },
  ],
};

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
 * Monta o cartão visual de um tópico com suas assinaturas, filas de destino e DLQ.
 *
 * @param {object} topico Dados de um tópico (nome, tipo, assinaturas[], dlq).
 * @returns {HTMLElement}
 */
function montarCartaoTopico(topico) {
  const card = el("article", "arch-topic");
  card.setAttribute(
    "aria-label",
    `Tópico ${topico.nome || "SNS"} do tipo ${topico.tipo || "desconhecido"}`
  );

  const header = el("header", "arch-topic-header");
  header.appendChild(el("h4", "arch-topic-name", topico.nome || "Tópico SNS"));
  header.appendChild(el("span", "arch-badge", topico.tipo || "—"));
  card.appendChild(header);

  card.appendChild(
    el("p", "arch-fanout-label", "Fan-out para 3 assinaturas → filas de destino")
  );

  const assinaturas = Array.isArray(topico.assinaturas) ? topico.assinaturas : [];
  const lista = el("ul", "arch-subs");
  lista.setAttribute("aria-label", "Assinaturas e filas de destino");
  assinaturas.forEach((assinatura) => {
    const item = el("li", "arch-sub");
    item.appendChild(
      el("span", "arch-sub-dest", assinatura.destino || "Destino")
    );
    item.appendChild(el("span", "arch-sub-arrow", "→"));
    item.appendChild(
      el("span", "arch-sub-queue", assinatura.fila || "Fila de destino")
    );
    lista.appendChild(item);
  });
  card.appendChild(lista);

  const dlq = el("div", "arch-dlq");
  dlq.appendChild(el("span", "arch-dlq-label", "DLQ do SNS"));
  dlq.appendChild(el("span", "arch-dlq-name", topico.dlq || "—"));
  card.appendChild(dlq);

  return card;
}

/**
 * Desenha a arquitetura dentro do ponto de extensão desta área.
 *
 * @param {object} arquitetura Dados retornados por GET /api/arquitetura (ou fallback).
 * @param {HTMLElement} container Elemento `[data-extension-point="arquitetura"]`.
 */
function desenhar(arquitetura, container) {
  container.innerHTML = "";

  const topicos = Array.isArray(arquitetura && arquitetura.topicos)
    ? arquitetura.topicos
    : ARQUITETURA_PADRAO.topicos;

  const grade = el("div", "arch-grid");
  topicos.forEach((topico) => grade.appendChild(montarCartaoTopico(topico)));
  container.appendChild(grade);
}

/**
 * Carrega os dados de arquitetura e desenha a representação visual. Em falha,
 * desenha a estrutura-base e exibe um aviso discreto, sem lançar erro.
 *
 * @param {{ api: object, container: HTMLElement }} ctx Contexto compartilhado.
 */
export async function renderizarArquitetura(ctx) {
  const alvo = ctx.container.querySelector('[data-extension-point="arquitetura"]');
  if (!alvo) {
    return;
  }
  const aviso = ctx.container.querySelector("#arquitetura-aviso");

  // Estado inicial com a estrutura-base, garantindo render imediato e sem erro.
  desenhar(ARQUITETURA_PADRAO, alvo);

  try {
    const dados = await ctx.api.obterArquitetura();
    desenhar(dados, alvo);
    if (aviso) {
      aviso.hidden = true;
    }
  } catch (erro) {
    // Mantém a estrutura-base já desenhada e sinaliza que os dados reais não
    // puderam ser carregados; a página permanece funcional.
    if (aviso) {
      const detalhe =
        erro instanceof ApiError && erro.detail
          ? ` (${typeof erro.detail === "string" ? erro.detail : "detalhe indisponível"})`
          : "";
      aviso.textContent =
        "Exibindo a estrutura-base da arquitetura: não foi possível carregar " +
        `os dados atualizados.${detalhe}`;
      aviso.hidden = false;
    }
  }
}
