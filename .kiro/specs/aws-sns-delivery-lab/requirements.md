# Requirements Document

## Introduction

Esta funcionalidade descreve um laboratório prático e didático de **Amazon SNS** construído sobre serviços reais da AWS na região `us-east-1` (Norte da Virgínia). O objetivo é apoiar o estudo para a certificação **AWS Solutions Architect Associate (SAA)**, demonstrando de forma visual todo o ciclo de vida das mensagens publicadas pelo SNS: publicação em tópicos, distribuição fan-out para múltiplas assinaturas, ordenação de mensagens, confirmação de entrega real nas filas de destino, falhas de entrega e encaminhamento para a **Dead-Letter Queue (DLQ) do SNS**.

O laboratório foca **exclusivamente no Amazon SNS**. O **Amazon SQS** participa **apenas como destino** das mensagens publicadas pelo SNS (padrão fan-out), não sendo objeto de estudo próprio neste laboratório. Nenhuma funcionalidade educacional específica de SQS é desenvolvida aqui; as filas SQS existem somente para receber e permitir a confirmação real das entregas feitas pelo SNS.

O cenário educacional adotado é um fluxo de **delivery de comida**: após a aprovação de uma compra, o SNS distribui a mensagem para três destinos — confirmação da aprovação da compra, solicitação para a cozinha preparar o alimento e solicitação para o motoboy buscar o pedido. O Dashboard apresenta visualmente a mensagem "Seu pedido foi aprovado e está sendo preparado". Essa notificação é apenas visual: o laboratório **não envia SMS nem e-mails reais**.

A solução é composta por uma aplicação web em Português do Brasil (pt-BR) com título "AWS SNS Delivery Lab", hospedada em uma instância **Amazon EC2** Linux. O backend é escrito em Python com `boto3` e `FastAPI`, e o frontend usa HTML, CSS e JavaScript. A confirmação de entrega de cada mensagem é obtida pela leitura real das filas SQS de destino, correlacionando as mensagens pelo identificador do pedido.

Todos os recursos AWS (tópicos SNS, assinaturas, filas SQS de destino, DLQs, access policies das filas, IAM Role, instância EC2, Security Groups) são criados **manualmente pelo próprio usuário no Console AWS em pt-BR**. A aplicação **não cria recursos AWS automaticamente** e não utiliza Infrastructure as Code (Terraform, CloudFormation, SAM, CDK). A autenticação com a AWS ocorre exclusivamente por meio de uma **IAM Role** associada à instância EC2, sem Access Keys fixas no código.

Este documento define os requisitos usando os padrões EARS e as regras de qualidade INCOSE. O detalhamento de tópicos, assinaturas, access policies, exemplos JSON e padrões de verificação será elaborado no documento de design (`design.md`).

## Glossary

