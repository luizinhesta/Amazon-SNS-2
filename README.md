# AWS SNS Delivery Lab

> Um laboratório visual para entender, na prática, como o **Amazon SNS** entrega mensagens — e por que "publicar" não é o mesmo que "entregar".

Quando a gente estuda mensageria para a certificação **AWS Solutions Architect Associate**, o SNS costuma virar uma caixa-preta: você publica em um tópico, a AWS devolve um `MessageId` e... pronto? Entregou? Este laboratório nasceu para responder essa pergunta de forma honesta, mostrando cada etapa do caminho de uma mensagem com os próprios olhos.

O cenário é um **delivery de comida**: quando um pedido é aprovado, o SNS avisa três sistemas ao mesmo tempo — a confirmação da compra, a cozinha e o motoboy. Uma publicação, três entregas. É o padrão **fan-out**, e é aqui que o SNS brilha.

![Dashboard do AWS SNS Delivery Lab — visão geral](imagens/imagem%20(5).png)

## A pergunta central: publicou ou entregou?

O coração do laboratório é uma distinção que muita gente ignora:

- **Entrega_Publicada** — o SNS aceitou a mensagem e devolveu um `MessageId`. Isso significa só que a publicação foi aceita.
- **Entrega_Confirmada** — a mensagem foi **lida de verdade** na fila de destino, correlacionada pelo `ID_Pedido`.

A aplicação nunca diz "entregue" só porque o SNS respondeu. Ela vai até a fila SQS de destino, lê a mensagem e só então confirma. Se não encontrar dentro do tempo-limite, o estado é **"Não confirmado"** — nunca um "entregue" fingido. Essa honestidade é o ponto didático que separa este lab de um tutorial comum.

## O que dá para ver no laboratório

O Dashboard em português tem quatro ações, cada uma ensinando um conceito:

**Disparar SNS Standard e FIFO** — publica uma mensagem e mostra ela chegando nos três destinos. No FIFO, você informa um `MessageGroupId`; no Standard, nem precisa. Repare que o resultado traz o `MessageId` de cada destino, confirmado por leitura real.

![Disparo SNS FIFO com os três destinos confirmados](imagens/imagem%20(2).png)

**Comparar Standard x FIFO** — publica as mesmas três mensagens ("Pedido criado", "Compra aprovada", "Pedido em preparação") nos dois tipos de tópico, lado a lado. O FIFO preserva a ordem dentro do mesmo `MessageGroupId`; o Standard não garante nada — mesmo quando chega na ordem certa, é coincidência. A aplicação mostra a ordem observada, sem maquiar.

![Comparação Standard x FIFO lado a lado](imagens/imagem%20(4).png)

**Testar DLQ do SNS** — aqui está o truque mais elegante. Para demonstrar a Dead-Letter Queue sem quebrar nada, o lab provoca uma **falha controlada e reversível**: ajusta temporariamente a política da fila para negar o recebimento, publica uma mensagem, observa ela cair na DLQ e **restaura a política original ao final**. A DLQ do SNS vive na *assinatura* (Redrive Policy), não na fila — um detalhe que cai na prova.

![Teste de DLQ do SNS com a mensagem confirmada e a política restaurada](imagens/imagem%20(9).png)

## Como foi construído

Tudo roda em uma única instância **EC2 Linux** na região `us-east-1`:

- **Backend em Python** (FastAPI + boto3) expõe a API e hospeda o *Verificador_Entrega*, que lê as filas de forma **não destrutiva** — nunca apaga mensagens, para não atrapalhar outros testes.
- **Dashboard** em HTML/CSS/JS puro, servido pela própria EC2.
- **Autenticação na AWS só pela IAM Role** da instância (credenciais temporárias, sem Access Key fixa em lugar nenhum).

Uma regra de ouro: a aplicação **usa** os recursos AWS, mas **nunca cria, altera ou apaga** nada — a única exceção é aquele ajuste temporário e reversível no teste de DLQ. Todos os recursos (tópicos, filas, assinaturas, IAM, EC2) são criados manualmente no Console, de propósito, para praticar.

O SNS é a estrela; o SQS entra **só como destino** do fan-out, servindo para confirmar a entrega real. Nenhuma funcionalidade de SQS é ensinada aqui.

## O que eu aprendi

A lição que mais marcou: **publicar não é entregar**. Tratar as duas coisas como iguais produz um dashboard que mente. Separar `Entrega_Publicada` de `Entrega_Confirmada` mudou como eu penso sobre mensageria.

A segunda: **observar sem interferir** exige disciplina — leitura não destrutiva, correlação por um identificador de negócio e um timeout honesto que aceita o "Não confirmado". E a terceira: a **DLQ do SNS é um conceito de assinatura**, demonstrável com segurança através de uma falha reversível.

## Rodando o projeto

Para operar contra a AWS real, a aplicação precisa rodar numa EC2 com a IAM Role anexada e os recursos já criados (o passo a passo completo está em [`IMPLANTACAO.md`](IMPLANTACAO.md)). Em produção, sobe como serviço `systemd`:

```bash
uvicorn app.main_sns:app --host 0.0.0.0 --port 8000
```

A suíte de testes roda localmente, sem precisar de AWS:

```bash
python -m pytest
```

São **537 testes** cobrindo as regras de correção — desde "só confirma entrega com leitura real" até "a política de acesso é restaurada idêntica à original".

## Documentação completa

- [`ARQUITETURA.md`](ARQUITETURA.md) — diagramas, fluxos e decisões de design
- [`IMPLANTACAO.md`](IMPLANTACAO.md) — passo a passo de criação dos recursos no Console AWS, com imagens
- [`TESTES.md`](TESTES.md) — roteiro dos seis experimentos, com evidências

---

*Projeto de portfólio para estudo de Amazon SNS (fan-out, Standard vs FIFO, ordenação e DLQ), com foco em honestidade didática: mostrar o que realmente acontece com cada mensagem.*
