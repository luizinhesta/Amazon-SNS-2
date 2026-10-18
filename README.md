# AWS SNS Delivery Lab

> Artigo técnico de portfólio sobre o estudo prático de **Amazon SNS** para a certificação **AWS Solutions Architect Associate (SAA)**.

Este projeto é um laboratório web que demonstra, de forma visual e honesta, o ciclo de vida completo das mensagens publicadas pelo **Amazon SNS**: publicação em tópicos, distribuição **fan-out** para múltiplas assinaturas, ordenação de mensagens (Standard vs FIFO), confirmação de entrega real nas filas de destino, falha de entrega controlada e encaminhamento para a **Dead-Letter Queue (DLQ) do SNS**. O cenário educacional é um fluxo de **delivery de comida**: após a aprovação de uma compra, o SNS distribui a mensagem para três destinos — confirmação da aprovação, solicitação para a cozinha preparar o alimento e solicitação para o motoboy buscar o pedido. O Dashboard exibe a notificação visual em pt-BR "Seu pedido foi aprovado e está sendo preparado". Essa notificação é **apenas visual**: o laboratório **não envia SMS nem e-mails reais**.

O laboratório foca **exclusivamente no Amazon SNS**. O **Amazon SQS** participa **apenas como destino** das mensagens publicadas pelo SNS (padrão fan-out); nenhuma funcionalidade educacional específica de SQS é desenvolvida aqui. As filas SQS existem somente para receber as entregas do SNS e permitir a confirmação real dessas entregas por meio de leitura não destrutiva. A aplicação roda em uma instância **Amazon EC2** Linux na região `us-east-1` e autentica-se na AWS exclusivamente pela IAM Role da instância (sem Access Keys fixas).

---

## 1. Amazon SNS (o que é)

O **Amazon Simple Notification Service (SNS)** é um serviço gerenciado de mensagens no padrão publicação/assinatura (pub/sub). Um publicador envia uma única mensagem a um **tópico** e o SNS a distribui para todas as **assinaturas** daquele tópico, desacoplando quem produz a informação de quem a consome. Por ser totalmente gerenciado, o SNS cuida de disponibilidade, durabilidade e escala, cobrando por requisição e sem exigir gestão de servidores.

Neste laboratório, o SNS é o coração do fluxo: o backend publica mensagens via `boto3` (`Publish`) em dois tópicos (um Standard e um FIFO), e o SNS as replica em paralelo para as três filas SQS de destino de cada tópico. O ponto didático central é que o `MessageId` retornado pelo SNS confirma apenas que a **publicação** foi aceita — não que a mensagem **chegou** ao destino. Por isso a aplicação só considera uma mensagem entregue depois de lê-la de fato na fila de destino correspondente.

## 2. Standard vs FIFO

Os tópicos **Standard** priorizam vazão alta e entrega *at-least-once*. Em troca, não garantem ordenação e podem entregar a mesma mensagem mais de uma vez. É o modelo adequado quando a ordem não importa e o sistema tolera (ou neutraliza) duplicatas. O laboratório deixa isso explícito: no teste de comparação, o texto em pt-BR reforça que o tópico Standard **não garante ordenação**, mesmo quando as mensagens chegam na sequência correta — e a aplicação nunca simula artificialmente mensagens fora de ordem; ela apenas apresenta a ordem observada na leitura.

Os tópicos **FIFO** (First-In-First-Out) garantem ordenação dentro de cada `MessageGroupId` e deduplicação dentro de uma janela, ao custo de uma vazão menor. O laboratório materializa a diferença com dois tópicos reais e seis filas de destino (três por tópico), com estatísticas apresentadas em dois conjuntos distintos e rotulados — um para o cenário Standard e um para o FIFO — para que a comparação entre entrega ordenada e entrega de alta vazão fique evidente lado a lado.

## 3. Tópicos SNS