- **Dashboard**: Aplicação web em pt-BR, com título "AWS SNS Delivery Lab", servida pela EC2, que apresenta a arquitetura e as quatro ações principais do laboratório.
- **API_Backend**: Serviço FastAPI em Python que expõe os endpoints HTTP consumidos pelo Dashboard.
- **Verificador_Entrega**: Processo da aplicação que lê as filas SQS de destino via `boto3` para confirmar entregas reais, correlacionando mensagens pelo identificador do pedido.
- **Sistema**: Conjunto formado por API_Backend, Verificador_Entrega e Dashboard executando na EC2.
- **Topico_Standard**: Tópico SNS do tipo Standard usado no cenário Standard.
- **Topico_FIFO**: Tópico SNS do tipo FIFO usado no cenário FIFO.
- **Assinatura_SNS**: Assinatura (subscription) que associa um tópico SNS a uma fila SQS de destino.
- **Fila_Destino_Standard**: Fila SQS do tipo Standard que recebe mensagens de uma Assinatura_SNS do Topico_Standard. Existem três filas de destino Standard, correspondentes aos três destinos do cenário delivery.
- **Fila_Destino_FIFO**: Fila SQS do tipo FIFO que recebe mensagens de uma Assinatura_SNS do Topico_FIFO. Existem três filas de destino FIFO, correspondentes aos três destinos do cenário delivery.
- **DLQ_SNS_Standard**: Fila SQS do tipo Standard de nome `delivery-sns-dlq-standard`, usada como Dead-Letter Queue compartilhada das assinaturas do Topico_Standard.
- **DLQ_SNS_FIFO**: Fila SQS do tipo FIFO de nome `delivery-sns-dlq.fifo`, usada como Dead-Letter Queue compartilhada das assinaturas do Topico_FIFO.
- **Destino_1**: Destino do cenário delivery que representa a confirmação da aprovação da compra.
- **Destino_2**: Destino do cenário delivery que representa a solicitação para a cozinha preparar o alimento.
- **Destino_3**: Destino do cenário delivery que representa a solicitação para o motoboy buscar o pedido.
- **Fan_Out**: Padrão de distribuição em que uma única mensagem publicada em um tópico SNS é entregue a múltiplas assinaturas simultaneamente.
- **Redrive_Policy_SNS**: Política configurada em uma Assinatura_SNS que associa a assinatura a uma DLQ e define o encaminhamento de mensagens não entregues.
- **MessageId**: Identificador da mensagem retornado pelo SNS no momento da publicação.
- **MessageGroupId**: Identificador de grupo exigido por tópicos e filas FIFO que garante ordenação dentro do grupo.
- **MessageDeduplicationId**: Identificador de deduplicação de mensagens em tópicos e filas FIFO.
- **Deduplicacao_Por_Conteudo**: Recurso FIFO que gera o `MessageDeduplicationId` a partir do conteúdo da mensagem (content-based deduplication). No laboratório, a Deduplicacao_Por_Conteudo do Topico_FIFO está HABILITADA por padrão como Config_Aplicada.
- **ID_Pedido**: Identificador do pedido de comida, usado para correlacionar as mensagens publicadas com as mensagens recebidas nas filas de destino.
- **Access_Policy_Fila**: Política de acesso (resource policy) de uma fila SQS que autoriza o SNS a publicar mensagens na fila.
- **Falha_Entrega_Controlada**: Cenário manual, reversível e seguro em que a Access_Policy_Fila de uma fila de destino é ajustada temporariamente para negar o recebimento vindo do SNS de uma assinatura específica, provocando uma falha de entrega demonstrável.
- **Entrega_Confirmada**: Estado de uma mensagem cuja presença foi comprovada pela leitura real da fila de destino correspondente.
- **Entrega_Publicada**: Estado de uma mensagem que o SNS aceitou publicar, retornando um MessageId, sem comprovação de recebimento na fila de destino.
- **Evento_Observado**: Evento registrado pela aplicação a partir de uma ação concreta que ela executou ou constatou (ex.: publicação via `boto3` com MessageId, leitura confirmada de mensagem na fila de destino).
- **Evento_Inferido**: Evento deduzido pela aplicação a partir de condições indiretas, sem confirmação direta do serviço AWS.
- **IAM_Role_EC2**: IAM Role com privilégios mínimos associada à instância EC2 para acesso ao SNS e às filas SQS do laboratório.
- **Session_Manager**: Recurso do AWS Systems Manager usado para administrar a EC2 sem abrir porta SSH.
- **Config_Aplicada**: Parâmetro efetivamente configurado em um recurso AWS (ex.: tipo do tópico, Redrive_Policy_SNS da assinatura).
- **Config_Simulacao**: Parâmetro usado apenas pela lógica de simulação da aplicação (ex.: timeout de verificação de entrega).
- **Timeout_Verificacao**: Termo guarda-chuva para o período máximo, em segundos, que o Sistema aguarda ao verificar a presença de uma mensagem em uma fila de destino ou DLQ antes de interromper a verificação. Subdivide-se em Timeout_Verificacao_Entrega e Timeout_Verificacao_DLQ.
- **Timeout_Verificacao_Entrega**: Período máximo, em segundos, para verificar a presença de uma mensagem em uma fila de destino. Valor inicial de 30 segundos, faixa de 5 a 120 segundos, do tipo Config_Simulacao.
- **Timeout_Verificacao_DLQ**: Período máximo, em segundos, para verificar a presença de uma mensagem em uma DLQ. Valor inicial de 120 segundos, faixa de 30 a 300 segundos, do tipo Config_Simulacao.

## Requirements

### Requisito 1: Infraestrutura manual de tópicos, assinaturas e filas

**User Story:** Como estudante de SAA, quero que o laboratório utilize tópicos SNS, assinaturas e filas SQS reais criados manualmente, para que eu pratique a configuração de recursos de mensageria pelo Console AWS.

#### Critérios de Aceitação

1. THE Sistema SHALL utilizar o Topico_Standard do tipo Standard na região `us-east-1`.
2. THE Sistema SHALL utilizar o Topico_FIFO do tipo FIFO na região `us-east-1`.
3. THE Sistema SHALL utilizar três Fila_Destino_Standard do tipo Standard, correspondentes a Destino_1, Destino_2 e Destino_3, na região `us-east-1`.
4. THE Sistema SHALL utilizar três Fila_Destino_FIFO do tipo FIFO, correspondentes a Destino_1, Destino_2 e Destino_3, na região `us-east-1`.
5. THE Sistema SHALL utilizar a DLQ_SNS_Standard de nome `delivery-sns-dlq-standard` do tipo Standard na região `us-east-1`.
6. THE Sistema SHALL utilizar a DLQ_SNS_FIFO de nome `delivery-sns-dlq.fifo` do tipo FIFO na região `us-east-1`.
7. THE Sistema SHALL utilizar seis Assinatura_SNS, sendo três do Topico_Standard para as três Fila_Destino_Standard e três do Topico_FIFO para as três Fila_Destino_FIFO.
8. THE Sistema SHALL operar exclusivamente sobre os dois tópicos SNS, as seis assinaturas, as seis filas de destino, as duas DLQs, a IAM Role e a instância EC2 criados manualmente pelo usuário no Console AWS, sem criar recursos próprios.
9. WHEN a inicialização do Sistema é iniciada, THE Sistema SHALL verificar a existência e a acessibilidade de cada recurso AWS esperado (tópicos, assinaturas, filas de destino, DLQs, IAM Role e instância EC2) antes de disponibilizar o Dashboard.
10. THE Sistema SHALL abster-se de criar, modificar ou excluir recursos AWS de forma automática, exceto o ajuste temporário e reversível de Access_Policy_Fila previsto no cenário de Falha_Entrega_Controlada.
11. IF um recurso AWS esperado estiver ausente ou inacessível durante a verificação de inicialização, THEN THE Sistema SHALL registrar o erro original retornado pela AWS, interromper a inicialização sem alterar qualquer recurso AWS e exibir no Dashboard uma mensagem em pt-BR que identifique o recurso indisponível por nome e tipo.
12. THE Sistema SHALL abster-se de utilizar Infrastructure as Code (Terraform, CloudFormation, SAM, CDK) para provisionar recursos.

