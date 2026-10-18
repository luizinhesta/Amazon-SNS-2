# TESTES.md — Roteiro de testes do AWS SNS Delivery Lab

> Roteiro de testes manuais do laboratório didático **AWS SNS Delivery Lab**, voltado ao estudo da certificação **AWS Solutions Architect Associate (SAA)**. Cada teste é executado **uma única vez, de forma manual**, pelo próprio estudante, por meio do **Dashboard** em pt-BR (título "AWS SNS Delivery Lab"). Não há loops, testes de carga, agendamentos nem publicações automáticas: cada ação roda apenas por acionamento manual do usuário, e o botão correspondente permanece desabilitado enquanto o teste está ativo.
>
> O laboratório foca **exclusivamente no Amazon SNS**. As filas Amazon SQS participam **apenas como destino** do padrão fan-out e servem para confirmar a entrega real por **leitura não destrutiva** (sem `DeleteMessage`), correlacionando as mensagens pelo **ID_Pedido**. O laboratório **não envia SMS nem e-mails reais**: a notificação "Seu pedido foi aprovado e está sendo preparado" é apenas visual.
>
> Toda a aplicação roda em uma instância Amazon EC2 Linux na região `us-east-1`, autenticando-se na AWS exclusivamente pela IAM_Role_EC2 (credenciais temporárias, sem Access Keys fixas).

## Como usar este roteiro

Cada teste descreve os **8 campos obrigatórios**: **objetivo**, **pré-requisitos**, **configuração**, **passo a passo numerado**, **resultado esperado**, **evidências**, **resultado real** (deixado em branco, para o estudante preencher durante a execução) e **critério de aprovação**.

- Preencha o campo **Resultado real** com o que efetivamente ocorreu. Registre apenas resultados realmente obtidos durante a execução, sem valores estimados, inventados ou presumidos.
- Anexe as **evidências** indicadas (capturas de tela, `MessageId`, horários) para tornar o teste reproduzível.
- O estado de cada mensagem é sempre distinguido entre **Entrega_Publicada** (o SNS aceitou a publicação e retornou um `MessageId`) e **Entrega_Confirmada** (a mensagem foi lida na fila de destino e correlacionada pelo ID_Pedido). Quando a verificação não confirma dentro do tempo-limite, o estado exibido é **"Não confirmado"**, nunca "entregue".

### Recursos do laboratório (criados manualmente no Console AWS)

| Recurso | Nome / referência |
|---------|-------------------|
| Topico_Standard | Tópico SNS do tipo Standard (`us-east-1`) |
| Topico_FIFO | Tópico SNS do tipo FIFO (`us-east-1`), com Deduplicacao_Por_Conteudo **habilitada** |
| Fila_Destino_Standard (x3) | Destino_1, Destino_2 e Destino_3 (SQS Standard) |
| Fila_Destino_FIFO (x3) | Destino_1, Destino_2 e Destino_3 (SQS FIFO) |
| DLQ_SNS_Standard | `delivery-sns-dlq-standard` |
| DLQ_SNS_FIFO | `delivery-sns-dlq.fifo` |
| Assinatura_SNS (x6) | 3 do Topico_Standard + 3 do Topico_FIFO, com Redrive_Policy_SNS para a DLQ compatível |

- **Destino_1**: confirmação da aprovação da compra.
- **Destino_2**: solicitação para a cozinha preparar o alimento.
- **Destino_3**: solicitação para o motoboy buscar o pedido.

### Pré-requisitos comuns a todos os testes

Os itens abaixo valem para os seis testes; cada teste repete apenas o que lhe for específico.

1. Todos os recursos AWS do laboratório existem na região `us-east-1` e foram criados manualmente conforme o `IMPLANTACAO.md`.
2. A IAM_Role_EC2 está anexada à instância EC2 e concede os privilégios mínimos de publicar nos tópicos, consultar assinaturas e ler as filas de destino e as DLQs.
3. A API_Backend, o Verificador_Entrega e o Dashboard estão em execução na EC2, e a verificação de inicialização (`GET /api/saude`) concluiu com sucesso (todos os recursos presentes e acessíveis).
4. O estudante está autenticado no Dashboard (login com usuário/senha válidos).
5. Nenhum outro teste do roteiro está em execução ao mesmo tempo (cada teste roda isoladamente).