Um **tópico** é o ponto de publicação do SNS: o publicador não conhece os destinos, apenas envia a mensagem ao tópico, e o SNS cuida da distribuição. O laboratório usa dois tópicos criados manualmente no Console AWS, em `us-east-1`: o **Topico_Standard** (tipo Standard) e o **Topico_FIFO** (tipo FIFO, com Deduplicacao_Por_Conteudo habilitada por padrão). O Dashboard apresenta o tipo de cada tópico como **Config_Aplicada** — um parâmetro efetivamente configurado no recurso AWS, não uma simulação da aplicação.

A aplicação **nunca** cria, modifica ou exclui tópicos: na inicialização ela apenas verifica a existência e a acessibilidade de cada recurso esperado antes de liberar o Dashboard. Se um tópico estiver ausente ou inacessível, a inicialização é interrompida sem alterar nada na AWS, e o Dashboard mostra em pt-BR qual recurso falhou, por nome e tipo.

## 4. Assinaturas

Uma **assinatura** (subscription) associa um tópico a um destino. No laboratório, cada assinatura liga um tópico SNS a uma fila SQS de destino, totalizando seis assinaturas: três do Topico_Standard para as três filas Standard (Destino_1, Destino_2, Destino_3) e três do Topico_FIFO para as três filas FIFO. É na assinatura que se configura a **Redrive_Policy_SNS**, que aponta a assinatura para a DLQ compatível com o tipo do tópico — por isso a DLQ do SNS é um conceito de **assinatura**, não de fila de destino.

O Dashboard apresenta, para cada uma das seis assinaturas, a Redrive_Policy_SNS correspondente como Config_Aplicada. Toda a topologia (tópicos, assinaturas, filas e DLQs) é criada manualmente pelo usuário no Console AWS; a aplicação apenas lê as assinaturas via `boto3` para exibi-las e para executar o teste de DLQ.

## 5. Fan-out

O **fan-out** é o padrão em que uma única mensagem publicada em um tópico é entregue simultaneamente a várias assinaturas. É o que permite, com uma só publicação, acionar vários sistemas em paralelo. No cenário delivery, uma publicação dispara, de uma vez, a confirmação da compra, o preparo na cozinha e a coleta pelo motoboy — cada um atendido por uma fila de destino distinta.

O laboratório demonstra o fan-out de ponta a ponta: o backend publica uma vez no tópico e o **Verificador_Entrega** confirma a chegada da mensagem nas três filas de destino, correlacionando cada mensagem pelo **ID_Pedido**. O resultado exibido mostra o tópico utilizado, o tipo, o ID_Pedido, o MessageId retornado pelo SNS e os três destinos de distribuição, deixando visível que uma publicação se desdobrou em três entregas.

## 6. Ordenação de mensagens

A **ordenação** só é garantida nos tópicos FIFO, e apenas dentro de um mesmo `MessageGroupId`: mensagens do mesmo grupo são entregues na ordem de publicação; grupos diferentes podem ser processados em paralelo. Isso permite ordenar o que precisa ser ordenado (por exemplo, todos os eventos de um mesmo pedido) sem serializar o sistema inteiro. Uma publicação FIFO sem `MessageGroupId` é rejeitada pela aplicação antes mesmo de chamar o SNS, com mensagem em pt-BR indicando a obrigatoriedade do campo.

No laboratório, a ordenação é **apresentada**, não reconstruída: o Verificador_Entrega lê as filas de destino FIFO preservando a ordem do grupo e o Dashboard exibe a sequência observada por `MessageGroupId`, sem reordenar as mensagens pela aplicação. O teste de comparação publica três mensagens — "Pedido criado", "Compra aprovada" e "Pedido em preparação" — no Standard e no FIFO (este com um único MessageGroupId) e mostra, lado a lado, a ordem de publicação contra a ordem de recebimento de cada cenário.

## 7. DLQ do SNS (Dead-Letter Queue)

A **DLQ do SNS** é uma fila para onde o SNS encaminha as mensagens que **não conseguiu entregar** a uma assinatura após esgotar sua política de retry. É um conceito configurado na **assinatura**, por meio da Redrive_Policy_SNS — diferente da DLQ de processamento do SQS, que trata mensagens que o consumidor não conseguiu processar. O laboratório usa duas DLQs compartilhadas: `delivery-sns-dlq-standard` (Standard) e `delivery-sns-dlq.fifo` (FIFO).