### Requisito 2: Configuração inicial e distinção entre parâmetros aplicados e de simulação

**User Story:** Como estudante de SAA, quero distinguir os parâmetros aplicados aos recursos SNS e SQS dos parâmetros usados apenas na simulação, para que eu entenda o que é comportamento real da AWS e o que é lógica da aplicação.

#### Critérios de Aceitação

1. WHEN o Dashboard é carregado, THE Dashboard SHALL apresentar o tipo de cada tópico (Standard e FIFO) como Config_Aplicada.
2. WHEN o Dashboard é carregado, THE Dashboard SHALL apresentar, para cada uma das seis assinaturas, a Redrive_Policy_SNS que aponta para a DLQ compatível com o tipo da assinatura como Config_Aplicada.
3. WHEN o Dashboard é carregado, THE Dashboard SHALL apresentar a Deduplicacao_Por_Conteudo como Config_Aplicada do Topico_FIFO.
4. WHEN o Dashboard é carregado, THE Dashboard SHALL apresentar a Access_Policy_Fila que autoriza o SNS a publicar em cada fila de destino como Config_Aplicada.
5. WHEN o Dashboard é carregado, THE Dashboard SHALL apresentar o Timeout_Verificacao_Entrega inicial de 30 segundos como Config_Simulacao, ajustável entre 5 e 120 segundos, e o Timeout_Verificacao_DLQ inicial de 120 segundos como Config_Simulacao, ajustável entre 30 e 300 segundos.
6. THE Dashboard SHALL exibir, para cada parâmetro, um rótulo textual distinto que identifique se é Config_Aplicada ou Config_Simulacao.
7. WHERE um parâmetro é de Config_Simulacao, THE Dashboard SHALL permitir que o usuário ajuste o valor, dentro da faixa definida, para novos testes sem alterar o código-fonte.
8. IF o usuário informar, para um parâmetro de Config_Simulacao, um valor fora da faixa definida, THEN THE Dashboard SHALL rejeitar o valor, preservar o valor anterior e exibir mensagem em pt-BR indicando a faixa válida.
9. IF o usuário solicitar alterar um parâmetro que é Config_Aplicada em um recurso AWS, THEN THE Dashboard SHALL exibir orientação em pt-BR de que a alteração deve ser feita manualmente no Console AWS.

### Requisito 3: Dashboard — Visualização da arquitetura e visão geral

**User Story:** Como estudante de SAA, quero uma visão geral com a arquitetura e as estatísticas de distribuição, para que eu acompanhe o estado agregado do laboratório.

#### Critérios de Aceitação

1. THE Dashboard SHALL exibir uma representação visual da arquitetura AWS contendo os dois tópicos SNS, as seis assinaturas, as seis filas de destino e as duas DLQs.
2. THE Dashboard SHALL exibir, para cada tópico, o tipo correspondente (Standard ou FIFO) de forma textual distinta.
3. THE Dashboard SHALL exibir as quatro ações principais rotuladas em pt-BR: "DISPARAR SNS STANDARD", "DISPARAR SNS FIFO", "COMPARAR STANDARD X FIFO" e "TESTAR DLQ DO SNS".
4. THE Dashboard SHALL exibir o total de mensagens publicadas em cada tópico como um valor numérico inteiro maior ou igual a 0, identificando cada tópico individualmente.
5. THE Dashboard SHALL exibir a quantidade de mensagens com Entrega_Confirmada em cada fila de destino como um valor numérico inteiro maior ou igual a 0, identificando cada fila individualmente.
6. THE Dashboard SHALL exibir a quantidade de mensagens presentes em cada DLQ como um valor numérico inteiro maior ou igual a 0, identificando cada DLQ individualmente.
7. THE Dashboard SHALL exibir as estatísticas separadas em dois conjuntos distintos e rotulados: um para o cenário Standard e um para o cenário FIFO.
8. THE Dashboard SHALL exibir o horário da última atualização bem-sucedida das estatísticas contendo data, hora com horas, minutos e segundos, e identificação do fuso horário.
9. IF uma atualização de estatísticas falhar, THEN THE Dashboard SHALL preservar os últimos valores exibidos com sucesso, manter inalterado o horário da última atualização bem-sucedida e exibir uma indicação visível de que a atualização falhou.
10. IF não houver dados registrados para uma estatística, THEN THE Dashboard SHALL exibir o valor 0 para essa estatística.

### Requisito 4: Dashboard — Disparo de publicação no SNS Standard

**User Story:** Como estudante de SAA, quero publicar uma mensagem no tópico SNS Standard, para que eu observe a distribuição fan-out para os três destinos do cenário delivery.

#### Critérios de Aceitação