---

## Teste 1 — Fan-out Standard

### Objetivo
Demonstrar o padrão **fan-out** do Amazon SNS no cenário Standard: publicar **uma única** mensagem no Topico_Standard e confirmar, por leitura real, que ela foi entregue às **três** filas de destino Standard (Destino_1, Destino_2 e Destino_3).

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- As três Assinatura_SNS do Topico_Standard para as três Fila_Destino_Standard estão ativas.
- As Access_Policy_Fila das três filas de destino Standard autorizam o Topico_Standard a publicar.

### Configuração
- Timeout_Verificacao_Entrega: valor padrão de 30 segundos (ajustável entre 5 e 120 s, se desejar). Verifique o valor atual na seção "Estatísticas e configuração" da Visão geral.
- ID_Pedido do teste: definir um identificador único de 1 a 80 caracteres, por exemplo `pedido-standard-0001`.

### Passo a passo numerado
1. No Dashboard, abra a área **"DISPARAR SNS STANDARD"**.
2. Informe o **ID_Pedido** `pedido-standard-0001` (1 a 80 caracteres).
3. Acione o botão de disparo Standard **uma única vez** e observe que o botão fica desabilitado enquanto o teste está ativo.
4. Aguarde a resposta da publicação: o Dashboard exibe o tópico utilizado, o tipo **Standard**, o ID_Pedido, o **MessageId** retornado pelo SNS e os três destinos (Destino_1, Destino_2, Destino_3), além da notificação visual "Seu pedido foi aprovado e está sendo preparado".
5. Aguarde o Verificador_Entrega ler as três filas de destino (leitura não destrutiva, Long Polling) e correlacionar pelo ID_Pedido, dentro do Timeout_Verificacao_Entrega.
6. Confirme que o botão é reabilitado ao concluir o teste.

### Resultado esperado
- A publicação é aceita e o estado inicial da mensagem é **Entrega_Publicada**, com `MessageId` registrado como Evento_Observado.
- Nas três filas de destino Standard, a mensagem é lida e correlacionada pelo ID_Pedido, mudando o estado para **Entrega_Confirmada** em Destino_1, Destino_2 e Destino_3.
- As estatísticas do cenário Standard refletem 1 publicação no Topico_Standard e 3 Entrega_Confirmada (uma por fila de destino).
- Nenhuma mensagem é excluída das filas durante a verificação; nenhum SMS ou e-mail real é enviado.

### Evidências
- Captura de tela do resultado do disparo com tópico, tipo Standard, ID_Pedido e MessageId.
- Captura de tela das estatísticas do cenário Standard mostrando 1 publicada e 3 confirmadas.
- Registro do MessageId retornado pelo SNS e do horário da última atualização bem-sucedida (data, hora com segundos e fuso).

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se **1 mensagem** for publicada no Topico_Standard e a mesma mensagem tiver **Entrega_Confirmada nas três filas de destino Standard** (Destino_1, Destino_2 e Destino_3), correlacionada pelo ID_Pedido.

---

## Teste 2 — Fan-out FIFO

### Objetivo
Demonstrar o padrão **fan-out** do Amazon SNS no cenário FIFO: publicar **uma única** mensagem no Topico_FIFO e confirmar, por leitura real, que ela foi entregue às **três** filas de destino FIFO (Destino_1, Destino_2 e Destino_3).

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- As três Assinatura_SNS do Topico_FIFO para as três Fila_Destino_FIFO estão ativas.
- As Access_Policy_Fila das três filas de destino FIFO autorizam o Topico_FIFO a publicar.
- A Deduplicacao_Por_Conteudo do Topico_FIFO está habilitada (Config_Aplicada); por isso o Dashboard **não** solicita MessageDeduplicationId.

### Configuração
- Timeout_Verificacao_Entrega: valor padrão de 30 segundos (ajustável entre 5 e 120 s).
- ID_Pedido do teste: `pedido-fifo-0001` (1 a 80 caracteres).
- MessageGroupId do teste: `grupo-fifo-0001` (1 a 128 caracteres).