Para demonstrar a DLQ sem excluir recursos, o laboratório usa uma **Falha_Entrega_Controlada**: ao acionar manualmente "SIMULAR FALHA DE ENTREGA" para uma assinatura, a aplicação salva a Access_Policy_Fila original da fila de destino, adiciona um statement `Deny` temporário que nega o recebimento vindo do SNS daquela assinatura, publica uma mensagem de teste e aguarda a presença dela na DLQ compatível até o Timeout_Verificacao_DLQ. Ao final, a policy original é **restaurada integralmente**. Se a restauração falhar, o Dashboard identifica a fila afetada e orienta a restauração manual pelo Console AWS. O cenário nunca exclui filas nem assinaturas e exige acionamento manual.

## 8. Arquitetura da solução

A solução roda inteiramente em uma instância **EC2** Linux em `us-east-1`. O backend em Python expõe a **API_Backend** (FastAPI) e hospeda o processo **Verificador_Entrega**, ambos acessando a AWS por `boto3` com credenciais temporárias resolvidas automaticamente pela **IAM Role** da EC2 (sem Access Keys em código, config ou variáveis de ambiente). O **Dashboard** (HTML/CSS/JS) consome a API e apresenta, em pt-BR, a representação visual da arquitetura e as quatro ações principais: "DISPARAR SNS STANDARD", "DISPARAR SNS FIFO", "COMPARAR STANDARD X FIFO" e "TESTAR DLQ DO SNS".

O backend está organizado em camadas: `SnsGateway` (publicação nos tópicos via `boto3`), `SqsLeituraGateway` e `Verificador_Entrega` (leitura **não destrutiva** das filas de destino e DLQs), `Gerenciador_Falha_Controlada` (round-trip da Access_Policy_Fila), `Verificacao_Inicializacao` (checagem dos recursos AWS esperados antes de liberar o Dashboard), além das camadas de segurança e observabilidade. O estado de cada mensagem é **derivado** das observações da aplicação — `Entrega_Publicada`, `Entrega_Confirmada` ou "Não confirmado" — nunca armazenado como um campo mutável que confunda publicação com entrega. Todos os recursos AWS (tópicos, assinaturas, filas, DLQs, Access Policies, IAM Role, EC2, Security Groups) são criados **manualmente** no Console AWS, sem IaC; a aplicação apenas os verifica e utiliza, exceto o ajuste temporário e reversível da Access_Policy_Fila no teste de DLQ.

## 9. Tecnologias utilizadas

O backend é escrito em **Python** e usa **FastAPI** para a API HTTP, **Uvicorn** como servidor ASGI e **boto3** como SDK oficial da AWS para SNS e SQS. O frontend é um Dashboard em **HTML, CSS e JavaScript** puro (em `web/sns/`), organizado por área funcional, sem framework pesado, mantendo a aplicação simples de servir diretamente da EC2.

Os serviços AWS envolvidos são **Amazon SNS** (tópicos Standard e FIFO, com assinaturas e Redrive_Policy_SNS), **Amazon SQS** (seis filas de destino e duas DLQs, apenas como destino do fan-out), **Amazon EC2** (hospedagem), **AWS IAM** (role de privilégio mínimo anexada à instância) e **AWS Systems Manager Session Manager** (administração sem abrir a porta 22). A suíte de testes usa **pytest**, **Hypothesis** (testes baseados em propriedade) e cliente HTTP para testar a API. As dependências estão em [`requirements.txt`](requirements.txt) e em [`pyproject.toml`](pyproject.toml).

## 10. Funcionamento da aplicação

