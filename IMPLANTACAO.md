# IMPLANTACAO.md — Implantação manual do AWS SNS Delivery Lab

Este documento descreve, em Português do Brasil (pt-BR), o passo a passo para implantar manualmente, pelo **Console AWS**, toda a infraestrutura do laboratório **AWS SNS Delivery Lab** e para instalar e executar a aplicação na instância **Amazon EC2**. Nenhum recurso é criado por Infrastructure as Code (Terraform, CloudFormation, SAM, CDK): o objetivo didático é praticar a criação e a configuração de cada serviço de mensageria no Console.

Todos os recursos ficam na região **us-east-1 (Norte da Virgínia)**. A autenticação da aplicação com a AWS ocorre exclusivamente pela **IAM_Role_EC2** anexada à instância EC2 (credenciais temporárias), sem Access Keys fixas. A aplicação **não cria, modifica nem exclui** recursos AWS, exceto o ajuste temporário e reversível da `Access_Policy_Fila` usado no cenário de Falha de Entrega Controlada.

> **Convenção de nomes.** Os nomes abaixo seguem o Glossário do projeto e são exatamente os nomes reais exibidos no Console AWS. Mantêm-se em inglês apenas termos técnicos, nomes de serviços AWS, nomes de parâmetros, nomes de variáveis e comandos.

## Sumário