### Passo a passo numerado
1. No Dashboard, abra a área **"DISPARAR SNS FIFO"**.
2. Informe o **ID_Pedido** `pedido-fifo-0001` (1 a 80 caracteres).
3. Informe o **MessageGroupId** `grupo-fifo-0001` (1 a 128 caracteres). Observe que o campo MessageDeduplicationId não é solicitado, pois a Deduplicacao_Por_Conteudo está habilitada.
4. Acione o botão de disparo FIFO **uma única vez** e observe que o botão fica desabilitado enquanto o teste está ativo.
5. Aguarde a resposta da publicação: o Dashboard exibe o tópico utilizado, o tipo **FIFO**, o ID_Pedido, o **MessageGroupId**, o **MessageId** retornado pelo SNS e os três destinos.
6. Aguarde o Verificador_Entrega ler as três filas de destino FIFO (leitura não destrutiva, preservando a ordem por MessageGroupId) e correlacionar pelo ID_Pedido, dentro do Timeout_Verificacao_Entrega.
7. Confirme que o botão é reabilitado ao concluir o teste.

### Resultado esperado
- A publicação é aceita (sempre com MessageGroupId) e o estado inicial é **Entrega_Publicada**, com `MessageId` registrado como Evento_Observado.
- Nas três filas de destino FIFO, a mensagem é lida e correlacionada pelo ID_Pedido, mudando o estado para **Entrega_Confirmada** em Destino_1, Destino_2 e Destino_3.
- As estatísticas do cenário FIFO refletem 1 publicação no Topico_FIFO e 3 Entrega_Confirmada (uma por fila de destino), separadas das estatísticas do cenário Standard.
- Nenhuma mensagem é excluída durante a verificação; nenhum SMS ou e-mail real é enviado.

### Evidências
- Captura de tela do resultado do disparo com tópico, tipo FIFO, ID_Pedido, MessageGroupId e MessageId.
- Captura de tela das estatísticas do cenário FIFO mostrando 1 publicada e 3 confirmadas.
- Registro do MessageId e do MessageGroupId utilizados e do horário da última atualização bem-sucedida.

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se **1 mensagem** for publicada no Topico_FIFO e a mesma mensagem tiver **Entrega_Confirmada nas três filas de destino FIFO** (Destino_1, Destino_2 e Destino_3), correlacionada pelo ID_Pedido.

### Imagens

Disparo FIFO com os três destinos em Entrega_Confirmada:

![Disparo SNS FIFO — formulário e resultado](imagens/imagem%20(2).png)

![Disparo SNS FIFO — detalhe dos destinos confirmados](imagens/imagem%20(1).png)

---

## Teste 3 — Ordenação FIFO (≥ 3 mensagens no mesmo MessageGroupId)

### Objetivo
Demonstrar a **garantia de ordenação FIFO** dentro de um mesmo MessageGroupId: publicar ao menos **três** mensagens sequenciais no Topico_FIFO com o mesmo MessageGroupId e confirmar que a ordem de recebimento observada nas filas de destino é **idêntica** à ordem de publicação, sem a aplicação reconstruir ou reordenar as mensagens.

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- As três Assinatura_SNS do Topico_FIFO estão ativas e com Access_Policy_Fila autorizando o Topico_FIFO.
- Deduplicacao_Por_Conteudo do Topico_FIFO habilitada (Config_Aplicada).

### Configuração
- Timeout_Verificacao_Entrega: valor padrão de 30 segundos (ajustável entre 5 e 120 s).
- MessageGroupId único para todas as mensagens do teste: `grupo-ordem-0001`.
- Três mensagens sequenciais, nesta ordem de publicação: `Pedido criado`, `Compra aprovada`, `Pedido em preparação` (cada publicação com um ID_Pedido próprio de 1 a 80 caracteres, por exemplo `pedido-ordem-0001`, `pedido-ordem-0002`, `pedido-ordem-0003`).