1. THE Dashboard SHALL permitir informar o ID_Pedido da publicação, com 1 a 80 caracteres.
2. WHEN o usuário aciona a ação "DISPARAR SNS STANDARD" com o ID_Pedido válido, THE API_Backend SHALL publicar uma mensagem no Topico_Standard via `boto3`.
3. WHEN a publicação no Topico_Standard é aceita, THE API_Backend SHALL registrar o MessageId retornado pelo SNS como Evento_Observado de Entrega_Publicada.
4. THE Dashboard SHALL exibir, após a publicação, o tópico utilizado, o tipo Standard, o ID_Pedido, o MessageId retornado pelo SNS e os três destinos de distribuição (Destino_1, Destino_2 e Destino_3).
5. THE Dashboard SHALL exibir a mensagem visual em pt-BR "Seu pedido foi aprovado e está sendo preparado" como notificação apenas visual.
6. THE Sistema SHALL abster-se de enviar SMS ou e-mail reais ao executar o cenário Standard.
7. IF o usuário acionar o disparo com o ID_Pedido ausente ou fora dos limites definidos, THEN THE Dashboard SHALL rejeitar o disparo, preservar os valores informados e exibir mensagem em pt-BR indicando o campo inválido.
8. IF a publicação no Topico_Standard falhar, THEN THE API_Backend SHALL registrar o erro original e o Dashboard SHALL exibir mensagem em pt-BR indicando a falha de publicação.

### Requisito 5: Dashboard — Disparo de publicação no SNS FIFO

**User Story:** Como estudante de SAA, quero publicar uma mensagem no tópico SNS FIFO, para que eu observe a distribuição fan-out ordenada para os três destinos do cenário delivery.

#### Critérios de Aceitação

1. THE Dashboard SHALL permitir informar o ID_Pedido da publicação, com 1 a 80 caracteres.
2. THE Dashboard SHALL permitir informar o MessageGroupId da publicação, com 1 a 128 caracteres.
3. WHERE a Deduplicacao_Por_Conteudo do Topico_FIFO está desabilitada, THE Dashboard SHALL permitir informar o MessageDeduplicationId com 1 a 128 caracteres.
4. WHERE a Deduplicacao_Por_Conteudo do Topico_FIFO está habilitada, THE Dashboard SHALL abster-se de solicitar e de aceitar o MessageDeduplicationId, apoiando-se na Config_Aplicada de Deduplicacao_Por_Conteudo.
5. WHEN o usuário aciona a ação "DISPARAR SNS FIFO" com os campos válidos, THE API_Backend SHALL publicar uma mensagem no Topico_FIFO via `boto3`, informando o MessageGroupId.
6. WHEN a publicação no Topico_FIFO é aceita, THE API_Backend SHALL registrar o MessageId retornado pelo SNS como Evento_Observado de Entrega_Publicada.
7. THE Dashboard SHALL exibir, após a publicação, o tópico utilizado, o tipo FIFO, o ID_Pedido, o MessageGroupId, o MessageId retornado pelo SNS e os três destinos de distribuição (Destino_1, Destino_2 e Destino_3).
8. THE Sistema SHALL abster-se de enviar SMS ou e-mail reais ao executar o cenário FIFO.
9. IF o usuário acionar o disparo com algum campo obrigatório ausente ou fora dos limites definidos, THEN THE Dashboard SHALL rejeitar o disparo, preservar os valores informados e exibir mensagem em pt-BR indicando o campo inválido.
10. IF a publicação no Topico_FIFO falhar, THEN THE API_Backend SHALL registrar o erro original e o Dashboard SHALL exibir mensagem em pt-BR indicando a falha de publicação.

### Requisito 6: Confirmação de entrega real nas filas de destino

**User Story:** Como estudante de SAA, quero que a confirmação de entrega venha da leitura real das filas, para que eu não confunda publicação aceita pelo SNS com entrega efetiva.

#### Critérios de Aceitação

1. THE Sistema SHALL considerar uma mensagem como Entrega_Confirmada somente após ler a mensagem correspondente na fila de destino, correlacionando-a pelo ID_Pedido.
2. THE Sistema SHALL abster-se de apresentar uma mensagem como entregue com base apenas na aceitação da publicação pelo SNS.
3. WHEN a aplicação lê uma mensagem na fila de destino correlacionada a um ID_Pedido, THE Sistema SHALL registrar um Evento_Observado de Entrega_Confirmada contendo a fila de destino, o ID_Pedido e o MessageId.
4. WHEN o Verificador_Entrega consulta uma fila de destino apenas para visualização, THE Verificador_Entrega SHALL preservar as mensagens de outros testes ou usuários, abstendo-se de excluí-las.
5. WHILE o Verificador_Entrega aguarda a presença de uma mensagem em uma fila de destino, THE Verificador_Entrega SHALL interromper a verificação ao atingir o Timeout_Verificacao_Entrega.
6. IF o Timeout_Verificacao_Entrega for atingido sem a confirmação da mensagem na fila de destino, THEN THE Dashboard SHALL exibir o estado "Não confirmado" para essa entrega, abstendo-se de indicá-la como concluída.
7. IF a leitura de uma fila de destino falhar, THEN THE Dashboard SHALL preservar os últimos dados válidos e exibir mensagem em pt-BR indicando a falha de verificação.

### Requisito 7: Dashboard — Comparação entre Standard e FIFO

**User Story:** Como estudante de SAA, quero comparar o comportamento do SNS Standard e do SNS FIFO, para que eu entenda a diferença de garantia de ordenação entre os dois tipos.

#### Critérios de Aceitação

