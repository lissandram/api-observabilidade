const apm = require('elastic-apm-node').start({
  serviceName: 'api-teste-observabilidade',
  serverUrl: 'http://localhost:8200', // Endereço do APM Server
  environment: 'development',
  active: true
});

const express = require('express');
const winston = require('winston');

const app = express();
app.use(express.json());

// 2. CONFIGURAÇÃO DE LOGS ESTRUTURADOS (Winston em JSON)
const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  transports: [
    new winston.transports.Console()
  ]
});

// Middleware para registrar logs de cada requisição e associar ao APM
app.use((req, res, next) => {
  const traceId = apm.currentTraceId;
  logger.info(`Requisição recebida: ${req.method} ${req.url}`, {
    http_method: req.method,
    url: req.url,
    trace_id: traceId
  });
  next();
});

// 3. ROTAS DE TESTE PARA OBSERVABILIDADE

// Rota 1: Sucesso simples (Métricas + Trace limpo)
app.get('/api/sucesso', (req, res) => {
  res.status(200).json({ status: 'ok', mensagem: 'Operação realizada com sucesso!' });
});

// Rota 2: Simulação de Latência/Lentidão (Ver Spans no APM)
app.get('/api/lento', async (req, res) => {
  // Criando um Span manual para simular uma consulta ao Banco de Dados
  const span = apm.startSpan('consulta_banco_dados_ficticio');
  
  await new Promise((resolve) => setTimeout(resolve, 1500)); // Espera 1.5s
  
  if (span) span.end();
  
  res.status(200).json({ status: 'ok', tempo: '1.5s' });
});

// Rota 3: Simulação de Erro Não Tratado (500) (Exceções + Erros no APM)
app.get('/api/erro', (req, res, next) => {
  try {
    throw new Error('Falha crítica no processamento da regra de negócio!');
  } catch (err) {
    logger.error('Erro interno capturado na rota de teste', {
      error_message: err.message,
      trace_id: apm.currentTraceId
    });
    // Notifica o Elastic APM manualmente
    apm.captureError(err);
    res.status(500).json({ erro: err.message });
  }
});

// Rota Raiz (Página Inicial)
app.get('/', (req, res) => {
  res.send('API de Teste de Observabilidade está online!');
});

// 4. INICIALIZAÇÃO DO SERVIDOR
const PORT = 3000;
app.listen(PORT, () => {
  logger.info(`API de teste rodando na porta ${PORT}`);
});