### Passo a passo numerado
1. No Dashboard, abra a área **"DISPARAR SNS FIFO"**.
2. Publique a 1ª mensagem (`Pedido criado`) usando o ID_Pedido `pedido-ordem-0001` e o MessageGroupId `grupo-ordem-0001`; aguarde a confirmação do disparo.
3. Publique a 2ª mensagem (`Compra aprovada`) usando o ID_Pedido `pedido-ordem-0002` e o **mesmo** MessageGroupId `grupo-ordem-0001`.
4. Publique a 3ª mensagem (`Pedido em preparação`) usando o ID_Pedido `pedido-ordem-0003` e o **mesmo** MessageGroupId `grupo-ordem-0001`.
5. Aguarde o Verificador_Entrega ler as filas de destino FIFO, dentro do Timeout_Verificacao_Entrega, e apresentar a sequência de recebimento agrupada por MessageGroupId.
6. Compare, para o MessageGroupId `grupo-ordem-0001`, a ordem de recebimento exibida com a ordem de publicação.

### Resultado esperado
- As três mensagens são publicadas no mesmo MessageGroupId, cada uma com estado **Entrega_Publicada** e seu `MessageId`.
- A sequência de recebimento apresentada pelo Dashboard, para o grupo `grupo-ordem-0001`, é exatamente `Pedido criado` → `Compra aprovada` → `Pedido em preparação`, igual à ordem de publicação.
- As três mensagens atingem **Entrega_Confirmada**, e a aplicação apresenta a ordem observada sem reconstruir nem reordenar.

### Evidências
- Captura de tela da sequência de recebimento FIFO por MessageGroupId, lado a lado com a ordem de publicação.
- Registro dos três MessageId na ordem de publicação.
- Registro do horário da última atualização bem-sucedida.

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se **ao menos 3 mensagens**, dentro do mesmo MessageGroupId, forem confirmadas (**Entrega_Confirmada**) na mesma ordem em que foram publicadas.

---

## Teste 4 — Comparação Standard x FIFO (lado a lado)

### Objetivo
Comparar o comportamento do Amazon SNS Standard e FIFO quanto à garantia de ordenação, executando dois testes independentes e apresentando, **lado a lado**, a ordem de publicação e a ordem de recebimento de cada cenário.

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- As seis Assinatura_SNS (três do Topico_Standard e três do Topico_FIFO) estão ativas, com Access_Policy_Fila autorizando o tópico correspondente.
- Deduplicacao_Por_Conteudo do Topico_FIFO habilitada (Config_Aplicada).

### Configuração
- Timeout_Verificacao_Entrega: valor padrão de 30 segundos (ajustável entre 5 e 120 s).
- As três mensagens de ambos os cenários, na mesma sequência: `Pedido criado`, `Compra aprovada`, `Pedido em preparação`.
- O cenário FIFO utiliza um **único** MessageGroupId para as três mensagens.

### Passo a passo numerado
1. No Dashboard, abra a área **"COMPARAR STANDARD X FIFO"**.
2. Acione a comparação **uma única vez** e observe que o botão fica desabilitado enquanto o teste está ativo.
3. Aguarde a execução dos dois testes independentes: três publicações sequenciais no Topico_Standard e três no Topico_FIFO (FIFO com um único MessageGroupId).
4. Aguarde o Verificador_Entrega ler as filas de destino de cada cenário, dentro do Timeout_Verificacao_Entrega.
5. Observe o painel exibindo, lado a lado, para cada cenário: a ordem de publicação, a ordem de recebimento, o MessageId de cada mensagem e o tipo do tópico.
6. Leia o texto explicativo em pt-BR indicando que o Topico_Standard não garante ordenação, mesmo quando as mensagens chegam na sequência correta.
7. Confirme que o botão é reabilitado ao concluir o teste.

### Resultado esperado
- O cenário FIFO apresenta a ordem de recebimento **idêntica** à ordem de publicação (`Pedido criado` → `Compra aprovada` → `Pedido em preparação`).
- O cenário Standard apresenta a ordem de recebimento observada **sem garantia de coincidir** com a ordem de publicação; a aplicação não simula artificialmente mensagens fora de ordem.
- Os resultados dos dois cenários aparecem lado a lado, com MessageId e tipo de cada mensagem, e o texto explicativo em pt-BR é exibido.
- Mensagens não confirmadas dentro do Timeout_Verificacao_Entrega são exibidas como **"Não confirmado"**, nunca como entregues.

### Evidências
- Captura de tela do painel de comparação lado a lado (ordem de publicação, ordem de recebimento, MessageId e tipo nos dois cenários).
- Captura de tela do texto explicativo sobre a ordenação do Standard.
- Registro dos MessageId de cada cenário.

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se o Dashboard apresentar **lado a lado** a ordem de publicação e a ordem de recebimento dos dois cenários (Standard e FIFO).