1. WHEN o usuário aciona a ação "COMPARAR STANDARD X FIFO", THE Dashboard SHALL executar dois testes independentes, um no Topico_Standard e um no Topico_FIFO.
2. WHEN o teste Standard é executado, THE API_Backend SHALL publicar três mensagens sequenciais no Topico_Standard, com os conteúdos "Pedido criado", "Compra aprovada" e "Pedido em preparação", nessa ordem.
3. WHEN o teste FIFO é executado, THE API_Backend SHALL publicar as mesmas três mensagens no Topico_FIFO, na mesma sequência, usando um único MessageGroupId no teste FIFO.
4. THE Dashboard SHALL exibir, para cada teste, a ordem de publicação, a ordem de recebimento nas filas de destino, o MessageId de cada mensagem e o tipo do tópico.
5. THE Dashboard SHALL exibir os resultados dos dois testes lado a lado.
6. THE Dashboard SHALL exibir um texto explicativo em pt-BR indicando que o Topico_Standard não garante ordenação, mesmo quando as mensagens chegam na sequência correta.
7. THE Sistema SHALL abster-se de simular artificialmente mensagens fora de ordem.
8. IF um tópico estiver indisponível ou a autenticação falhar durante a comparação, THEN THE Dashboard SHALL interromper o teste e exibir mensagem em pt-BR indicando a causa.
9. IF alguma das três mensagens de qualquer cenário não for confirmada nas filas de destino dentro do Timeout_Verificacao_Entrega, THEN THE Dashboard SHALL exibir o estado "Não confirmado" para essa mensagem na comparação, abstendo-se de indicá-la como entregue.

### Requisito 8: Dashboard — Teste de DLQ do SNS com falha de entrega controlada

**User Story:** Como estudante de SAA, quero simular uma falha de entrega controlada, para que eu observe o SNS encaminhar uma mensagem não entregue para a DLQ da assinatura.

#### Critérios de Aceitação

1. WHEN o usuário aciona a ação "TESTAR DLQ DO SNS", THE Dashboard SHALL permitir selecionar uma Assinatura_SNS específica para o teste.
2. WHEN o usuário aciona o botão "SIMULAR FALHA DE ENTREGA" para a assinatura selecionada, THE Sistema SHALL ajustar temporariamente a Access_Policy_Fila da fila de destino para negar o recebimento vindo do SNS daquela assinatura, sem excluir filas nem assinaturas.
3. WHEN a Falha_Entrega_Controlada está preparada, THE API_Backend SHALL publicar uma mensagem de teste no tópico correspondente à assinatura selecionada.
4. WHEN a mensagem de teste é publicada, THE Sistema SHALL verificar o resultado de entrega das demais assinaturas do mesmo tópico.
5. WHILE o Sistema aguarda a presença da mensagem na DLQ correspondente, THE Sistema SHALL interromper a verificação ao atingir o Timeout_Verificacao_DLQ.
6. WHEN a mensagem de teste é confirmada na DLQ correspondente, THE Dashboard SHALL exibir a mensagem na DLQ como Evento_Observado.
7. IF o Timeout_Verificacao_DLQ for atingido sem a confirmação da mensagem na DLQ, THEN THE Dashboard SHALL exibir o estado "Não confirmado", abstendo-se de indicar sucesso.
8. WHEN o teste de DLQ é concluído, THE Sistema SHALL restaurar a Access_Policy_Fila original da fila de destino afetada.
9. IF a restauração da Access_Policy_Fila falhar, THEN THE Dashboard SHALL exibir mensagem em pt-BR identificando a fila afetada e orientando a restauração manual pelo Console AWS.
10. THE Sistema SHALL abster-se de executar a Falha_Entrega_Controlada de forma automática, exigindo acionamento manual do usuário.
11. THE Dashboard SHALL exibir um texto explicativo em pt-BR indicando que a DLQ do SNS é configurada na assinatura e recebe as mensagens que o SNS não conseguiu entregar.

### Requisito 9: Limites de execução dos testes

**User Story:** Como estudante de SAA, quero que os testes tenham limites de execução, para que eu evite loops, custos indevidos e resultados inconsistentes.

#### Critérios de Aceitação

1. THE Sistema SHALL executar cada teste somente mediante acionamento manual do usuário.
2. THE Sistema SHALL abster-se de executar loops de teste, testes de carga, agendamentos automáticos ou publicações repetitivas automáticas.
3. WHILE um teste estiver ativo, THE Dashboard SHALL manter desabilitado o botão correspondente a esse teste.
4. WHEN um teste é concluído ou interrompido, THE Dashboard SHALL reabilitar o botão correspondente a esse teste.
5. THE Sistema SHALL aplicar o Timeout_Verificacao a todas as verificações de presença de mensagem em filas de destino e DLQs.
6. WHEN uma verificação atinge o Timeout_Verificacao, THE Sistema SHALL interromper a verificação e abster-se de repeti-la automaticamente.
7. THE Sistema SHALL abster-se de repetir automaticamente uma publicação com o objetivo de obter um resultado diferente.

### Requisito 10: Consumo de mensagens pelos consumidores das filas de destino

**User Story:** Como estudante de SAA, quero que a aplicação leia as filas de destino de forma segura, para que a confirmação de entrega seja real sem interferir em outros testes.

#### Critérios de Aceitação