Na inicialização, a aplicação executa a verificação de recursos: confirma que os dois tópicos, as seis assinaturas, as seis filas de destino, as duas DLQs, a IAM Role e a EC2 existem e estão acessíveis antes de liberar o Dashboard. Se algum recurso estiver ausente ou inacessível, a inicialização é interrompida sem alterar nada na AWS, e o Dashboard mostra em pt-BR qual recurso falhou, por nome e tipo. A partir daí, o usuário dispara publicações informando o ID_Pedido (1 a 80 caracteres) e, no FIFO, o MessageGroupId (1 a 128 caracteres). Toda entrada é validada antes de qualquer chamada à AWS; cada publicação aceita registra um Evento_Observado de Entrega_Publicada com o MessageId retornado pelo SNS.

O Verificador_Entrega confirma as entregas lendo as filas de destino de forma **não destrutiva** — usa `ReceiveMessage` com Long Polling, **nunca** chama `DeleteMessage` e correlaciona cada mensagem pelo ID_Pedido extraído do envelope SNS, preservando mensagens de outros testes ou usuários. Enquanto aguarda, repete tentativas apenas até o Timeout_Verificacao (sem registrar erro em retornos vazios); ao atingir o limite sem confirmar, o estado exibido é **"Não confirmado"**, nunca "entregue". O Dashboard atualiza as estatísticas periodicamente (intervalo configurável de 5 a 300 s, padrão 10 s), exibe o horário da última atualização bem-sucedida e, se uma atualização falhar, preserva os últimos dados válidos com indicação visível. Exposto à internet, o Dashboard exige login e bloqueia a origem por 300 segundos após 5 tentativas inválidas consecutivas.

## 11. Experimentos realizados

O laboratório oferece seis experimentos controlados, todos de acionamento manual e sem loops ou testes de carga:

1. **Fan-out Standard** — publica uma mensagem no Topico_Standard e confirma a chegada nas três filas de destino Standard.
2. **Fan-out FIFO** — publica no Topico_FIFO (com MessageGroupId) e confirma a chegada nas três filas de destino FIFO.
3. **Ordenação FIFO** — publica três ou mais mensagens no mesmo MessageGroupId e apresenta a sequência de recebimento observada por grupo.
4. **Comparação Standard x FIFO** — publica as três mesmas mensagens ("Pedido criado", "Compra aprovada", "Pedido em preparação") em cada tópico e exibe, lado a lado, a ordem de publicação contra a ordem de recebimento, com texto em pt-BR explicando que o Standard não garante ordenação.
5. **DLQ do SNS com Falha_Entrega_Controlada** — ajusta temporariamente a Access_Policy_Fila para negar o recebimento de uma assinatura, publica uma mensagem de teste, aguarda sua presença na DLQ compatível e restaura a policy original ao final.
6. **Confirmação de entrega real** — em todos os cenários, distingue explicitamente **Entrega_Publicada** (SNS aceitou e retornou MessageId) de **Entrega_Confirmada** (mensagem lida de fato na fila de destino).

Cada experimento é observável na prática: o Dashboard mostra o tópico, o tipo, o ID_Pedido, o MessageId e os destinos, e usa indicadores textuais distintos para o estado de cada mensagem. Os parâmetros de simulação (Timeout_Verificacao_Entrega entre 5 e 120 s, Timeout_Verificacao_DLQ entre 30 e 300 s, intervalo de atualização entre 5 e 300 s) são ajustáveis dentro de faixas validadas, sem tocar no código.

## 12. Resultados

Os resultados aqui descritos são os **efetivamente verificáveis no repositório**, sem presumir métricas de uma execução real na AWS. A principal evidência objetiva é a suíte de testes automatizados: no ambiente de desenvolvimento, a suíte completa executa com **537 testes passando** (via `python -m pytest`), combinando testes unitários de exemplos e de borda com testes baseados em propriedade (Hypothesis) que exercitam as propriedades de correção descritas no design.

