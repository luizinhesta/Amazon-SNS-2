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
  - [Etapa 9 — Criar os Security Groups (porta 22 fechada)](#etapa-9--criar-os-security-groups-porta-22-fechada)
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
| IAM_Role_EC2 | `sns-delivery-lab-ec2-role` | IAM Role |
| Security Group | `sns-delivery-lab-sg` | EC2 Security Group |
| Instância EC2 | `sns-delivery-lab` | EC2 (Amazon Linux 2023, `t3.micro`) |

> O sufixo `.fifo` é **obrigatório** nos recursos FIFO (tópico e filas). Sem ele, o Console não permite habilitar o tipo FIFO.

## 2. Pré-requisitos

- Conta AWS com acesso ao Console na região **us-east-1**.
- Permissão para criar recursos de SNS, SQS, IAM e EC2.
- Um VPC com ao menos uma sub-rede pública (a VPC padrão da conta atende).
- Código da aplicação disponível (este repositório), que será copiado para a EC2 na Etapa 11.

Mantenha anotados, à medida que criar os recursos, os seguintes identificadores — eles são usados nas etapas de policy e de verificação:

- **Account ID** (12 dígitos), visível no canto superior direito do Console.
- **ARN do Topico_Standard** e **ARN do Topico_FIFO** (exibidos na página do tópico).
- **ARN** e **URL** de cada fila SQS (exibidos na página da fila).

---

## 3. Passo a passo de implantação

Cada etapa indica a **ação/comando**, **o que faz**, **por que é executada** e o **resultado esperado**. Siga a ordem apresentada: as dependências (policies e assinaturas) exigem que os recursos anteriores já existam.

### Etapa 1 — Criar o Topico_Standard

1. No Console, abra o serviço **Amazon SNS** e confirme a região **us-east-1** (canto superior direito).
2. Menu **Topics** → **Create topic**.
3. Em **Type**, selecione **Standard**.
4. Em **Name**, informe `delivery-standard`.
5. Deixe as demais opções no padrão e clique em **Create topic**.

- **O que faz:** cria o tópico SNS do tipo Standard que recebe os disparos do cenário Standard.
- **Por que:** é o ponto de fan-out para as três filas de destino Standard (Req. 1.1).
- **Resultado esperado:** a página do tópico abre exibindo **Type: Standard** e o **ARN** no formato `arn:aws:sns:us-east-1:<account-id>:delivery-standard`. Anote esse ARN.

### Etapa 2 — Criar o Topico_FIFO (com Deduplicacao_Por_Conteudo)

1. Em **Amazon SNS** → **Topics** → **Create topic**.
2. Em **Type**, selecione **FIFO**.
3. Em **Name**, informe `delivery-fifo.fifo` (o sufixo `.fifo` é obrigatório).
4. Marque a opção **Content-based deduplication** (Deduplicacao_Por_Conteudo).
5. Clique em **Create topic**.

- **O que faz:** cria o tópico FIFO com deduplicação por conteúdo habilitada.
- **Por que:** o cenário FIFO demonstra ordenação por `MessageGroupId`; com a Deduplicacao_Por_Conteudo habilitada, o `MessageDeduplicationId` é gerado a partir do conteúdo e não precisa ser informado no disparo (Req. 1.2, 2.3, 16.1).
- **Resultado esperado:** a página do tópico exibe **Type: FIFO**, **Content-based deduplication: Enabled** e o **ARN** `arn:aws:sns:us-east-1:<account-id>:delivery-fifo.fifo`. Anote esse ARN.

### Etapa 3 — Criar as seis filas de destino

Crie primeiro as **três filas Standard** e depois as **três filas FIFO**.

**Filas Standard (repita para cada nome):**

1. Abra o serviço **Amazon SQS** → **Create queue**, região **us-east-1**.
2. Em **Type**, selecione **Standard**.
3. Em **Name**, informe, uma por vez: `delivery-destino1-standard`, `delivery-destino2-standard`, `delivery-destino3-standard`.
4. Mantenha os padrões e clique em **Create queue**.

**Filas FIFO (repita para cada nome):**

1. **Create queue** → **Type: FIFO**.
2. Em **Name**, informe, uma por vez: `delivery-destino1-fifo.fifo`, `delivery-destino2-fifo.fifo`, `delivery-destino3-fifo.fifo` (sufixo `.fifo` obrigatório).
3. Deixe **Content-based deduplication** da fila no padrão (desmarcado); a deduplicação relevante do laboratório é a do tópico.
4. Clique em **Create queue**.

- **O que faz:** cria as seis filas SQS que recebem o fan-out dos tópicos (três por cenário, uma por destino).
- **Por que:** as filas de destino são o único meio de **confirmar a entrega real** das mensagens (Entrega_Confirmada), lidas pelo Verificador_Entrega (Req. 1.3, 1.4, 16.2).
- **Resultado esperado:** as seis filas aparecem na lista do SQS. Em cada página de fila, anote o **ARN** e a **URL**.

### Etapa 4 — Criar as duas DLQs do SNS

1. Em **Amazon SQS** → **Create queue** → **Type: Standard** → **Name:** `delivery-sns-dlq-standard` → **Create queue**.
2. **Create queue** → **Type: FIFO** → **Name:** `delivery-sns-dlq.fifo` → **Create queue**.

- **O que faz:** cria as duas Dead-Letter Queues compartilhadas pelas assinaturas de cada tópico.
- **Por que:** a DLQ do SNS é configurada na assinatura (Redrive_Policy_SNS) e recebe as mensagens que o SNS não conseguiu entregar; o tipo da DLQ deve ser compatível com o tipo do tópico (Req. 1.5, 1.6, 16.2).
- **Resultado esperado:** as duas DLQs aparecem na lista do SQS. Anote o **ARN** de cada uma.

### Etapa 5 — Configurar a Access_Policy_Fila de cada fila de destino

Cada uma das **seis filas de destino** precisa autorizar o tópico SNS correspondente a publicar nela. Faça isso editando a access policy da fila.

Para cada fila de destino:

1. Em **Amazon SQS**, abra a fila → aba **Access policy** → **Edit**.
2. Substitua/complemente a policy pelo JSON abaixo, ajustando os espaços reservados:
   - `<account-id>`: seu Account ID.
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

3. Clique em **Save**.

- **O que faz:** autoriza a publicação na fila **apenas** pelo tópico SNS correspondente, por meio da condição `aws:SourceArn`.
- **Por que:** sem essa policy o SNS não consegue entregar à fila; a condição por `SourceArn` garante que só o tópico certo publique, rejeitando outras origens (Req. 12.8, 16.3). Essa também é a policy que o cenário de Falha de Entrega Controlada ajusta temporariamente com um statement `Deny` e restaura ao final.
- **Resultado esperado:** a aba **Access policy** passa a exibir o statement `Allow` para `sns.amazonaws.com` com a condição por `SourceArn`.

### Etapa 6 — Autorizar o SNS a publicar nas DLQs

As DLQs também precisam aceitar mensagens enviadas pelo SNS. Repita a configuração de access policy da Etapa 5 nas **duas DLQs**:

- Em `delivery-sns-dlq-standard`, use `<ARN_DO_TOPICO>` = ARN de `delivery-standard`.
- Em `delivery-sns-dlq.fifo`, use `<ARN_DO_TOPICO>` = ARN de `delivery-fifo.fifo`.

- **O que faz:** autoriza o SNS a depositar na DLQ as mensagens não entregues.
- **Por que:** sem essa autorização a Redrive_Policy_SNS da assinatura não consegue encaminhar à DLQ (Req. 16.5).
- **Resultado esperado:** cada DLQ exibe o statement `Allow` para `sns.amazonaws.com` condicionado ao ARN do tópico correspondente.

### Etapa 7 — Criar as seis assinaturas com Redrive_Policy_SNS

Crie **três assinaturas no `delivery-standard`** (para as três filas Standard) e **três assinaturas no `delivery-fifo.fifo`** (para as três filas FIFO). O procedimento é o mesmo para cada uma.

Para cada assinatura:

1. Em **Amazon SNS** → **Topics**, abra o tópico (`delivery-standard` ou `delivery-fifo.fifo`).
2. Clique em **Create subscription**.
3. Em **Protocol**, selecione **Amazon SQS**.
4. Em **Endpoint**, selecione o **ARN da fila de destino** compatível (filas `*-standard` para o tópico Standard; filas `*-fifo.fifo` para o tópico FIFO).
5. **Raw message delivery:** deixe **desabilitado**. O laboratório lê o envelope do SNS (campo `Message` e `MessageAttributes`) para extrair o `ID_Pedido`.
6. Expanda **Redrive policy (dead-letter queue)** e marque **Enabled**.
7. Em **Dead-letter queue (Amazon SQS)**, selecione o **ARN da DLQ compatível**:
   - assinaturas do `delivery-standard` → `delivery-sns-dlq-standard`;
   - assinaturas do `delivery-fifo.fifo` → `delivery-sns-dlq.fifo`.
8. Clique em **Create subscription**.

- **O que faz:** cria o vínculo (fan-out) entre o tópico e cada fila de destino e define a DLQ da assinatura.
- **Por que:** são as seis assinaturas que distribuem a mensagem publicada para os três destinos de cada cenário; a Redrive_Policy_SNS garante que entregas falhas sigam para a DLQ compatível (Req. 1.7, 2.2, 16.4, 16.5).
- **Resultado esperado:** o tópico lista três assinaturas com **Status: Confirmed** e a coluna de **Redrive policy** preenchida. Ao final, há **seis** assinaturas no total.

### Etapa 8 — Criar a IAM_Role_EC2 (privilégios mínimos, sem Access Keys)

1. Abra o serviço **IAM** → **Policies** → **Create policy** → aba **JSON** e cole a policy abaixo, substituindo `<account-id>`:

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
      "Sid": "ConsultarAssinaturas",
      "Effect": "Allow",
      "Action": "sns:ListSubscriptionsByTopic",
      "Resource": [
        "arn:aws:sns:us-east-1:<account-id>:delivery-standard",
        "arn:aws:sns:us-east-1:<account-id>:delivery-fifo.fifo"
      ]
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

2. Nomeie a policy como `sns-delivery-lab-policy` e clique em **Create policy**.
3. Vá em **IAM** → **Roles** → **Create role**.
4. Em **Trusted entity type**, selecione **AWS service**; em **Use case**, selecione **EC2**. Avance.
5. Anexe duas policies: a `sns-delivery-lab-policy` (criada acima) e a policy gerenciada **`AmazonSSMManagedInstanceCore`** (necessária para o Session Manager).
6. Nomeie a role como `sns-delivery-lab-ec2-role` e clique em **Create role**.

- **O que faz:** cria uma IAM Role com os privilégios mínimos — publicar nos dois tópicos (`sns:Publish`), listar assinaturas (`sns:ListSubscriptionsByTopic`), ler filas e DLQs (`sqs:ReceiveMessage`, `sqs:GetQueueAttributes`, `sqs:GetQueueUrl`) e ajustar temporariamente a Access_Policy_Fila do cenário de DLQ (`sqs:SetQueueAttributes`) — além de habilitar o Session Manager.
- **Por que:** a aplicação se autentica na AWS exclusivamente por essa role (credenciais temporárias via IMDSv2), sem Access Keys fixas, e com acesso restrito aos recursos do laboratório (Req. 12.1, 12.2, 12.3, 16.6). A policy **não** concede `sqs:DeleteMessage` porque a leitura é sempre não destrutiva.
- **Resultado esperado:** a role `sns-delivery-lab-ec2-role` aparece em **IAM** → **Roles** com as duas policies anexadas.

### Etapa 9 — Criar os Security Groups (porta 22 fechada)

1. Abra **EC2** → **Security Groups** → **Create security group**, na mesma VPC em que a EC2 será criada.
2. **Name:** `sns-delivery-lab-sg`. **Description:** `Dashboard SNS Delivery Lab`.
3. **Inbound rules** — adicione **apenas** a porta da aplicação, restrita às origens autorizadas:
   - Type **Custom TCP**, Port **8000**, Source: o **seu IP** (`My IP`) ou a faixa das origens autorizadas. **Não** use `0.0.0.0/0`.
4. **Não** adicione regra para a porta **22 (SSH)**. A porta 22 permanece sem regra de entrada.
5. **Outbound rules:** mantenha o padrão (saída liberada), necessário para a EC2 alcançar os endpoints da AWS (SNS, SQS, Systems Manager) e instalar pacotes.
6. Clique em **Create security group**.

- **O que faz:** restringe o acesso de entrada à porta da aplicação (8000) e mantém a porta 22 (SSH) fechada.
- **Por que:** o acesso administrativo à EC2 é feito exclusivamente via Session Manager, dispensando SSH; expor a porta 22 seria desnecessário e inseguro (Req. 12.7, 15.3, 16.7).
- **Resultado esperado:** o Security Group lista somente a regra de entrada da porta 8000 restrita; nenhuma regra para a porta 22.

### Etapa 10 — Criar a instância EC2 Linux com Session Manager

1. Abra **EC2** → **Instances** → **Launch instances**, região **us-east-1**.
2. **Name:** `sns-delivery-lab`.
3. **AMI:** **Amazon Linux 2023** (já inclui o agente do Systems Manager).
4. **Instance type:** `t3.micro` (dentro do nível gratuito elegível; suficiente para o laboratório).
5. **Key pair:** selecione **Proceed without a key pair** (não é necessário par de chaves, pois o acesso é via Session Manager).
6. **Network settings:** selecione a VPC/sub-rede pública e, em **Firewall (security groups)**, selecione **Select existing security group** → `sns-delivery-lab-sg`.
7. **Advanced details** → **IAM instance profile:** selecione `sns-delivery-lab-ec2-role`.
8. Clique em **Launch instance**.

- **O que faz:** cria a instância Linux que hospeda a API_Backend, o Verificador_Entrega e o Dashboard, já com a IAM Role anexada e sem par de chaves SSH.
- **Por que:** a aplicação roda inteiramente na EC2 e usa a IAM Role anexada para autenticar no SNS/SQS; a administração ocorre via Session Manager, sem SSH (Req. 15.3, 16.7).
- **Resultado esperado:** a instância `sns-delivery-lab` fica com **Instance state: Running**. Anote o **Instance ID** (`i-...`). Após alguns minutos, em **EC2** → selecione a instância → **Connect** → aba **Session Manager**, o botão **Connect** fica habilitado, confirmando que o agente SSM registrou a instância.

### Etapa 11 — Instalar e executar a aplicação na EC2

Conecte-se à instância pelo **Session Manager** (**EC2** → instância → **Connect** → **Session Manager** → **Connect**). Os comandos abaixo são executados no terminal aberto no navegador.

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
- **Por que:** isolar as dependências evita conflitos com pacotes do sistema; o `boto3` resolverá as credenciais da IAM Role automaticamente.
- **Resultado esperado:** `pip` conclui sem erros; `pip show boto3` exibe a versão instalada.

4. Configurar as variáveis de ambiente da aplicação (nenhum segredo da AWS é definido aqui — a autenticação é via IAM Role):

```bash
export DASHBOARD_SNS_USUARIO="admin"
export DASHBOARD_SNS_SENHA="defina-uma-senha-forte"
export DASHBOARD_SNS_ORIGENS_AUTORIZADAS="<SEU_IP>"
export SNS_LAB_IAM_ROLE="sns-delivery-lab-ec2-role"
export SNS_LAB_EC2_INSTANCE_ID="<INSTANCE_ID>"
```

- **O que faz:** define usuário/senha do Dashboard, a lista de origens (IPs) autorizadas a fazer login e os identificadores da IAM Role e da instância usados na verificação de inicialização.
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

> **Execução permanente (opcional).** Para manter a aplicação ativa após fechar a sessão, crie um serviço `systemd` com `ExecStart` apontando para o `uvicorn` do ambiente virtual e as variáveis no bloco `Environment=`, e habilite com `sudo systemctl enable --now sns-delivery-lab`. Assim o processo reinicia automaticamente e não depende do terminal do Session Manager.

---

## 4. Verificação pós-implantação

Confirme que cada recurso foi criado com os nomes e os valores de Config_Aplicada previstos.

| # | Verificação | Onde conferir | Resultado esperado |
|---|---|---|---|
| 1 | Topico_Standard | SNS → Topics → `delivery-standard` | Type **Standard** |
| 2 | Topico_FIFO + dedup | SNS → Topics → `delivery-fifo.fifo` | Type **FIFO**, **Content-based deduplication: Enabled** |
| 3 | Seis filas de destino | SQS → lista | `delivery-destino1/2/3-standard` e `delivery-destino1/2/3-fifo.fifo` presentes |
| 4 | Duas DLQs | SQS → lista | `delivery-sns-dlq-standard` e `delivery-sns-dlq.fifo` presentes |
| 5 | Access_Policy_Fila | SQS → cada fila → **Access policy** | Statement `Allow` para `sns.amazonaws.com` com condição por `SourceArn` do tópico |
| 6 | Seis assinaturas + Redrive | SNS → cada tópico → **Subscriptions** | 3 por tópico, **Confirmed**, com Redrive policy apontando para a DLQ compatível |
| 7 | IAM_Role_EC2 | IAM → Roles → `sns-delivery-lab-ec2-role` | `sns-delivery-lab-policy` + `AmazonSSMManagedInstanceCore`; sem Access Keys |
| 8 | Security Group | EC2 → Security Groups → `sns-delivery-lab-sg` | Entrada só na porta 8000 restrita; **sem** porta 22 |
| 9 | Instância EC2 | EC2 → Instances → `sns-delivery-lab` | **Running**, com a IAM Role anexada e Session Manager disponível |
| 10 | Verificação automática | Dashboard em `http://<IP>:8000/` ou `GET /api/saude` | Dashboard carrega; `/api/saude` indica todos os recursos acessíveis |

Se o endpoint `GET /api/saude` ou o Dashboard apontar um recurso indisponível, ele é identificado por **nome e tipo** em pt-BR — use essa indicação para localizar a etapa correspondente e corrigir.

---

## 5. Tratamento de falhas de etapa

Se um passo não puder ser concluído por **recurso ausente**, **permissão insuficiente** ou **valor de configuração divergente**, identifique a causa e corrija **antes** de prosseguir para o passo seguinte.

| Sintoma | Causa provável | Como identificar | Como corrigir | Como validar |
|---|---|---|---|---|
| Console não permite habilitar FIFO | Nome do recurso FIFO sem o sufixo `.fifo` | A opção FIFO fica indisponível ao digitar o nome | Recriar o tópico/fila com o nome terminando em `.fifo` | O recurso aparece com **Type: FIFO** |
| Assinatura fica em **PendingConfirmation** ou mensagem não chega à fila | `Access_Policy_Fila` ausente ou com `SourceArn` incorreto | SQS → fila → **Access policy**: statement ausente ou com ARN de outro tópico | Refazer a Etapa 5 com o ARN correto do tópico | Após um disparo, a mensagem aparece na fila de destino |
| Mensagem não vai para a DLQ no teste de DLQ | DLQ sem autorização ao SNS ou Redrive_Policy_SNS não configurada | SQS → DLQ → **Access policy**; SNS → assinatura → **Redrive policy** | Refazer as Etapas 6 e 7 na assinatura/DLQ compatível | Teste de DLQ confirma a mensagem na DLQ compatível |
| Aplicação responde `HTTP 503` ao iniciar | Verificação de inicialização encontrou recurso ausente/inacessível | O corpo da resposta (e o log) identifica o recurso por **nome e tipo** em pt-BR | Criar/corrigir o recurso indicado (nome, tipo, região) | Reiniciar o `uvicorn`; o Dashboard passa a ser servido |
| `AccessDenied` / `AuthorizationError` nos logs | IAM Role sem a ação necessária ou não anexada à EC2 | Log do boto3 cita a ação negada (ex.: `sns:Publish`) | Ajustar `sns-delivery-lab-policy` (Etapa 8) e confirmar o Instance Profile na EC2 | A operação (publicar/ler) passa a funcionar |
| Session Manager não conecta | Falta `AmazonSSMManagedInstanceCore` ou sem rota de saída | EC2 → Connect → Session Manager com **Connect** desabilitado | Anexar a policy SSM à role (Etapa 8); garantir saída de rede (Etapa 9) | O botão **Connect** do Session Manager fica habilitado |
| Dashboard não abre no navegador | Porta 8000 fechada ou origem não autorizada | Timeout no navegador; `DASHBOARD_SNS_ORIGENS_AUTORIZADAS` sem o IP | Liberar a porta 8000 só para a origem (Etapa 9) e incluir o IP na env (Etapa 11.4) | O login do Dashboard é exibido |
| Login sempre bloqueado | Nenhuma origem autorizada configurada | Aviso de segurança em pt-BR no log de inicialização | Definir `DASHBOARD_SNS_ORIGENS_AUTORIZADAS` com o IP (ou `=*` apenas para teste) e reiniciar | O login passa a aceitar as credenciais |

---

## 6. Custo mensal estimado em USD

Valores aproximados para a região **us-east-1**, considerando o uso **didático e de baixo volume** deste laboratório. Servem como estimativa de ordem de grandeza; os preços oficiais devem ser confirmados na calculadora e na página de preços da AWS.

| Recurso | Premissa de uso | Custo mensal estimado (USD) |
|---|---|---|
| EC2 `t3.micro` (Amazon Linux 2023) | 1 instância; nível gratuito elegível nos primeiros 12 meses; fora do nível gratuito, ~730 h/mês sob demanda | ~US$ 0 (nível gratuito) ou ~US$ 7–8 |
| Volume EBS `gp3` 8 GB | disco raiz da EC2 | ~US$ 0,64 |
| Amazon SNS | publicações do laboratório (dezenas a centenas de mensagens/mês); primeiras 1.000.000 publicações gratuitas | ~US$ 0 |
| Amazon SQS (6 filas de destino + 2 DLQs) | leituras com Long Polling e poucos disparos; primeiras 1.000.000 requisições gratuitas | ~US$ 0 |
| IAM, Security Group, Session Manager | sem custo próprio | US$ 0 |
| Transferência de dados de saída | tráfego mínimo do Dashboard; primeiros 100 GB/mês gratuitos | ~US$ 0 |
| **Total estimado** | laboratório ligado apenas durante os testes | **~US$ 0 a ~US$ 8–9 / mês** |

Observações que reduzem o custo:
- A arquitetura **não** usa **NAT Gateway** nem **Elastic Load Balancer** (os maiores custos fixos típicos), conforme Req. 15.1 e 15.2.
- **Pare ou encerre a instância EC2** quando não estiver usando o laboratório — é o item que mais influencia o custo fora do nível gratuito.

---

## 7. Exclusão dos recursos ao final (ordem de dependência)

Ao encerrar o laboratório, remova **todos** os recursos abaixo. Siga a ordem indicada: ela respeita as dependências (assinaturas dependem de tópicos e filas; a instância depende da role e do security group).

| Ordem | Recurso | Nome real | Onde excluir | Observação de dependência |
|---|---|---|---|---|
| 1 | Assinatura_SNS (as seis) | 3 do `delivery-standard` + 3 do `delivery-fifo.fifo` | SNS → Subscriptions → **Delete** | Remover antes dos tópicos e das filas |
| 2 | Topico_Standard | `delivery-standard` | SNS → Topics → **Delete** | — |
| 3 | Topico_FIFO | `delivery-fifo.fifo` | SNS → Topics → **Delete** | — |
| 4 | Fila_Destino_Standard (3) | `delivery-destino1/2/3-standard` | SQS → **Delete** | Após remover as assinaturas |
| 5 | Fila_Destino_FIFO (3) | `delivery-destino1/2/3-fifo.fifo` | SQS → **Delete** | Após remover as assinaturas |
| 6 | DLQ_SNS_Standard | `delivery-sns-dlq-standard` | SQS → **Delete** | Após remover as assinaturas |
| 7 | DLQ_SNS_FIFO | `delivery-sns-dlq.fifo` | SQS → **Delete** | Após remover as assinaturas |
| 8 | Instância EC2 | `sns-delivery-lab` | EC2 → Instances → **Terminate** | Libera a IAM Role anexada e o volume EBS raiz |
| 9 | Security Group | `sns-delivery-lab-sg` | EC2 → Security Groups → **Delete** | Só é possível após terminar a instância |
| 10 | IAM Role | `sns-delivery-lab-ec2-role` | IAM → Roles → **Delete** | Após terminar a instância que a usava |
| 11 | IAM Policy | `sns-delivery-lab-policy` | IAM → Policies → **Delete** | Após excluir a role que a referenciava |

Após executar a exclusão, **confirme** que nenhum recurso da lista permanece ativo (reveja as listas de SNS, SQS, EC2 e IAM). Se algum recurso remanescer, identifique-o pelo nome/identificador e repita a exclusão correspondente, respeitando a ordem acima.