1. WHEN o Verificador_Entrega consulta uma Fila_Destino_Standard, THE Verificador_Entrega SHALL receber mensagens via `boto3` e correlacioná-las pelo ID_Pedido.
2. WHEN o Verificador_Entrega consulta uma Fila_Destino_FIFO, THE Verificador_Entrega SHALL receber mensagens via `boto3`, preservando a ordem por MessageGroupId, e correlacioná-las pelo ID_Pedido.
3. WHEN uma mensagem correlacionada ao teste em execução é lida, THE Verificador_Entrega SHALL registrar o Evento_Observado de recebimento com o horário real da aplicação.
4. THE Verificador_Entrega SHALL abster-se de excluir mensagens que não pertençam ao teste em execução.
5. WHILE o Verificador_Entrega aguarda mensagens, THE Verificador_Entrega SHALL usar Long Polling com WaitTimeSeconds de 1 a 20 segundos.
6. WHEN uma solicitação de recebimento retornar sem mensagens, THE Verificador_Entrega SHALL repetir a tentativa apenas até atingir o Timeout_Verificacao, sem registrar erro.
7. THE Sistema SHALL abster-se de configurar DLQ de processamento nas filas de destino, limitando o uso de DLQ ao encaminhamento configurado na Assinatura_SNS.

### Requisito 11: Ordenação de mensagens FIFO

**User Story:** Como estudante de SAA, quero observar a ordenação de mensagens FIFO, para que eu entenda a garantia de ordem dentro de um MessageGroupId.

#### Critérios de Aceitação

1. WHEN mensagens são publicadas no Topico_FIFO com o mesmo MessageGroupId, THE Sistema SHALL apresentar a ordem observada na leitura das filas de destino FIFO, refletindo a garantia de ordenação FIFO dentro do mesmo MessageGroupId, sem reconstruir ou reordenar as mensagens pela aplicação.
2. THE Dashboard SHALL exibir, para o cenário FIFO, a sequência de recebimento das mensagens por MessageGroupId.
3. THE Topico_FIFO SHALL utilizar a Deduplicacao_Por_Conteudo ou o MessageDeduplicationId informado para evitar entregas duplicadas.
4. THE Dashboard SHALL exibir um texto explicativo em pt-BR indicando que a ordenação FIFO é garantida dentro de um mesmo MessageGroupId.
5. IF uma mensagem FIFO for publicada sem MessageGroupId, THEN THE API_Backend SHALL rejeitar a publicação e o Dashboard SHALL exibir mensagem em pt-BR indicando a obrigatoriedade do MessageGroupId.

### Requisito 12: Segurança — autenticação e acesso

**User Story:** Como estudante de SAA, quero que a aplicação acesse a AWS com segurança, para que eu siga boas práticas de IAM e proteção de dados.

#### Critérios de Aceitação

1. THE Sistema SHALL autenticar-se nos serviços AWS exclusivamente por meio das credenciais temporárias fornecidas pela IAM_Role_EC2 associada à instância EC2.
2. THE Sistema SHALL operar sem qualquer Access Key fixa (atributos aws_access_key_id e aws_secret_access_key) presente no código-fonte, em arquivos de configuração ou em variáveis de ambiente.
3. THE IAM_Role_EC2 SHALL conceder somente as ações necessárias para publicar mensagens nos tópicos SNS, consultar as assinaturas e ler mensagens das filas SQS de destino e das DLQs, sem conceder privilégios administrativos ou de acesso a outros recursos AWS.
4. THE Sistema SHALL abster-se de expor credenciais da AWS no navegador do usuário.
5. WHERE o Dashboard estiver exposto à internet, THE Dashboard SHALL exigir usuário e senha válidos antes de conceder acesso a qualquer conteúdo.
6. WHERE o Dashboard estiver exposto à internet, IF forem registradas 5 tentativas de autenticação com credenciais inválidas de forma consecutiva, THEN THE Dashboard SHALL bloquear novas tentativas pela origem por 300 segundos e exibir indicação de bloqueio.
7. THE Sistema SHALL restringir o acesso de rede ao Dashboard apenas às origens explicitamente autorizadas, rejeitando conexões de origens não autorizadas.
8. THE Access_Policy_Fila de cada fila de destino SHALL autorizar a publicação apenas pelo tópico SNS correspondente, rejeitando publicações de outras origens.
9. IF a autenticação do Sistema via IAM_Role_EC2 falhar ao acessar os tópicos SNS ou as filas SQS, THEN THE Sistema SHALL interromper a operação afetada, registrar o evento de falha e expor indicação de erro de autorização sem persistir dados parciais.

### Requisito 13: Observabilidade e atualização periódica

**User Story:** Como estudante de SAA, quero que o Dashboard atualize os dados periodicamente, para que eu acompanhe a evolução das entregas sem recarregar a página manualmente.

#### Critérios de Aceitação

1. WHILE o Dashboard estiver aberto, THE Dashboard SHALL atualizar automaticamente as estatísticas de publicação e entrega ao final de cada intervalo configurado, sem recarregar a página.
2. THE Dashboard SHALL permitir configurar o intervalo de atualização periódica entre 5 e 300 segundos, com valor padrão de 10 segundos.
3. IF o usuário informar um intervalo de atualização fora da faixa de 5 a 300 segundos, THEN THE Dashboard SHALL rejeitar o valor, preservar o intervalo anterior e exibir mensagem em pt-BR indicando a faixa válida.
4. WHEN uma atualização periódica é concluída com sucesso, THE Dashboard SHALL exibir o horário dessa atualização com data e hora da aplicação.
5. IF uma atualização periódica falhar, THEN THE Dashboard SHALL preservar os últimos dados válidos exibidos e exibir uma mensagem em pt-BR indicando que os dados podem estar desatualizados.
6. THE Dashboard SHALL exibir, para cada mensagem apresentada, um indicador textual distinto que identifique se o estado é Entrega_Publicada ou Entrega_Confirmada.