### Imagens

Painel de comparação Standard x FIFO lado a lado (ordem de publicação e de recebimento):

![Comparação Standard x FIFO lado a lado](imagens/imagem%20(4).png)

---

## Teste 5 — DLQ do SNS com Falha_Entrega_Controlada e restauração da policy

### Objetivo
Demonstrar a **Dead-Letter Queue (DLQ) do SNS** configurada na assinatura: provocar uma falha de entrega controlada e reversível em uma Assinatura_SNS, observar o SNS encaminhar a mensagem não entregue para a DLQ compatível e confirmar a restauração integral da Access_Policy_Fila original ao final.

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- A Assinatura_SNS selecionada possui Redrive_Policy_SNS apontando para a DLQ compatível com o tipo (DLQ_SNS_Standard para assinaturas Standard; DLQ_SNS_FIFO para assinaturas FIFO).
- O SNS está autorizado a publicar na DLQ correspondente.

### Configuração
- Timeout_Verificacao_DLQ: valor padrão de 120 segundos (ajustável entre 30 e 300 s). Verifique o valor atual na seção "Estatísticas e configuração".
- Assinatura_SNS alvo: selecionar uma assinatura específica (por exemplo, a assinatura de Destino_1 do Topico_Standard).

### Passo a passo numerado
1. No Dashboard, abra a área **"TESTAR DLQ DO SNS"**.
2. Selecione a **Assinatura_SNS** alvo do teste.
3. Leia o texto explicativo em pt-BR indicando que a DLQ do SNS é configurada na assinatura e recebe as mensagens que o SNS não conseguiu entregar.
4. Acione o botão **"SIMULAR FALHA DE ENTREGA"** (acionamento manual) **uma única vez**; o botão fica desabilitado enquanto o teste está ativo.
5. O Sistema salva a Access_Policy_Fila original e aplica um statement `Deny` temporário (principal `sns.amazonaws.com`, condição por `SourceArn` do tópico), **sem** excluir filas nem assinaturas.
6. O Sistema publica a mensagem de teste no tópico correspondente à assinatura selecionada.
7. O Verificador_Entrega verifica o resultado de entrega das **demais** assinaturas do mesmo tópico e aguarda a presença da mensagem na DLQ compatível, até o Timeout_Verificacao_DLQ (leitura não destrutiva).
8. Ao final, o Sistema restaura integralmente a Access_Policy_Fila original e o Dashboard confirma a policy restaurada.
9. Confirme que o botão é reabilitado ao concluir o teste.

### Resultado esperado
- A mensagem de teste não é entregue à fila de destino da assinatura alvo (devido ao Deny temporário) e é encaminhada pelo SNS à DLQ compatível.
- A mensagem é confirmada na DLQ por leitura real, exibida como **Evento_Observado** (Entrega_Confirmada na DLQ); se o Timeout_Verificacao_DLQ for atingido sem confirmação, o estado exibido é **"Não confirmado"**.
- As demais assinaturas do mesmo tópico seguem com Entrega_Confirmada normal nas suas filas de destino.
- A Access_Policy_Fila original é **restaurada integralmente** e o Dashboard confirma a restauração. Em caso de falha de restauração, o Dashboard identifica a fila afetada e orienta a restauração manual pelo Console AWS.

### Evidências
- Captura de tela do resultado do teste mostrando a mensagem confirmada na DLQ (Evento_Observado) ou o estado "Não confirmado".
- Captura de tela da confirmação de policy restaurada.
- Registro do MessageId da mensagem de teste, da assinatura selecionada e da fila de destino afetada.

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se, após a Falha_Entrega_Controlada de uma assinatura, uma mensagem for confirmada (**Entrega_Confirmada**) na **DLQ compatível** e a **Access_Policy_Fila original for restaurada**.

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

## Teste 6 — Confirmação de entrega real (Entrega_Publicada x Entrega_Confirmada)

### Objetivo
Demonstrar a distinção **explícita** entre **Entrega_Publicada** (o SNS aceitou a publicação e retornou um `MessageId`) e **Entrega_Confirmada** (a mensagem foi lida na fila de destino e correlacionada pelo ID_Pedido), evidenciando que a aplicação nunca afirma entrega apenas pela aceitação da publicação pelo SNS.

