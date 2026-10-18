# Amazon SNS — Pub/Sub, Fan-out e Entrega Assíncrona · Testes

> Guia prático para você rodar os seis experimentos do laboratório pelo Dashboard, um de cada vez. Cada ação é manual: você clica, acompanha o resultado na tela e segue para o próximo.

**Antes de começar**, confira que:

1. Os recursos AWS já foram criados (veja o `IMPLANTACAO.md`) e a aplicação está rodando na EC2.
2. Você está logado no Dashboard.
3. Nenhum outro teste está em andamento (rode um por vez; o botão fica desabilitado enquanto o teste roda).

**Dois estados que você vai ver o tempo todo:**

- **Entrega_Publicada** — o SNS aceitou a publicação e devolveu um `MessageId`.
- **Entrega_Confirmada** — a mensagem foi lida de verdade na fila de destino. Se não for lida a tempo, aparece **"Não confirmado"** (nunca "entregue").

Os três destinos do cenário representam: **Destino_1** confirmação da compra, **Destino_2** cozinha, **Destino_3** motoboy.

---

## Teste 1 — Fan-out Standard

**Objetivo:** ver uma única mensagem publicada no tópico Standard chegar nas três filas de destino.

1. Abra a aba **DISPARAR SNS STANDARD**.
2. Digite um **ID_Pedido** (ex.: `pedido-standard-0001`) e clique em disparar.
3. Acompanhe o resultado: tópico, tipo **Standard**, MessageId e os três destinos.

✅ **Deu certo se:** os três destinos (Destino_1, 2 e 3) ficarem como **Entrega_Confirmada**.

---

## Teste 2 — Fan-out FIFO

**Objetivo:** o mesmo fan-out, agora no tópico FIFO (que exige um MessageGroupId).

1. Abra a aba **DISPARAR SNS FIFO**.
2. Digite um **ID_Pedido** (ex.: `pedido-fifo-0001`) e um **MessageGroupId** (ex.: `grupo-fifo-0001`) e clique em disparar.
3. Repare que o campo MessageDeduplicationId **não** é pedido — a deduplicação por conteúdo já está ligada no tópico.

✅ **Deu certo se:** os três destinos FIFO ficarem como **Entrega_Confirmada**.

### Imagens

Disparo FIFO com os três destinos em Entrega_Confirmada:

![Disparo SNS FIFO — formulário e resultado](imagens/imagem%20(2).png)

![Disparo SNS FIFO — detalhe dos destinos confirmados](imagens/imagem%20(1).png)

---

## Teste 3 — Ordenação FIFO

**Objetivo:** mostrar que o FIFO entrega na ordem publicada, dentro do mesmo MessageGroupId.

1. Abra a aba **DISPARAR SNS FIFO**.
2. Publique três mensagens em sequência, **sempre com o mesmo MessageGroupId** (ex.: `grupo-ordem-0001`), cada uma com um ID_Pedido próprio:
   - 1ª — `Pedido criado`
   - 2ª — `Compra aprovada`
   - 3ª — `Pedido em preparação`
3. Veja a ordem de recebimento exibida pelo Dashboard.

✅ **Deu certo se:** a ordem de recebimento for exatamente a de publicação (criado → aprovado → preparação).

---

## Teste 4 — Comparação Standard x FIFO

**Objetivo:** comparar lado a lado, com um clique, como cada tipo trata a ordenação.

1. Abra a aba **COMPARAR STANDARD X FIFO**.
2. Informe um **ID_Pedido** e clique em comparar.
3. Veja os dois painéis: ordem de publicação e ordem de recebimento, para Standard e FIFO.

✅ **Deu certo se:** o FIFO mantiver a ordem e o painel trouxer o texto explicando que o Standard **não garante** ordenação (mesmo quando chega na ordem certa, é coincidência).

### Imagens

Painel de comparação Standard x FIFO lado a lado (ordem de publicação e de recebimento):

![Comparação Standard x FIFO lado a lado](imagens/imagem%20(4).png)

---

## Teste 5 — DLQ do SNS (falha controlada)

**Objetivo:** provocar uma falha de entrega reversível e ver a mensagem cair na DLQ.

1. Abra a aba **TESTAR DLQ DO SNS**.
2. Escolha uma **Assinatura_SNS** (cenário + destino) e informe um **ID_Pedido** de teste.
3. Clique em **SIMULAR FALHA DE ENTREGA**.
4. Acompanhe: a aplicação nega temporariamente o recebimento na fila alvo, publica a mensagem, observa ela chegar na DLQ e **restaura a política original** no final.

✅ **Deu certo se:** a mensagem aparecer como **Entrega_Confirmada na DLQ** e o Dashboard confirmar que a **política foi restaurada**.

> A DLQ do SNS fica na *assinatura* (Redrive Policy), não na fila de destino — por isso as demais assinaturas do mesmo tópico continuam recebendo normalmente.

### Imagens

Seleção da Assinatura_SNS (cenário e destino) para o teste de DLQ:

![Teste de DLQ — seleção da assinatura](imagens/imagem%20(8).png)

Resultado do teste de DLQ no cenário Standard (mensagem confirmada na DLQ como Evento_Observado e Access_Policy_Fila restaurada):

![Teste de DLQ — resultado Standard](imagens/imagem%20(9).png)

Resultado do teste de DLQ no cenário FIFO:

![Teste de DLQ — resultado FIFO](imagens/imagem%20(12).png)

Prova no Console AWS: a mensagem de teste presente na DLQ do SNS (envelope SNS correlacionado pelo ID_Pedido):

![Mensagem na DLQ do SNS no Console AWS](imagens/imagem%20(11).png)

---

## Teste 6 — Publicou x Entregou

**Objetivo:** ver, na prática, a diferença entre o SNS aceitar a publicação e a mensagem ser lida de verdade.

1. Abra a aba **DISPARAR SNS STANDARD**, informe um **ID_Pedido** e dispare.
2. Logo após o disparo, a mensagem aparece como **Entrega_Publicada** (com o MessageId).
3. Em seguida, quando o verificador lê a fila, o estado muda para **Entrega_Confirmada**.
4. (Opcional) Reduza o Timeout_Verificacao_Entrega na visão geral para ver o estado **"Não confirmado"** quando a leitura não dá tempo.

✅ **Deu certo se:** a mesma mensagem passar de **Entrega_Publicada** para **Entrega_Confirmada** — e nunca for marcada como entregue só porque o SNS respondeu.

### Imagens

Estatísticas por cenário no Dashboard, com os contadores de Entrega_Publicada (publicadas por tópico) e Entrega_Confirmada (por fila de destino):

![Estatísticas por cenário — Entrega_Publicada x Entrega_Confirmada](imagens/imagem%20(42).png)

---

## Resumo

| # | Teste | Passou se... |
|---|-------|--------------|
| 1 | Fan-out Standard | 1 publicação chega confirmada nas 3 filas Standard |
| 2 | Fan-out FIFO | 1 publicação chega confirmada nas 3 filas FIFO |
| 3 | Ordenação FIFO | 3 mensagens no mesmo grupo chegam na ordem publicada |
| 4 | Comparação Standard x FIFO | os dois cenários aparecem lado a lado |
| 5 | DLQ do SNS | mensagem confirmada na DLQ + política restaurada |
| 6 | Publicou x Entregou | a mensagem passa de Publicada para Confirmada |