O comportamento verificável inclui: `Entrega_Confirmada` derivada **somente** quando há leitura real correlacionada pelo ID_Pedido (nunca a partir da mera aceitação da publicação pelo SNS); verificação **não destrutiva** que jamais emite `DeleteMessage`, preservando o conteúdo da fila; correlação **seletiva** por ID_Pedido, confirmando apenas as mensagens do teste em execução; timeout que produz o estado "Não confirmado", nunca "entregue"; **round-trip** da Access_Policy_Fila que restaura a policy estruturalmente idêntica à original; validações de disparo (ID_Pedido de 1 a 80 caracteres, MessageGroupId obrigatório no FIFO) e de faixa que aceitam se e somente se os valores são válidos; e estatísticas sempre inteiras, não-negativas e corretamente particionadas entre Standard e FIFO. Não há, neste documento, qualquer número de execução na AWS real — os valores concretos de publicação, entrega e DLQ aparecem no Dashboard quando o laboratório é operado contra os recursos criados manualmente.

## 13. Boas práticas

Do ponto de vista de **segurança**, o projeto adota **IAM Role na EC2** com privilégio mínimo e **nenhuma Access Key fixa** — as credenciais temporárias são resolvidas pelo `boto3` via metadata service. A IAM Role concede apenas as ações necessárias para publicar nos tópicos, consultar assinaturas e ler as filas de destino e DLQs. A administração usa **Session Manager** com a **porta 22 fechada**; cada Access_Policy_Fila autoriza a publicação apenas pelo tópico SNS correspondente; e o Dashboard exige login com bloqueio por origem após tentativas inválidas. Esse conjunto reflete recomendações centrais do SAA para proteger credenciais e reduzir a superfície de ataque.

Do ponto de vista de **arquitetura e honestidade didática**, três decisões se destacam. Primeira: a **leitura não destrutiva** das filas de destino (sem `DeleteMessage`, com VisibilityTimeout curto), que preserva mensagens de outros testes ou usuários. Segunda: a **distinção explícita entre Entrega_Publicada e Entrega_Confirmada** — o laboratório nunca afirma entrega só porque o SNS aceitou a publicação. Terceira: a separação entre **Config_Aplicada** (parâmetros reais dos recursos AWS) e **Config_Simulacao** (parâmetros da aplicação), com rótulos textuais distintos no Dashboard, e a regra de que a aplicação não cria, modifica nem exclui recursos AWS — exceto o ajuste temporário e reversível da Access_Policy_Fila no teste de DLQ.

## 14. Custos estimados

O laboratório foi projetado para custo baixo e previsível, usando o nível gratuito sempre que possível. A maior parte do custo potencial vem da instância **EC2**: usar um tipo elegível ao Free Tier (por exemplo, `t3.micro`/`t2.micro`, conforme disponibilidade na conta) mantém o gasto próximo de zero dentro dos limites do nível gratuito; fora dele, o custo é o da hora da instância enquanto ela estiver ligada. **SNS** e **SQS** cobram por requisição e, no volume de um laboratório operado manualmente (disparos pontuais, sem loops nem carga), o uso tende a permanecer dentro das camadas gratuitas mensais desses serviços. Não há **NAT Gateway** nem **Elastic Load Balancer** na arquitetura, justamente para evitar custos fixos por hora.

A estimativa detalhada em USD, com a composição por serviço, está no documento de implantação do laboratório SNS. A recomendação prática de contenção de custos é simples: **desligar ou encerrar a EC2 quando não estiver estudando** e **remover os recursos ao final** (ver a seção 16), já que a cobrança da EC2 ocorre enquanto a instância existe/está ligada, independentemente do SNS e do SQS.

## 15. Como executar

Pré-requisitos: Python 3.10+ e as dependências instaladas (`pip install -r requirements.txt`). A aplicação se autentica na AWS pela IAM Role da EC2, então, para operar contra recursos reais, ela deve rodar em uma instância EC2 com a role anexada e os recursos AWS já criados manualmente no Console.

Para iniciar o backend do laboratório SNS, execute na raiz do projeto:

```bash
uvicorn app.main_sns:app --host 0.0.0.0 --port 8000
```

Esse comando sobe o servidor ASGI Uvicorn servindo a aplicação FastAPI definida em `app/main_sns.py`. O que esperar: na inicialização, a aplicação executa a verificação de recursos AWS (tópicos, assinaturas, filas, DLQs, IAM Role e EC2); se tudo estiver acessível, o Dashboard fica disponível no host e porta configurados; se algum recurso faltar, a inicialização é interrompida e o Dashboard informa, em pt-BR, qual recurso falhou. Para rodar a suíte de testes localmente (que não exige AWS), use `python -m pytest` na raiz do projeto — a suíte completa executa com 537 testes passando.