### Requisito 14: Desempenho da aplicação

**User Story:** Como estudante de SAA, quero que o Dashboard responda em tempo adequado, para que a experiência de uso seja fluida durante os testes.

#### Critérios de Aceitação

1. WHEN o usuário solicita as estatísticas da visão geral sob carga de até 10 requisições simultâneas, THE API_Backend SHALL responder em até 3 segundos no percentil 95.
2. WHEN o usuário solicita o resultado de um teste sob carga de até 10 requisições simultâneas, THE API_Backend SHALL responder em até 3 segundos no percentil 95.
3. IF a solicitação de estatísticas da visão geral exceder 3 segundos, THEN THE API_Backend SHALL retornar uma indicação de timeout e o Dashboard SHALL preservar os últimos dados válidos.
4. WHILE o Verificador_Entrega aguarda mensagens em uma fila de destino, THE Verificador_Entrega SHALL usar Long Polling com WaitTimeSeconds de 20 segundos para reduzir chamadas vazias ao SQS.

### Requisito 15: Custos e encerramento do laboratório

**User Story:** Como estudante de SAA, quero controlar os custos do laboratório, para que eu evite cobranças desnecessárias após os testes.

#### Critérios de Aceitação

1. THE Sistema SHALL provisionar a arquitetura sem recurso NAT Gateway, exceto quando houver justificativa técnica registrada na documentação do projeto.
2. THE Sistema SHALL provisionar a arquitetura sem recurso Elastic Load Balancer, exceto quando houver justificativa técnica registrada na documentação do projeto.
3. THE Sistema SHALL habilitar o acesso administrativo à instância EC2 exclusivamente via AWS Systems Manager Session Manager, mantendo a porta 22 (SSH) sem regra de entrada liberada no Security Group.
4. WHEN a documentação do projeto for publicada, THE documentação do projeto SHALL registrar, para cada recurso AWS utilizado, o custo mensal estimado em dólares americanos (USD) e a premissa de uso (região, tipo de instância, horas de execução ou volume de requisições) adotada no cálculo.
5. WHEN a documentação do projeto for publicada, THE documentação do projeto SHALL registrar a lista nominal de todos os recursos AWS a excluir ao final do laboratório, com o nome ou identificador de cada recurso e a ordem de exclusão quando houver dependência entre eles.
6. WHEN o laboratório for encerrado, THE Sistema SHALL ter todos os recursos AWS da lista de exclusão removidos.
7. IF algum recurso AWS da lista de exclusão permanecer ativo após a execução do procedimento de encerramento, THEN THE Sistema SHALL sinalizar a ocorrência por meio de uma indicação de recursos remanescentes, informando o nome ou identificador de cada recurso não removido.

### Requisito 16: Implantação manual sem IaC

**User Story:** Como estudante de SAA, quero implantar os recursos manualmente pelo Console AWS, para que eu pratique a criação e configuração de cada serviço de mensageria.

#### Critérios de Aceitação

1. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para criar manualmente no Console AWS o Topico_Standard e o Topico_FIFO na região `us-east-1`, incluindo a habilitação da Deduplicacao_Por_Conteudo no Topico_FIFO.
2. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para criar manualmente as três Fila_Destino_Standard, as três Fila_Destino_FIFO, a DLQ_SNS_Standard (`delivery-sns-dlq-standard`) e a DLQ_SNS_FIFO (`delivery-sns-dlq.fifo`) na região `us-east-1`.
3. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para configurar manualmente a Access_Policy_Fila de cada fila de destino autorizando o tópico SNS correspondente a publicar na fila.
4. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para criar manualmente as seis Assinatura_SNS, associando cada tópico às filas de destino compatíveis com o tipo.
5. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para configurar manualmente a Redrive_Policy_SNS em cada uma das seis assinaturas, apontando para a DLQ compatível com o tipo (Standard para DLQ_SNS_Standard e FIFO para DLQ_SNS_FIFO), e a autorização para o SNS publicar nas DLQs.
6. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para criar manualmente a IAM_Role_EC2 no Console AWS com os privilégios mínimos de acesso aos tópicos SNS e às filas SQS de destino e DLQs, sem Access Keys fixas.
7. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para criar manualmente a instância EC2 Linux e os Security Groups no Console AWS, especificando as portas de entrada e saída liberadas, e para configurar o Session_Manager sem abrir porta SSH.
8. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para instalar e executar na EC2 a API_Backend, o Verificador_Entrega e o Dashboard, explicando cada comando Linux utilizado quanto ao que faz, por que é executado e qual resultado esperar.
9. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo para excluir ao final do laboratório os dois tópicos SNS, as seis assinaturas, as seis filas de destino, as duas DLQs, a IAM_Role_EC2, a instância EC2 e os Security Groups, apresentando-os pelos nomes definidos no Glossário.
10. THE documentação de implantação SHALL descrever, em pt-BR, o passo a passo de verificação pós-implantação que confirme que os tópicos, as assinaturas, as filas de destino, as DLQs, a IAM_Role_EC2 e a instância EC2 foram criados com os nomes e os valores de Config_Aplicada previstos.
11. THE documentação de implantação SHALL apresentar todos os recursos pelos nomes definidos no Glossário e pelos nomes reais exibidos no Console AWS, mantendo em inglês apenas termos técnicos, nomes de serviços AWS, nomes de parâmetros, nomes de variáveis e comandos.
12. IF um passo da implantação não puder ser concluído por recurso ausente, permissão insuficiente ou valor de configuração divergente, THEN THE documentação de implantação SHALL indicar, em pt-BR, como identificar a causa e como corrigir antes de prosseguir para o passo seguinte.

