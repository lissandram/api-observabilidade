# Projeto de Observabilidade com a Stack Elastic e Node.js

Este repositório contém o código-fonte, scripts de orquestração e configurações para a implantação de um **Projeto Básico de Observabilidade** utilizando a **Stack Elastic** (Elasticsearch, Kibana e APM Server) para monitoramento de uma API REST desenvolvida em Node.js/Express.

> **Contexto Acadêmico:** Trabalho prático e artigo técnico desenvolvido para a disciplina de **Gerenciamento e Monitoramento de Aplicações e Infraestrutura** do curso de Especialização em Engenharia DevOps — **Instituto Federal de Mato Grosso (IFMT)**.

---

## Arquitetura da Solução

O diagrama abaixo ilustra a arquitetura do ambiente conteinerizado via Docker Compose no WSL2 e o fluxo de telemetria entre a aplicação Node.js, o APM Server, o Elasticsearch e o Kibana:

![Arquitetura da Solução](arquitetura_ferramenta.png)

---

## Estrutura do Repositório

O projeto está organized nos seguintes diretórios e arquivos principais:

```bash
.
├── api/                     # Código-fonte da API REST em Node.js/Express
│   ├── server.js            # Entrypoint da aplicação e inicialização do Agente APM
│   ├── package.json         # Dependências (express, elastic-apm-node, winston, etc.)
│   └── ...
├── elastic-stack/           # Módulo de infraestrutura e orquestração dos containers
│   ├── docker-compose.yml   # Especificação dos serviços (Elasticsearch, Kibana, APM Server)
│   └── ...
├── arquitetura_ferramenta.png # Diagrama de arquitetura da solução
└── README.md                # Documentação e guia de execução do projeto
```

## Tecnologias Utilizadas

- **Aplicação:** Node.js (v18.19) com Express framework.
- **Agente de Telemetria:** `elastic-apm-node` (v4.18.0) no padrão ECS (*Elastic Common Schema* v8.10.0).
- **Stack de Observabilidade:** Elastic Stack (v8.12.2)
  - **Elasticsearch:** Armazenamento, indexação distribuída e busca em séries temporais (Porta `9200`).
  - **Elastic APM Server:** Ingestão, conversão e processamento de traces, métricas e exceções (Porta `8200`).
  - **Kibana:** Dashboards analíticos, consultas KQL e visualização de percentis via Kibana Lens (Porta `5601`).
- **Orquestração & Virtualização:** Docker Engine, Docker Compose no ambiente **WSL2** (Ubuntu 22.04 LTS).
- **Gerador de Carga:** Utilitário `autocannon` para simulação de requisições HTTP concorrentes.

---

## Endpoints da API para Testes de Observabilidade

A API disponibiliza rotas simuladas para exercitar a captura de telemetria pelo agente APM:

| Rota | Método | Descrição / Comportamento Esperado | Status |
| :--- | :---: | :--- | :---: |
| `/api/sucesso` | `GET` | Transação padrão com resposta rápida de baixa latência. | `200 OK` |
| `/api/lento` | `GET` | Simula gargalo de banco de dados/integração via span manual de **1,5 s (1.500 ms)**. | `200 OK` |
| `/api/erro` | `GET` | Simula falha de regra de negócio reportada via `captureError` com *stack trace*. | `500 Internal Error` |

---

## Como Executar o Projeto

### Pré-requisitos
- Docker Engine & Docker Compose instalados (recomendado via WSL2 em ambiente Windows ou Linux com Ubuntu 24 ou superior).
- Node.js (v18+) e NPM instalados.

### 1. Subir a Infraestrutura de Observabilidade (Stack Elastic)
Navegue até o diretório `elastic-stack` e inicie os containers:

```bash
cd elastic-stack
docker compose up -d
```

---
## Validação dos Serviços
Após a execução, confirme a saúde dos serviços acessando as URLs:
- Elasticsearch (Status cluster/motor de busca): http://localhost:9200/

- Kibana Lens / Dashboards: http://localhost:5601/app/lens

Status dos Containers: Execute docker compose ps para garantir que os três containers estão em estado Up.
Observação: Aguarde pelo menos de 3 a 5 min para testar a execução das Urls.

---
## Iniciar a API Node.js

Em um novo terminal, navegue até a pasta api, instale as dependências e execute o servidor:

```bash
cd api
npm install
node server.js
```

Ao iniciar, o console exibirá o log do agente elastic-apm-node atestando a conexão com o APM Server (http://localhost:8200) e a pronta escuta na porta 3000.

---
## Simulação de Carga (Testes de Desempenho)

Para gerar tráfego e popular os dashboards do Kibana Lens com métricas de throughput, percentis de latência ($p50, p90, p95, p99$) e gráficos de falhas, utilize o utilitário autocannon:

```bash
# Instalar o Autocannon globalmente (caso não possua)
npm install -g autocannon

# Teste de carga na rota de erro (10 conexões concorrentes, 1.000 requisições)
autocannon -c 10 -a 1000 http://localhost:3000/api/erro

# Teste de carga na rota com gargalo de latência
autocannon -c 5 -d 30 http://localhost:3000/api/lento
```

---
## Visualização dos Dados no Kibana
Acesse o Kibana diretamente no Lens: http://localhost:5601/app/lens ou navegue até Analytics > Dashboards. é possível criar dashboards personalizados para validar o experimento.