Em produção (na EC2), prefira rodar a aplicação como um serviço **systemd** (`deploy/sns-delivery-lab.service`) em vez do `uvicorn` avulso: isso garante processo único na porta, reinício automático em falha e start no boot, com os parâmetros sensíveis lidos de um `EnvironmentFile` fora do repositório. O passo a passo está na Etapa 12 do [`IMPLANTACAO.md`](IMPLANTACAO.md), que também traz uma tabela de solução de problemas comuns (conflito de porta, instância sem `InstanceId` na verificação, cache do navegador).

## 16. Como remover os recursos AWS

Como todos os recursos foram criados manualmente, a remoção também é manual, no Console AWS, respeitando a ordem de dependência para evitar erros. O roteiro é:

1. **Encerrar a aplicação** na EC2 (parar o processo Uvicorn) e **confirmar que a Access_Policy_Fila está restaurada** — se um teste de DLQ foi interrompido antes de restaurar, verifique e remova qualquer statement `Deny` temporário.
2. **Excluir as seis assinaturas** (subscriptions) dos dois tópicos.
3. **Excluir os dois tópicos SNS** (Topico_Standard e Topico_FIFO).
4. **Excluir as seis filas de destino** e as **duas DLQs** (`delivery-sns-dlq-standard` e `delivery-sns-dlq.fifo`).
5. **Encerrar a instância EC2** (terminate) e remover o **Security Group** associado, se não for mais necessário.
6. **Remover a IAM Role / Instance Profile** usados pela instância, caso tenham sido criados exclusivamente para este laboratório.

O passo a passo numerado completo, com os cliques no Console e a verificação pós-remoção, está no documento de implantação do laboratório SNS. A regra de ouro para custo é terminar sempre pela **EC2**, pois é o recurso com maior potencial de cobrança contínua.

## 17. Lições aprendidas

A lição mais marcante é que **publicar não é entregar**. O `MessageId` que o SNS retorna confirma apenas que a publicação foi aceita; a entrega só é um fato quando a mensagem é lida na fila de destino. Tratar as duas coisas como iguais produziria um dashboard enganoso — por isso o laboratório separa, de forma intransigente, Entrega_Publicada de Entrega_Confirmada.

A segunda lição é que **observar sem interferir** exige disciplina: para confirmar entregas em filas que podem conter mensagens de terceiros, a leitura precisa ser não destrutiva (sem `DeleteMessage`), correlacionada por um identificador de negócio (o ID_Pedido) e limitada por um timeout honesto que resulta em "Não confirmado" quando a mensagem não aparece. A terceira é que a **DLQ do SNS vive na assinatura**, não na fila de destino — e que demonstrá-la com segurança pede uma falha controlada e reversível (um `Deny` temporário na Access_Policy_Fila), com restauração garantida ao final. Por fim, modelar o estado como algo **derivado das observações**, e não como um campo mutável, foi o que permitiu manter a honestidade didática em todos os cenários.

## 18. Conclusão

Este laboratório cumpre seu objetivo de ensinar Amazon SNS na prática para o SAA, cobrindo tópicos, assinaturas, fan-out, Standard vs FIFO, ordenação por MessageGroupId e DLQ do SNS — tudo observável de forma honesta, que separa o que foi publicado do que foi efetivamente entregue. A combinação de SNS como protagonista, SQS apenas como destino verificável, leitura não destrutiva, IAM Role de privilégio mínimo e um Dashboard em pt-BR entrega uma ferramenta de estudo que torna tangíveis conceitos normalmente abstratos.

Como artefato de portfólio, o projeto evidencia domínio tanto dos conceitos de mensageria pub/sub quanto de boas práticas de arquitetura e segurança na AWS, sustentado por uma suíte de testes automatizados (537 testes passando) que valida a lógica central.