- [1. Recursos que serão criados](#1-recursos-que-serão-criados)
- [2. Pré-requisitos](#2-pré-requisitos)
- [3. Passo a passo de implantação](#3-passo-a-passo-de-implantação)
  - [Etapa 1 — Criar o Topico_Standard](#etapa-1--criar-o-topico_standard)
  - [Etapa 2 — Criar o Topico_FIFO (com Deduplicacao_Por_Conteudo)](#etapa-2--criar-o-topico_fifo-com-deduplicacao_por_conteudo)
  - [Etapa 3 — Criar as seis filas de destino](#etapa-3--criar-as-seis-filas-de-destino)
  - [Etapa 4 — Criar as duas DLQs do SNS](#etapa-4--criar-as-duas-dlqs-do-sns)
  - [Etapa 5 — Configurar a Access_Policy_Fila de cada fila de destino](#etapa-5--configurar-a-access_policy_fila-de-cada-fila-de-destino)
  - [Etapa 6 — Autorizar o SNS a publicar nas DLQs](#etapa-6--autorizar-o-sns-a-publicar-nas-dlqs)
  - [Etapa 7 — Criar as seis assinaturas com Redrive_Policy_SNS](#etapa-7--criar-as-seis-assinaturas-com-redrive_policy_sns)
  - [Etapa 8 — Criar a IAM_Role_EC2 (privilégios mínimos, sem Access Keys)](#etapa-8--criar-a-iam_role_ec2-privilégios-mínimos-sem-access-keys)
  - [Etapa 9 — Criar os Grupos de Segurança (porta 22 fechada)](#etapa-9--criar-os-grupos-de-segurança-porta-22-fechada)
  - [Etapa 10 — Criar a instância EC2 Linux com Session Manager](#etapa-10--criar-a-instância-ec2-linux-com-session-manager)
  - [Etapa 11 — Instalar e executar a aplicação na EC2](#etapa-11--instalar-e-executar-a-aplicação-na-ec2)
- [4. Verificação pós-implantação](#4-verificação-pós-implantação)
- [5. Tratamento de falhas de etapa](#5-tratamento-de-falhas-de-etapa)
- [6. Custo mensal estimado em USD](#6-custo-mensal-estimado-em-usd)
- [7. Exclusão dos recursos ao final (ordem de dependência)](#7-exclusão-dos-recursos-ao-final-ordem-de-dependência)

---

## 1. Recursos que serão criados

| Recurso (Glossário) | Nome real no Console AWS | Tipo |
|---|---|---|
| Topico_Standard | `delivery-standard` | SNS Standard |
| Topico_FIFO | `delivery-fifo.fifo` | SNS FIFO |
| Fila_Destino_Standard (Destino_1/2/3) | `delivery-destino1-standard`, `delivery-destino2-standard`, `delivery-destino3-standard` | SQS Standard |
| Fila_Destino_FIFO (Destino_1/2/3) | `delivery-destino1-fifo.fifo`, `delivery-destino2-fifo.fifo`, `delivery-destino3-fifo.fifo` | SQS FIFO |
| DLQ_SNS_Standard | `delivery-sns-dlq-standard` | SQS Standard |
| DLQ_SNS_FIFO | `delivery-sns-dlq.fifo` | SQS FIFO |
| Assinatura_SNS (seis) | 3 do `delivery-standard` + 3 do `delivery-fifo.fifo` | SNS Subscription (protocolo SQS) |
| IAM_Role_EC2 | `sns-delivery-lab-ec2-role` | Função do IAM |
| Grupo de Segurança | `sns-delivery-lab-sg` | Grupo de Segurança do EC2 |
| Instância EC2 | `sns-delivery-lab` | EC2 (Amazon Linux 2023, `t3.micro`) |

> O sufixo `.fifo` é **obrigatório** nos recursos FIFO (tópico e filas). Sem ele, o Console não permite habilitar o tipo FIFO.

## 2. Pré-requisitos

- Conta AWS com acesso ao Console na região **us-east-1**.
- Permissão para criar recursos de SNS, SQS, IAM e EC2.
- Um VPC com ao menos uma sub-rede pública (a VPC padrão da conta atende).
- Código da aplicação disponível (este repositório), que será copiado para a EC2 na Etapa 11.

Mantenha anotados, à medida que criar os recursos, os seguintes identificadores — eles são usados nas etapas de policy e de verificação:

- **ID da conta** (*Account ID*, 12 dígitos), visível no menu da conta, no canto superior direito do Console.
- **ARN do Topico_Standard** e **ARN do Topico_FIFO** (exibidos na página do tópico).
- **ARN** e **URL** de cada fila SQS (exibidos na página da fila).

---

## 3. Passo a passo de implantação

Cada etapa indica a **ação/comando**, **o que faz**, **por que é executada** e o **resultado esperado**. Siga a ordem apresentada: as dependências (policies e assinaturas) exigem que os recursos anteriores já existam.

### Etapa 1 — Criar o Topico_Standard

1. No Console, abra o serviço **Amazon SNS** e confirme a região **us-east-1** (canto superior direito).
2. No menu lateral, clique em **Tópicos** (*Topics*) → **Criar tópico** (*Create topic*).
3. Em **Tipo** (*Type*), selecione **Standard**.
4. Em **Nome** (*Name*), informe `delivery-standard`.
5. Deixe as demais opções no padrão e clique em **Criar tópico** (*Create topic*).

- **O que faz:** cria o tópico SNS do tipo Standard que recebe os disparos do cenário Standard.
- **Por que:** é o ponto de fan-out para as três filas de destino Standard (Req. 1.1).
- **Resultado esperado:** a página do tópico abre exibindo **Tipo: Standard** e o **ARN** no formato `arn:aws:sns:us-east-1:<account-id>:delivery-standard`. Anote esse ARN.

### Etapa 2 — Criar o Topico_FIFO (com Deduplicacao_Por_Conteudo)

1. Em **Amazon SNS** → **Tópicos** (*Topics*) → **Criar tópico** (*Create topic*).
2. Em **Tipo** (*Type*), selecione **FIFO**.
3. Em **Nome** (*Name*), informe `delivery-fifo.fifo` (o sufixo `.fifo` é obrigatório).
4. Marque a opção **Deduplicação baseada em conteúdo** (*Content-based deduplication*) — a Deduplicacao_Por_Conteudo.
5. Clique em **Criar tópico** (*Create topic*).

- **O que faz:** cria o tópico FIFO com deduplicação por conteúdo habilitada.
- **Por que:** o cenário FIFO demonstra ordenação por `MessageGroupId`; com a Deduplicacao_Por_Conteudo habilitada, o `MessageDeduplicationId` é gerado a partir do conteúdo e não precisa ser informado no disparo (Req. 1.2, 2.3, 16.1).
- **Resultado esperado:** a página do tópico exibe **Tipo: FIFO**, **Deduplicação baseada em conteúdo: Habilitado** e o **ARN** `arn:aws:sns:us-east-1:<account-id>:delivery-fifo.fifo`. Anote esse ARN.

### Etapa 3 — Criar as seis filas de destino

Crie primeiro as **três filas Standard** e depois as **três filas FIFO**.

**Filas Standard (repita para cada nome):**

1. Abra o serviço **Amazon SQS** → **Criar fila** (*Create queue*), região **us-east-1**.
2. Em **Tipo** (*Type*), selecione **Standard**.
3. Em **Nome** (*Name*), informe, uma por vez: `delivery-destino1-standard`, `delivery-destino2-standard`, `delivery-destino3-standard`.
4. Mantenha os padrões e clique em **Criar fila** (*Create queue*).

**Filas FIFO (repita para cada nome):**

1. **Criar fila** (*Create queue*) → **Tipo: FIFO**.
2. Em **Nome** (*Name*), informe, uma por vez: `delivery-destino1-fifo.fifo`, `delivery-destino2-fifo.fifo`, `delivery-destino3-fifo.fifo` (sufixo `.fifo` obrigatório).
3. Deixe **Deduplicação baseada em conteúdo** (*Content-based deduplication*) da fila no padrão (desmarcado); a deduplicação relevante do laboratório é a do tópico.
4. Clique em **Criar fila** (*Create queue*).

- **O que faz:** cria as seis filas SQS que recebem o fan-out dos tópicos (três por cenário, uma por destino).
- **Por que:** as filas de destino são o único meio de **confirmar a entrega real** das mensagens (Entrega_Confirmada), lidas pelo Verificador_Entrega (Req. 1.3, 1.4, 16.2).
- **Resultado esperado:** as seis filas aparecem na lista do SQS. Em cada página de fila, anote o **ARN** e a **URL**.

### Etapa 4 — Criar as duas DLQs do SNS

1. Em **Amazon SQS** → **Criar fila** (*Create queue*) → **Tipo: Standard** → **Nome:** `delivery-sns-dlq-standard` → **Criar fila** (*Create queue*).
2. **Criar fila** (*Create queue*) → **Tipo: FIFO** → **Nome:** `delivery-sns-dlq.fifo` → **Criar fila** (*Create queue*).

- **O que faz:** cria as duas Dead-Letter Queues compartilhadas pelas assinaturas de cada tópico.
- **Por que:** a DLQ do SNS é configurada na assinatura (Redrive_Policy_SNS) e recebe as mensagens que o SNS não conseguiu entregar; o tipo da DLQ deve ser compatível com o tipo do tópico (Req. 1.5, 1.6, 16.2).
- **Resultado esperado:** as duas DLQs aparecem na lista do SQS. Anote o **ARN** de cada uma.

### Etapa 5 — Configurar a Access_Policy_Fila de cada fila de destino

Cada uma das **seis filas de destino** precisa autorizar o tópico SNS correspondente a publicar nela. Faça isso editando a política de acesso da fila.

Para cada fila de destino:

1. Em **Amazon SQS**, abra a fila → aba **Política de acesso** (*Access policy*) → **Editar** (*Edit*).
2. Substitua/complemente a policy pelo JSON abaixo, ajustando os espaços reservados:
   - `<account-id>`: seu ID da conta.
   - `<ARN_DA_FILA>`: o ARN da fila que está sendo editada.
   - `<ARN_DO_TOPICO>`: o ARN de `delivery-standard` para as filas `*-standard` e de `delivery-fifo.fifo` para as filas `*-fifo.fifo`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PermitirSnsPublicar",
      "Effect": "Allow",
      "Principal": { "Service": "sns.amazonaws.com" },
      "Action": "sqs:SendMessage",
      "Resource": "<ARN_DA_FILA>",
      "Condition": {
        "ArnEquals": { "aws:SourceArn": "<ARN_DO_TOPICO>" }
      }
    }
  ]
}
```

3. Clique em **Salvar** (*Save*).

- **O que faz:** autoriza a publicação na fila **apenas** pelo tópico SNS correspondente, por meio da condição `aws:SourceArn`.
- **Por que:** sem essa policy o SNS não consegue entregar à fila; a condição por `SourceArn` garante que só o tópico certo publique, rejeitando outras origens (Req. 12.8, 16.3). Essa também é a policy que o cenário de Falha de Entrega Controlada ajusta temporariamente com um statement `Deny` e restaura ao final.
- **Resultado esperado:** a aba **Política de acesso** passa a exibir a declaração `Allow` para `sns.amazonaws.com` com a condição por `SourceArn`.

### Etapa 6 — Autorizar o SNS a publicar nas DLQs

As DLQs também precisam aceitar mensagens enviadas pelo SNS. Repita a configuração de política de acesso da Etapa 5 nas **duas DLQs**:

- Em `delivery-sns-dlq-standard`, use `<ARN_DO_TOPICO>` = ARN de `delivery-standard`.
- Em `delivery-sns-dlq.fifo`, use `<ARN_DO_TOPICO>` = ARN de `delivery-fifo.fifo`.

- **O que faz:** autoriza o SNS a depositar na DLQ as mensagens não entregues.
- **Por que:** sem essa autorização a Redrive_Policy_SNS da assinatura não consegue encaminhar à DLQ (Req. 16.5).
- **Resultado esperado:** cada DLQ exibe o statement `Allow` para `sns.amazonaws.com` condicionado ao ARN do tópico correspondente.

### Etapa 7 — Criar as seis assinaturas com Redrive_Policy_SNS

Crie **três assinaturas no `delivery-standard`** (para as três filas Standard) e **três assinaturas no `delivery-fifo.fifo`** (para as três filas FIFO). O procedimento é o mesmo para cada uma.

Para cada assinatura:

1. Em **Amazon SNS** → **Tópicos** (*Topics*), abra o tópico (`delivery-standard` ou `delivery-fifo.fifo`).
2. Clique em **Criar assinatura** (*Create subscription*).
3. Em **Protocolo** (*Protocol*), selecione **Amazon SQS**.
4. Em **Ponto de extremidade** (*Endpoint*), selecione o **ARN da fila de destino** compatível (filas `*-standard` para o tópico Standard; filas `*-fifo.fifo` para o tópico FIFO).
5. **Entrega de mensagem bruta** (*Raw message delivery*): deixe **desabilitado**. O laboratório lê o envelope do SNS (campo `Message` e `MessageAttributes`) para extrair o `ID_Pedido`.
6. Expanda **Política de redirecionamento (fila de mensagens mortas)** (*Redrive policy (dead-letter queue)*) e marque **Habilitado** (*Enabled*).
7. Em **Fila de mensagens mortas (Amazon SQS)** (*Dead-letter queue (Amazon SQS)*), selecione o **ARN da DLQ compatível**:
   - assinaturas do `delivery-standard` → `delivery-sns-dlq-standard`;
   - assinaturas do `delivery-fifo.fifo` → `delivery-sns-dlq.fifo`.
8. Clique em **Criar assinatura** (*Create subscription*).

- **O que faz:** cria o vínculo (fan-out) entre o tópico e cada fila de destino e define a DLQ da assinatura.
- **Por que:** são as seis assinaturas que distribuem a mensagem publicada para os três destinos de cada cenário; a Redrive_Policy_SNS garante que entregas falhas sigam para a DLQ compatível (Req. 1.7, 2.2, 16.4, 16.5).
- **Resultado esperado:** o tópico lista três assinaturas com **Status: Confirmado** (*Confirmed*) e a coluna de **Política de redirecionamento** (*Redrive policy*) preenchida. Ao final, há **seis** assinaturas no total.

### Etapa 8 — Criar a IAM_Role_EC2 (privilégios mínimos, sem Access Keys)

1. Abra o serviço **IAM** → **Políticas** (*Policies*) → **Criar política** (*Create policy*) → aba **JSON** e cole a política abaixo, substituindo `<account-id>`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicarNosTopicos",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": [
        "arn:aws:sns:us-east-1:<account-id>:delivery-standard",
        "arn:aws:sns:us-east-1:<account-id>:delivery-fifo.fifo"
      ]
    },
    {
      "Sid": "ListarTopicosSNS",
      "Effect": "Allow",
      "Action": "sns:ListTopics",
      "Resource": "*"
    },
    {
      "Sid": "ConsultarTopicosEAssinaturas",
      "Effect": "Allow",
      "Action": [
        "sns:GetTopicAttributes",
        "sns:ListSubscriptionsByTopic"
      ],
      "Resource": [
        "arn:aws:sns:us-east-1:<account-id>:delivery-standard",
        "arn:aws:sns:us-east-1:<account-id>:delivery-fifo.fifo"
      ]
    },
    {
      "Sid": "ConsultarAtributosAssinaturas",
      "Effect": "Allow",
      "Action": "sns:GetSubscriptionAttributes",
      "Resource": "arn:aws:sns:us-east-1:<account-id>:*"
    },
    {
      "Sid": "ConsultarRoleEC2",
      "Effect": "Allow",
      "Action": "iam:GetRole",
      "Resource": "arn:aws:iam::<account-id>:role/sns-delivery-lab-ec2-role"
    },
    {
      "Sid": "ConsultarInstanciaEC2",
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*",
      "Condition": {
        "StringEquals": { "ec2:Region": "us-east-1" }
      }
    },
    {
      "Sid": "LerFilasEDlqsEAjustarPolicyTemporaria",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:SetQueueAttributes"
      ],
      "Resource": [
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino1-standard",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino2-standard",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino3-standard",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino1-fifo.fifo",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino2-fifo.fifo",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-destino3-fifo.fifo",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-sns-dlq-standard",
        "arn:aws:sqs:us-east-1:<account-id>:delivery-sns-dlq.fifo"
      ]
    }
  ]
}
```

> **Por que cada permissão.** `sns:Publish` publica nas mensagens dos cenários; `sns:ListTopics`, `sns:GetTopicAttributes` e `sns:ListSubscriptionsByTopic` montam a arquitetura visual e confirmam o tipo/deduplicação dos tópicos; `sns:GetSubscriptionAttributes` lê a Redrive_Policy_SNS de cada assinatura; `iam:GetRole` e `ec2:DescribeInstances` são usados pela **verificação de inicialização** (Req. 1.9) para confirmar a IAM Role e a instância EC2 — sem `ec2:DescribeInstances`, a verificação falha com `MissingParameter`/`AccessDenied` e o Dashboard não é servido; o bloco de SQS lê as filas de destino e as DLQs (leitura não destrutiva) e, **apenas** no cenário de Falha_Entrega_Controlada, ajusta temporariamente a Access_Policy_Fila via `sqs:SetQueueAttributes` (única permissão de escrita, reversível).

2. Nomeie a política como `sns-delivery-lab-policy` e clique em **Criar política** (*Create policy*).
3. Vá em **IAM** → **Funções** (*Roles*) → **Criar função** (*Create role*).
4. Em **Tipo de entidade confiável** (*Trusted entity type*), selecione **Serviço da AWS** (*AWS service*); em **Caso de uso** (*Use case*), selecione **EC2**. Avance.
5. Anexe duas políticas: a `sns-delivery-lab-policy` (criada acima) e a política gerenciada **`AmazonSSMManagedInstanceCore`** (necessária para o Session Manager).
6. Nomeie a função como `sns-delivery-lab-ec2-role` e clique em **Criar função** (*Create role*).

- **O que faz:** cria uma Função do IAM com os privilégios mínimos — publicar nos dois tópicos (`sns:Publish`), listar assinaturas (`sns:ListSubscriptionsByTopic`), ler filas e DLQs (`sqs:ReceiveMessage`, `sqs:GetQueueAttributes`, `sqs:GetQueueUrl`) e ajustar temporariamente a Access_Policy_Fila do cenário de DLQ (`sqs:SetQueueAttributes`) — além de habilitar o Session Manager.
- **Por que:** a aplicação se autentica na AWS exclusivamente por essa role (credenciais temporárias via IMDSv2), sem Access Keys fixas, e com acesso restrito aos recursos do laboratório (Req. 12.1, 12.2, 12.3, 16.6). A policy **não** concede `sqs:DeleteMessage` porque a leitura é sempre não destrutiva.
- **Resultado esperado:** a função `sns-delivery-lab-ec2-role` aparece em **IAM** → **Funções** (*Roles*) com as duas políticas anexadas.

### Etapa 9 — Criar os Grupos de Segurança (porta 22 fechada)

1. Abra **EC2** → **Grupos de segurança** (*Security Groups*) → **Criar grupo de segurança** (*Create security group*), na mesma VPC em que a EC2 será criada.
2. **Nome** (*Name*): `sns-delivery-lab-sg`. **Descrição** (*Description*): `Dashboard SNS Delivery Lab`.
3. **Regras de entrada** (*Inbound rules*) — adicione **apenas** a porta da aplicação, restrita às origens autorizadas:
   - Tipo (*Type*) **TCP personalizado** (*Custom TCP*), Porta (*Port*) **8000**, Origem (*Source*): o **Meu IP** (*My IP*) ou a faixa das origens autorizadas. **Não** use `0.0.0.0/0`.
4. **Não** adicione regra para a porta **22 (SSH)**. A porta 22 permanece sem regra de entrada.
5. **Regras de saída** (*Outbound rules*): mantenha o padrão (saída liberada), necessário para a EC2 alcançar os endpoints da AWS (SNS, SQS, Systems Manager) e instalar pacotes.
6. Clique em **Criar grupo de segurança** (*Create security group*).

- **O que faz:** restringe o acesso de entrada à porta da aplicação (8000) e mantém a porta 22 (SSH) fechada.
- **Por que:** o acesso administrativo à EC2 é feito exclusivamente via Session Manager, dispensando SSH; expor a porta 22 seria desnecessário e inseguro (Req. 12.7, 15.3, 16.7).
- **Resultado esperado:** o Grupo de Segurança lista somente a regra de entrada da porta 8000 restrita; nenhuma regra para a porta 22.

### Etapa 10 — Criar a instância EC2 Linux com Session Manager

1. Abra **EC2** → **Instâncias** (*Instances*) → **Executar instâncias** (*Launch instances*), região **us-east-1**.
2. **Nome** (*Name*): `sns-delivery-lab`.
3. **Imagem de máquina da Amazon (AMI)** (*AMI*): **Amazon Linux 2023** (já inclui o agente do Systems Manager).
4. **Tipo de instância** (*Instance type*): `t3.micro` (dentro do nível gratuito elegível; suficiente para o laboratório).
5. **Par de chaves (login)** (*Key pair*): selecione **Continuar sem um par de chaves** (*Proceed without a key pair*) — não é necessário par de chaves, pois o acesso é via Session Manager.
6. **Configurações de rede** (*Network settings*): selecione a VPC/sub-rede pública e, em **Firewall (grupos de segurança)** (*Firewall (security groups)*), escolha **Selecionar grupo de segurança existente** (*Select existing security group*) → `sns-delivery-lab-sg`.
7. **Detalhes avançados** (*Advanced details*) → **Perfil de instância do IAM** (*IAM instance profile*): selecione `sns-delivery-lab-ec2-role`.
8. Clique em **Executar instância** (*Launch instance*).

- **O que faz:** cria a instância Linux que hospeda a API_Backend, o Verificador_Entrega e o Dashboard, já com a Função do IAM anexada e sem par de chaves SSH.
- **Por que:** a aplicação roda inteiramente na EC2 e usa a Função do IAM anexada para autenticar no SNS/SQS; a administração ocorre via Session Manager, sem SSH (Req. 15.3, 16.7).
- **Resultado esperado:** a instância `sns-delivery-lab` fica com **Estado da instância: Executando** (*Running*). Anote o **ID da instância** (*Instance ID*, `i-...`). Após alguns minutos, em **EC2** → selecione a instância → **Conectar** (*Connect*) → aba **Session Manager**, o botão **Conectar** (*Connect*) fica habilitado, confirmando que o agente SSM registrou a instância.

### Etapa 11 — Instalar e executar a aplicação na EC2

Conecte-se à instância pelo **Session Manager** (**EC2** → instância → **Conectar** (*Connect*) → **Session Manager** → **Conectar**). Os comandos abaixo são executados no terminal aberto no navegador.

1. Atualizar os pacotes do sistema e instalar Python, pip, git e o cliente de rede:

```bash
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git
```

- **O que faz:** atualiza o sistema e instala o Python 3.11, o `pip` e o `git`.
- **Por que:** a aplicação é escrita em Python (FastAPI + boto3) e o código será obtido via git.
- **Resultado esperado:** `python3.11 --version` responde `Python 3.11.x`.

2. Obter o código da aplicação:

```bash
cd /opt
sudo git clone <URL_DO_REPOSITORIO> amazon-sns2
sudo chown -R ssm-user:ssm-user /opt/amazon-sns2
cd /opt/amazon-sns2
```

- **O que faz:** clona o repositório em `/opt/amazon-sns2` e ajusta a propriedade dos arquivos para o usuário da sessão.
- **Por que:** o código precisa estar presente na EC2 para ser executado; `/opt` é um local padrão para aplicações.
- **Resultado esperado:** o diretório `/opt/amazon-sns2` contém `app/`, `web/`, `requirements.txt` etc. (substitua `<URL_DO_REPOSITORIO>` pela URL real; alternativamente, envie os arquivos por outro meio).

3. Criar um ambiente virtual e instalar as dependências:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- **O que faz:** cria um ambiente virtual isolado e instala `fastapi`, `uvicorn`, `boto3` e as demais dependências listadas em `requirements.txt`.
- **Por que:** isolar as dependências evita conflitos com pacotes do sistema; o `boto3` resolverá as credenciais da Função do IAM automaticamente.
- **Resultado esperado:** `pip` conclui sem erros; `pip show boto3` exibe a versão instalada.

4. Configurar as variáveis de ambiente da aplicação (nenhum segredo da AWS é definido aqui — a autenticação é via Função do IAM):

```bash
export DASHBOARD_SNS_USUARIO="admin"
export DASHBOARD_SNS_SENHA="defina-uma-senha-forte"
export DASHBOARD_SNS_ORIGENS_AUTORIZADAS="<SEU_IP>"
export SNS_LAB_IAM_ROLE="sns-delivery-lab-ec2-role"
export SNS_LAB_EC2_INSTANCE_ID="<INSTANCE_ID>"
```

- **O que faz:** define usuário/senha do Dashboard, a lista de origens (IPs) autorizadas a fazer login e os identificadores da Função do IAM e da instância usados na verificação de inicialização.
- **Por que:** o Dashboard exige autenticação quando exposto à internet e restringe o acesso às origens autorizadas; as credenciais vêm do ambiente, nunca do código (Req. 12.2, 12.5, 12.7). Troque `<SEU_IP>` pelo IP de origem e `<INSTANCE_ID>` pelo `i-...` da Etapa 10.
- **Resultado esperado:** `echo $DASHBOARD_SNS_ORIGENS_AUTORIZADAS` exibe o IP configurado. (Para execução permanente, prefira um serviço `systemd` com um bloco `Environment=`; veja a observação ao final desta etapa.)

5. Iniciar a aplicação:

```bash
uvicorn app.main_sns:app --host 0.0.0.0 --port 8000
```

- **O que faz:** sobe o servidor web da API_Backend servindo também o Dashboard estático de `web/sns/`, na porta 8000, acessível pela rede.
- **Por que:** `app.main_sns:app` é o ponto de entrada que compõe a API, o Verificador_Entrega e o Dashboard, condicionando a disponibilização do Dashboard à verificação de inicialização dos recursos AWS (Req. 1.9, 9.1).
- **Resultado esperado:** o log exibe `Uvicorn running on http://0.0.0.0:8000`. Se a verificação de inicialização encontrar todos os recursos, o Dashboard é servido em `/`; se algum recurso faltar, a aplicação responde `HTTP 503` com a causa em pt-BR e **não** serve o Dashboard (ver Seção 5).

6. Acessar o Dashboard a partir de uma origem autorizada: abra `http://<IP_PUBLICO_DA_EC2>:8000/` no navegador e faça login com o usuário/senha definidos.

- **Resultado esperado:** o Dashboard "AWS SNS Delivery Lab" carrega em pt-BR, exibindo a arquitetura (dois tópicos, seis assinaturas, seis filas, duas DLQs) e as quatro ações principais.

> **Execução permanente (recomendado).** Rodar o `uvicorn` manualmente com `nohup ... &` funciona para um teste rápido, mas tem um risco real: nada impede subir um segundo processo por cima do primeiro, e os dois disputam a porta 8000 (erro `address already in use`), deixando a aplicação em estado inconsistente. Para produção, use o serviço `systemd` descrito na **Etapa 12**, que garante um único processo, reinício automático em falha e start no boot.

### Etapa 12 — Execução gerenciada com systemd (recomendado)

Esta etapa substitui o `uvicorn` manual por um serviço `systemd`, de modo que a aplicação rode como um único processo, reinicie sozinha em caso de falha e suba automaticamente no boot da instância. O repositório já traz a *unit* pronta em `deploy/sns-delivery-lab.service`.

1. Criar o arquivo de variáveis de ambiente **fora do git** (para não versionar segredos), com permissão restrita:

```bash
sudo tee /etc/sns-delivery-lab.env > /dev/null <<'EOF'
DASHBOARD_SNS_USUARIO=admin
DASHBOARD_SNS_SENHA=defina-uma-senha-forte
DASHBOARD_SNS_ORIGENS_AUTORIZADAS=SEU_IP_PUBLICO
SNS_LAB_IAM_ROLE=sns-delivery-lab-ec2-role
SNS_LAB_EC2_INSTANCE_ID=SEU_INSTANCE_ID
EOF
sudo chmod 600 /etc/sns-delivery-lab.env
```

- **O que faz:** grava as variáveis lidas por `app/main_sns.py` (usuário/senha do Dashboard, origens autorizadas, nome da IAM Role e ID da instância) num arquivo só de leitura pelo root.
- **Por que:** mantém os segredos fora do repositório e centralizados. Nenhuma Access Key da AWS entra aqui — a autenticação segue pela IAM_Role_EC2 (Req. 12.1, 12.2).
- **Atenção ao `SNS_LAB_EC2_INSTANCE_ID`:** informe o `i-...` **real** da instância. Na Amazon Linux 2023 (IMDSv2), ler o ID pela metadata exige um token; um `curl` simples sem token devolve vazio, e um ID vazio faz a verificação de inicialização falhar (ver a Seção 5). Pegue o ID com o comando abaixo e copie o valor para o arquivo:

```bash
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id
```

> **Origens (`DASHBOARD_SNS_ORIGENS_AUTORIZADAS`).** Informe o seu IP público para restringir o login. Se o seu IP muda com frequência (redes com CGNAT costumam alternar o IP de saída), pode usar `*` para liberar o login de qualquer origem **apenas em ambiente de laboratório**; nesse caso, a proteção de acesso passa a depender exclusivamente do Security Group (porta 8000 restrita).

2. Instalar a *unit* e apontar para o arquivo de variáveis:

```bash
sudo cp /opt/amazon-sns2/deploy/sns-delivery-lab.service /etc/systemd/system/sns-delivery-lab.service
# desativa os Environment= inline (placeholders) e ativa o EnvironmentFile
sudo sed -i 's/^Environment=/#Environment=/' /etc/systemd/system/sns-delivery-lab.service
sudo sed -i 's|^# EnvironmentFile=/etc/sns-delivery-lab.env|EnvironmentFile=/etc/sns-delivery-lab.env|' /etc/systemd/system/sns-delivery-lab.service
```

- **O que faz:** copia a *unit* para o diretório do systemd e a configura para ler as variáveis de `/etc/sns-delivery-lab.env`.
- **Por que:** separa a configuração (service versionado) dos segredos (arquivo local), como recomenda a própria *unit*.

3. Garantir que nenhum `uvicorn` manual esteja rodando e subir o serviço:

```bash
pkill -f 'uvicorn app.main_sns:app' || true
sleep 2
sudo systemctl daemon-reload
sudo systemctl enable --now sns-delivery-lab
```

- **O que faz:** encerra qualquer `uvicorn` avulso (evita o conflito de porta), recarrega as *units* e habilita + inicia o serviço.
- **Resultado esperado:** o serviço sobe e fica habilitado no boot (o systemd cria o *symlink* em `multi-user.target.wants`).

4. Verificar:

```bash
systemctl status sns-delivery-lab --no-pager
curl -i http://localhost:8000/api/saude
```

- **Resultado esperado:** `Active: active (running)` no status e `HTTP/1.1 200 OK` no `curl`, com `"saudavel":true` no corpo. Os logs ficam no journald: `sudo journalctl -u sns-delivery-lab -n 50 --no-pager` (ou `-f` para acompanhar em tempo real).

> **Trocar a senha depois.** Edite `/etc/sns-delivery-lab.env` e rode `sudo systemctl restart sns-delivery-lab`. O serviço relê as variáveis na reinicialização.

### Etapa 13 — Elastic IP para IP fixo (recomendado se você liga/desliga a EC2)

Por padrão, o IP público de uma instância EC2 **muda a cada parada/início** (*stop/start*). Se você pretende **desligar e ligar a instância várias vezes** (prática comum para economizar custo em laboratório), associe um **Elastic IP**: o endereço passa a ser fixo e a URL do Dashboard não muda entre os ciclos. Combinado com o serviço systemd (Etapa 12), que sobe a aplicação automaticamente no boot, o laboratório fica acessível sempre na mesma URL após cada ligamento.

1. **EC2 → Rede e segurança → IPs elásticos** (*Elastic IPs*) → **Alocar endereço IP elástico** (*Allocate Elastic IP address*) → **Alocar**. Dê um nome na *tag* (ex.: `sns-delivery-lab-eip`).
2. Selecione o IP alocado → **Ações** (*Actions*) → **Associar endereço IP elástico** (*Associate Elastic IP address*) → escolha a instância `sns-delivery-lab` → **Associar**.
3. Confirme em **EC2 → Instâncias** que o **IP público** da instância passou a ser o Elastic IP. Use esse endereço fixo para acessar `http://<ELASTIC_IP>:8000/`.

- **O que faz:** fixa o IP público da instância, de modo que *stop/start* não altere o endereço.
- **Por que:** no cenário de liga/desliga, evita ter de descobrir o novo IP a cada início e mantém uma URL de acesso estável (Req. 15.x de operação do laboratório).
- **Resultado esperado:** o Dashboard responde no mesmo IP após cada reinício; `GET /api/saude` continua retornando `"saudavel":true`.

> **Custo do Elastic IP.** A AWS cobra uma pequena taxa horária por endereço IPv4 público (inclusive Elastic IP) e, em especial, por Elastic IP **alocado mas não associado** a uma instância em execução. Enquanto associado à sua instância, o custo é de centavos por dia. Ao encerrar o laboratório, **libere o Elastic IP** (ver a Seção 7) para não pagar por um IP ocioso.

---

## 4. Verificação pós-implantação

Confirme que cada recurso foi criado com os nomes e os valores de Config_Aplicada previstos.

| # | Verificação | Onde conferir | Resultado esperado |
|---|---|---|---|
| 1 | Topico_Standard | SNS → Tópicos → `delivery-standard` | Tipo **Standard** |
| 2 | Topico_FIFO + dedup | SNS → Tópicos → `delivery-fifo.fifo` | Tipo **FIFO**, **Deduplicação baseada em conteúdo: Habilitado** |
| 3 | Seis filas de destino | SQS → lista | `delivery-destino1/2/3-standard` e `delivery-destino1/2/3-fifo.fifo` presentes |
| 4 | Duas DLQs | SQS → lista | `delivery-sns-dlq-standard` e `delivery-sns-dlq.fifo` presentes |
| 5 | Access_Policy_Fila | SQS → cada fila → **Política de acesso** | Declaração `Allow` para `sns.amazonaws.com` com condição por `SourceArn` do tópico |
| 6 | Seis assinaturas + Redrive | SNS → cada tópico → **Assinaturas** | 3 por tópico, **Confirmado**, com Política de redirecionamento apontando para a DLQ compatível |
| 7 | IAM_Role_EC2 | IAM → Funções → `sns-delivery-lab-ec2-role` | `sns-delivery-lab-policy` + `AmazonSSMManagedInstanceCore`; sem Access Keys |
| 8 | Grupo de Segurança | EC2 → Grupos de segurança → `sns-delivery-lab-sg` | Entrada só na porta 8000 restrita; **sem** porta 22 |
| 9 | Instância EC2 | EC2 → Instâncias → `sns-delivery-lab` | **Executando**, com a Função do IAM anexada e Session Manager disponível |
| 10 | Verificação automática | Dashboard em `http://<IP>:8000/` ou `GET /api/saude` | Dashboard carrega; `/api/saude` indica todos os recursos acessíveis |

Se o endpoint `GET /api/saude` ou o Dashboard apontar um recurso indisponível, ele é identificado por **nome e tipo** em pt-BR — use essa indicação para localizar a etapa correspondente e corrigir.

---

## 5. Tratamento de falhas de etapa

Se um passo não puder ser concluído por **recurso ausente**, **permissão insuficiente** ou **valor de configuração divergente**, identifique a causa e corrija **antes** de prosseguir para o passo seguinte.

| Sintoma | Causa provável | Como identificar | Como corrigir | Como validar |
|---|---|---|---|---|
| Console não permite habilitar FIFO | Nome do recurso FIFO sem o sufixo `.fifo` | A opção FIFO fica indisponível ao digitar o nome | Recriar o tópico/fila com o nome terminando em `.fifo` | O recurso aparece com **Tipo: FIFO** |
| Assinatura fica em **Pendente de confirmação** (*PendingConfirmation*) ou mensagem não chega à fila | `Access_Policy_Fila` ausente ou com `SourceArn` incorreto | SQS → fila → **Política de acesso**: declaração ausente ou com ARN de outro tópico | Refazer a Etapa 5 com o ARN correto do tópico | Após um disparo, a mensagem aparece na fila de destino |
| Mensagem não vai para a DLQ no teste de DLQ | DLQ sem autorização ao SNS ou Redrive_Policy_SNS não configurada | SQS → DLQ → **Política de acesso**; SNS → assinatura → **Política de redirecionamento** | Refazer as Etapas 6 e 7 na assinatura/DLQ compatível | Teste de DLQ confirma a mensagem na DLQ compatível |
| Aplicação responde `HTTP 503` ao iniciar | Verificação de inicialização encontrou recurso ausente/inacessível | O corpo da resposta (e o log) identifica o recurso por **nome e tipo** em pt-BR | Criar/corrigir o recurso indicado (nome, tipo, região) | Reiniciar o `uvicorn`; o Dashboard passa a ser servido |
| `AccessDenied` / `AuthorizationError` nos logs | Função do IAM sem a ação necessária ou não anexada à EC2 | Log do boto3 cita a ação negada (ex.: `sns:Publish`) | Ajustar `sns-delivery-lab-policy` (Etapa 8) e confirmar o Perfil de instância na EC2 | A operação (publicar/ler) passa a funcionar |
| Session Manager não conecta | Falta `AmazonSSMManagedInstanceCore` ou sem rota de saída | EC2 → Conectar → Session Manager com **Conectar** desabilitado | Anexar a política SSM à função (Etapa 8); garantir saída de rede (Etapa 9) | O botão **Conectar** do Session Manager fica habilitado |
| Dashboard não abre no navegador | Porta 8000 fechada ou origem não autorizada | Tempo esgotado no navegador; `DASHBOARD_SNS_ORIGENS_AUTORIZADAS` sem o IP | Liberar a porta 8000 só para a origem (Etapa 9) e incluir o IP na variável (Etapa 11.4) | O login do Dashboard é exibido |
| Login sempre bloqueado | Nenhuma origem autorizada configurada | Aviso de segurança em pt-BR no log de inicialização | Definir `DASHBOARD_SNS_ORIGENS_AUTORIZADAS` com o IP (ou `=*` apenas para teste) e reiniciar | O login passa a aceitar as credenciais |
| `[Errno 98] address already in use` ao iniciar o `uvicorn` | Já existe outro processo `uvicorn` ouvindo a porta 8000 (ex.: um `nohup` anterior) | `sudo ss -tlnp \| grep 8000` mostra um processo ativo; o log traz `address already in use` | Encerrar os processos avulsos (`pkill -f 'uvicorn app.main_sns:app'`) e usar o serviço systemd da Etapa 12 (processo único) | `sudo ss -tlnp \| grep 8000` mostra apenas o processo do serviço |
| `HTTP 503` com "recurso instância EC2 ausente/inacessível" e erro `MissingParameter ... InstanceId` | `SNS_LAB_EC2_INSTANCE_ID` vazio (metadata IMDSv2 lida sem token devolve vazio) | A mensagem do 503 cita `DescribeInstances` sem `InstanceId`; `grep SNS_LAB_EC2_INSTANCE_ID /etc/sns-delivery-lab.env` mostra valor em branco | Preencher o ID real (obtido com o token IMDSv2 da Etapa 12) e `sudo systemctl restart sns-delivery-lab` | `GET /api/saude` responde `"saudavel":true` e `/` serve o Dashboard (HTTP 200) |
| Faixa vermelha "Não foi possível atualizar as estatísticas", mas o `fetch` retorna HTTP 200 | Dashboard desatualizado no navegador (cache) após uma correção de JS | No DevTools, a requisição de estatísticas está 200, mas o Console pode mostrar erro de JS antigo | Atualizar o código (`git pull`) e dar *hard refresh* no navegador (`Ctrl+Shift+R`) para furar o cache | A faixa some e aparece "Última atualização bem-sucedida" com data/hora/fuso |

---

## 6. Custo mensal estimado em USD

Valores aproximados para a região **us-east-1**, considerando o uso **didático e de baixo volume** deste laboratório. Servem como estimativa de ordem de grandeza; os preços oficiais devem ser confirmados na calculadora e na página de preços da AWS.

| Recurso | Premissa de uso | Custo mensal estimado (USD) |
|---|---|---|
| EC2 `t3.micro` (Amazon Linux 2023) | 1 instância; nível gratuito elegível nos primeiros 12 meses; fora do nível gratuito, ~730 h/mês sob demanda | ~US$ 0 (nível gratuito) ou ~US$ 7–8 |
| Volume EBS `gp3` 8 GB | disco raiz da EC2 | ~US$ 0,64 |
| Amazon SNS | publicações do laboratório (dezenas a centenas de mensagens/mês); primeiras 1.000.000 publicações gratuitas | ~US$ 0 |
| Amazon SQS (6 filas de destino + 2 DLQs) | leituras com Long Polling e poucos disparos; primeiras 1.000.000 requisições gratuitas | ~US$ 0 |
| IAM, Grupo de Segurança, Session Manager | sem custo próprio | US$ 0 |
| Transferência de dados de saída | tráfego mínimo do Dashboard; primeiros 100 GB/mês gratuitos | ~US$ 0 |
| **Total estimado** | laboratório ligado apenas durante os testes | **~US$ 0 a ~US$ 8–9 / mês** |

Observações que reduzem o custo:
- A arquitetura **não** usa **NAT Gateway** nem **Elastic Load Balancer** (os maiores custos fixos típicos), conforme Req. 15.1 e 15.2.
- **Pare ou encerre a instância EC2** quando não estiver usando o laboratório — é o item que mais influencia o custo fora do nível gratuito.

---

## 7. Exclusão dos recursos ao final (ordem de dependência)

Ao encerrar o laboratório, remova **todos** os recursos abaixo. Siga a ordem indicada: ela respeita as dependências (assinaturas dependem de tópicos e filas; a instância depende da função e do grupo de segurança).

| Ordem | Recurso | Nome real | Onde excluir | Observação de dependência |
|---|---|---|---|---|
| 1 | Assinatura_SNS (as seis) | 3 do `delivery-standard` + 3 do `delivery-fifo.fifo` | SNS → Assinaturas → **Excluir** (*Delete*) | Remover antes dos tópicos e das filas |
| 2 | Topico_Standard | `delivery-standard` | SNS → Tópicos → **Excluir** (*Delete*) | — |
| 3 | Topico_FIFO | `delivery-fifo.fifo` | SNS → Tópicos → **Excluir** (*Delete*) | — |
| 4 | Fila_Destino_Standard (3) | `delivery-destino1/2/3-standard` | SQS → **Excluir** (*Delete*) | Após remover as assinaturas |
| 5 | Fila_Destino_FIFO (3) | `delivery-destino1/2/3-fifo.fifo` | SQS → **Excluir** (*Delete*) | Após remover as assinaturas |
| 6 | DLQ_SNS_Standard | `delivery-sns-dlq-standard` | SQS → **Excluir** (*Delete*) | Após remover as assinaturas |
| 7 | DLQ_SNS_FIFO | `delivery-sns-dlq.fifo` | SQS → **Excluir** (*Delete*) | Após remover as assinaturas |
| 8 | Instância EC2 | `sns-delivery-lab` | EC2 → Instâncias → **Encerrar** (*Terminate*) | Libera a Função do IAM anexada e o volume EBS raiz |
| 9 | Elastic IP (se criado na Etapa 13) | `sns-delivery-lab-eip` | EC2 → IPs elásticos → **Desassociar** e depois **Liberar** (*Release*) | Liberar após encerrar a instância, para não pagar por IP ocioso |
| 10 | Grupo de Segurança | `sns-delivery-lab-sg` | EC2 → Grupos de segurança → **Excluir** (*Delete*) | Só é possível após encerrar a instância |
| 11 | Função do IAM | `sns-delivery-lab-ec2-role` | IAM → Funções → **Excluir** (*Delete*) | Após encerrar a instância que a usava |
| 12 | Política do IAM | `sns-delivery-lab-policy` | IAM → Políticas → **Excluir** (*Delete*) | Após excluir a função que a referenciava |

Após executar a exclusão, **confirme** que nenhum recurso da lista permanece ativo (reveja as listas de SNS, SQS, EC2 e IAM). Se algum recurso remanescer, identifique-o pelo nome/identificador e repita a exclusão correspondente, respeitando a ordem acima.
