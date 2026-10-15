/**
 * Cliente HTTP da API_Backend (FastAPI) do laboratório AWS SNS Delivery Lab.
 *
 * Centraliza o acesso aos endpoints reais do SNS Delivery Lab para que as áreas
 * do Dashboard (Tarefas 15.2 a 15.5) não repitam detalhes de fetch, cabeçalhos e
 * tratamento de erro. Todos os caminhos têm o prefixo `/api`, conforme o design
 * da API_Backend do SNS.
 *
 * Contratos alinhados com o design (seção "Components and Interfaces"):
 *  - POST /api/autenticacao      -> { usuario, senha, origem? }   (Req. 12.5, 12.6)
 *  - GET  /api/saude             -> verificação de inicialização  (Req. 1.9, 1.11)
 *  - GET  /api/config            -> Config_Aplicada/Config_Simulacao (Req. 2.*)
 *  - PUT  /api/config/simulacao  -> ajuste de timeouts             (Req. 2.5, 2.8)
 *  - GET  /api/arquitetura       -> dados da arquitetura visual    (Req. 3.1, 3.2)
 *  - GET  /api/estatisticas      -> estatísticas por cenário       (Req. 3.4-3.10)
 *  - POST /api/disparar/standard -> dispara SNS Standard           (Req. 4.*)
 *  - POST /api/disparar/fifo     -> dispara SNS FIFO               (Req. 5.*)
 *  - GET  /api/testes/estado     -> estado "teste ativo" por botão (Req. 9.3, 9.4)
 *  - POST /api/comparar          -> comparação Standard x FIFO     (Req. 7.*)
 *  - POST /api/dlq/simular-falha -> teste de DLQ do SNS            (Req. 8.*)
 *
 * As áreas detalhadas (15.2-15.5) consomem somente os métodos deste objeto.
 */

const BASE_URL = "/api";

/**
 * Erro de chamada à API, preservando o status HTTP e o detalhe retornado pela
 * API_Backend (campo `detail` do FastAPI ou corpo bruto).
 */
export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Executa uma requisição JSON e normaliza o tratamento de erro.
 *
 * @param {string} path Caminho relativo ao BASE_URL (ex.: "/saude").
 * @param {RequestInit} [options] Opções do fetch (method, body já serializado...).
 * @returns {Promise<any>} Corpo JSON da resposta.
 */
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (networkError) {
    throw new ApiError(
      "Não foi possível conectar à API_Backend. Verifique sua conexão.",
      0,
      String(networkError)
    );
  }

  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const detail = body && typeof body === "object" ? body.detail : body;
    throw new ApiError(
      "A API_Backend retornou um erro ao processar a solicitação.",
      response.status,
      detail
    );
  }

  return body;
}

const get = (path) => request(path, { method: "GET" });
const post = (path, payload) =>
  request(path, { method: "POST", body: JSON.stringify(payload ?? {}) });
const put = (path, payload) =>
  request(path, { method: "PUT", body: JSON.stringify(payload ?? {}) });

/**
 * Cliente da API_Backend. Cada método reflete um endpoint real do SNS Delivery Lab.
 * As áreas (15.2-15.5) importam este objeto e chamam somente estes métodos.
 */
export const api = {
  /** POST /api/autenticacao — login com bloqueio por origem (Req. 12.5, 12.6). */
  autenticar(usuario, senha, origem) {
    return post("/autenticacao", { usuario, senha, origem });
  },

  /** GET /api/saude — verificação de inicialização dos recursos AWS (Req. 1.9, 1.11). */
  obterSaude() {
    return get("/saude");
  },

  /** GET /api/config — Config_Aplicada e Config_Simulacao (Req. 2.*). */
  obterConfig() {
    return get("/config");
  },

  /** PUT /api/config/simulacao — ajuste de Timeout_Verificacao_* (Req. 2.5, 2.8). */
  ajustarConfigSimulacao(ajuste) {
    return put("/config/simulacao", ajuste);
  },

  /** GET /api/arquitetura — dados da representação visual da arquitetura (Req. 3.1, 3.2). */
  obterArquitetura() {
    return get("/arquitetura");
  },

  /** GET /api/estatisticas — estatísticas agregadas por cenário (Req. 3.4-3.10). */
  obterEstatisticas() {
    return get("/estatisticas");
  },

  /** POST /api/disparar/standard — publica no Topico_Standard (Req. 4.*). */
  dispararStandard(requisicao) {
    return post("/disparar/standard", requisicao);
  },

  /** POST /api/disparar/fifo — publica no Topico_FIFO (Req. 5.*, 11.5). */
  dispararFifo(requisicao) {
    return post("/disparar/fifo", requisicao);
  },

  /** GET /api/testes/estado — estado "teste ativo" por botão (Req. 9.3, 9.4). */
  obterEstadoTestes() {
    return get("/testes/estado");
  },

  /** POST /api/comparar — executa Standard e FIFO lado a lado (Req. 7.*). */
  comparar(requisicao) {
    return post("/comparar", requisicao);
  },

  /** POST /api/dlq/simular-falha — Falha_Entrega_Controlada → DLQ do SNS (Req. 8.*). */
  simularFalhaDlq(requisicao) {
    return post("/dlq/simular-falha", requisicao);
  },
};