### Pré-requisitos
- Pré-requisitos comuns (seção acima) atendidos.
- Pelo menos uma Assinatura_SNS do tópico escolhido está ativa, com Access_Policy_Fila autorizando o tópico a publicar na fila de destino.

### Configuração
- Timeout_Verificacao_Entrega: valor padrão de 30 segundos (ajustável entre 5 e 120 s).
- Cenário escolhido: Standard (também pode ser repetido no FIFO).
- ID_Pedido do teste: `pedido-estado-0001` (1 a 80 caracteres).

### Passo a passo numerado
1. No Dashboard, abra a área **"DISPARAR SNS STANDARD"**.
2. Informe o **ID_Pedido** `pedido-estado-0001` e acione o disparo **uma única vez**.
3. Imediatamente após a resposta do SNS, observe o indicador textual da mensagem: o estado inicial deve ser **Entrega_Publicada**, acompanhado do `MessageId` retornado.
4. Aguarde o Verificador_Entrega ler a fila de destino e correlacionar pelo ID_Pedido, dentro do Timeout_Verificacao_Entrega.
5. Observe a mudança do indicador textual da mesma mensagem para **Entrega_Confirmada** quando a leitura real correlacionada ocorrer.
6. (Opcional) Para evidenciar o estado **"Não confirmado"**, repita o disparo com um Timeout_Verificacao_Entrega baixo (por exemplo 5 s) em uma condição em que a confirmação não ocorra a tempo e observe que o estado permanece "Não confirmado", nunca "entregue".

### Resultado esperado
- Logo após a publicação, a mensagem é apresentada com o indicador textual distinto **Entrega_Publicada** e o `MessageId`.
- Após a leitura real na fila de destino, a mesma mensagem passa a exibir o indicador textual distinto **Entrega_Confirmada**.
- A aplicação **não** apresenta a mensagem como entregue com base apenas na aceitação da publicação pelo SNS; se o timeout for atingido sem leitura correlacionada, exibe **"Não confirmado"**.

### Evidências
- Captura de tela mostrando a mensagem no estado Entrega_Publicada (com MessageId) logo após o disparo.
- Captura de tela mostrando a mesma mensagem no estado Entrega_Confirmada após a leitura real.
- (Opcional) Captura de tela do estado "Não confirmado" obtido com timeout baixo.

### Resultado real
_(a preencher durante a execução)_

### Critério de aprovação
O teste é aprovado se o Dashboard distinguir **explicitamente** os estados **Entrega_Publicada** e **Entrega_Confirmada** para uma mesma mensagem, por meio de indicadores textuais distintos.

### Imagens

Estatísticas por cenário no Dashboard, com os contadores de Entrega_Publicada (publicadas por tópico) e Entrega_Confirmada (por fila de destino):

![Estatísticas por cenário — Entrega_Publicada x Entrega_Confirmada](imagens/imagem%20(42).png)

---

## Checklist de completude do roteiro

Cada um dos seis testes contém os **8 campos obrigatórios**: objetivo, pré-requisitos, configuração, passo a passo numerado, resultado esperado, evidências, resultado real (em branco) e critério de aprovação.

| # | Teste | Critério de aprovação resumido |
|---|-------|--------------------------------|
| 1 | Fan-out Standard | 1 publicação no Topico_Standard + Entrega_Confirmada nas 3 filas de destino Standard |
| 2 | Fan-out FIFO | 1 publicação no Topico_FIFO + Entrega_Confirmada nas 3 filas de destino FIFO |
| 3 | Ordenação FIFO | ≥ 3 mensagens no mesmo MessageGroupId confirmadas na mesma ordem de publicação |
| 4 | Comparação Standard x FIFO | Apresentação lado a lado da ordem de publicação e de recebimento dos dois cenários |
| 5 | DLQ do SNS | Entrega_Confirmada na DLQ compatível após Falha_Entrega_Controlada + Access_Policy_Fila restaurada |
| 6 | Confirmação de entrega real | Distinção explícita entre Entrega_Publicada e Entrega_Confirmada para a mesma mensagem |