### Requisito 17: Artefatos de documentação do projeto

**User Story:** Como estudante de SAA, quero documentação completa do projeto, para que eu use o laboratório como material de estudo e portfólio.

#### Critérios de Aceitação

1. THE projeto SHALL conter o arquivo `ARQUITETURA.md` contendo todas as seguintes seções: visão geral, lista dos serviços AWS utilizados com a descrição da função de cada um, descrição dos fluxos fan-out Standard e FIFO, descrição do fluxo de falha de entrega e DLQ do SNS, descrição da integração com as filas SQS de destino e com o Dashboard, lista das permissões IAM, pelo menos um diagrama Mermaid que represente todos os fluxos citados e pelo menos um diagrama visual utilizando ícones oficiais AWS.
2. THE projeto SHALL conter o arquivo `IMPLANTACAO.md` contendo o passo a passo da implantação manual descrito no Requisito 16, com cada etapa numerada em ordem sequencial, o comando ou ação correspondente e o resultado esperado de cada etapa.
3. THE projeto SHALL conter o arquivo `README.md` no formato de artigo técnico de portfólio contendo todas as seguintes seções, cada uma com no mínimo um parágrafo: SNS, Standard vs FIFO, tópicos, assinaturas, fan-out, ordenação de mensagens, DLQ do SNS, arquitetura, tecnologias, funcionamento, experimentos, resultados, boas práticas, custos estimados, como executar, como remover os recursos AWS, lições aprendidas e conclusão.
4. THE projeto SHALL conter o arquivo `TESTES.md` contendo o roteiro dos testes definidos no Requisito 18, cada teste descrito com objetivo, pré-condições, passos de execução e resultado esperado.
5. IF a documentação do projeto apresentar qualquer resultado de experimento, THEN THE documentação SHALL incluir somente resultados efetivamente obtidos durante a execução dos testes, sem valores estimados, inventados ou presumidos.
6. THE documentação do projeto SHALL ser escrita em pt-BR, mantendo em inglês apenas termos técnicos, nomes de serviços AWS, nomes de parâmetros, nomes de variáveis e comandos.
7. IF qualquer um dos arquivos `ARQUITETURA.md`, `IMPLANTACAO.md`, `README.md` ou `TESTES.md` estiver ausente ou não contiver todas as seções obrigatórias definidas neste requisito, THEN THE documentação do projeto SHALL ser considerada incompleta.

### Requisito 18: Roteiro de testes

**User Story:** Como estudante de SAA, quero um roteiro de testes estruturado, para que eu valide cada comportamento do laboratório de forma reproduzível.

#### Critérios de Aceitação

1. THE arquivo `TESTES.md` SHALL conter um teste de fan-out Standard cujo critério de aprovação seja a publicação de 1 mensagem no Topico_Standard e a Entrega_Confirmada da mensagem nas três filas de destino Standard.
2. THE arquivo `TESTES.md` SHALL conter um teste de fan-out FIFO cujo critério de aprovação seja a publicação de 1 mensagem no Topico_FIFO e a Entrega_Confirmada da mensagem nas três filas de destino FIFO.
3. THE arquivo `TESTES.md` SHALL conter um teste de ordenação FIFO cujo critério de aprovação seja a Entrega_Confirmada de ao menos 3 mensagens, dentro do mesmo MessageGroupId, na mesma ordem em que foram publicadas.
4. THE arquivo `TESTES.md` SHALL conter um teste de comparação Standard x FIFO cujo critério de aprovação seja a apresentação lado a lado da ordem de publicação e da ordem de recebimento dos dois cenários.
5. THE arquivo `TESTES.md` SHALL conter um teste de DLQ do SNS cujo critério de aprovação seja a Entrega_Confirmada de uma mensagem na DLQ compatível após a Falha_Entrega_Controlada de uma assinatura e a restauração da Access_Policy_Fila original.
6. THE arquivo `TESTES.md` SHALL conter um teste de confirmação de entrega real cujo critério de aprovação seja a distinção explícita entre Entrega_Publicada e Entrega_Confirmada para uma mesma mensagem.
7. THE arquivo `TESTES.md` SHALL descrever, para cada teste, os seguintes campos obrigatórios: objetivo, pré-requisitos, configuração, passo a passo numerado, resultado esperado, evidências, campo para resultado real e critério de aprovação.
8. IF um teste descrito no arquivo `TESTES.md` não contiver todos os 8 campos obrigatórios definidos no critério 7, THEN THE roteiro de testes SHALL ser considerado reprovado na verificação de completude.
