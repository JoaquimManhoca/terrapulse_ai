# TerraPulse AI · Assistente de Plantio

Ajuda agricultores do distrito de Manica (província de Manica, Moçambique) a
decidir **quando semear milho**, combinando observações de precipitação da NASA
(GPM IMERG) com previsão de curto prazo e regras agronómicas explicáveis.

> **Estado: Fase 1 (em curso).** A aplicação usa apenas observações reais NASA
> GPM IMERG; dados de demonstração e o respetivo modelo foram removidos. A base
> local tem lacunas e a observação mais recente é de 13/11/2026. Não uses uma
> decisão sem validar a data e a cobertura dos dados nem sem validação de campo.

## O problema

Em Manica a chuva por vezes começa cedo e depois pára durante uma ou duas
semanas. Quem planta na primeira chuva perde a semente e tem de comprar outra.
A informação existe, mas não chega ao agricultor de forma simples, local e
utilizável. O TerraPulse AI responde a uma pergunta prática: **planto hoje ou
espero?**

## O que a aplicação faz

- **Hoje** — seletor de cidade e cultura e recomendação única: `Plantar agora`,
  `Esperar`, `Plantar em N dias` ou `Risco alto`, com confiança.
- **Plano de 30 dias** — 16 dias de previsão Open-Meteo e 14 dias de
  climatologia IMERG, com ações `Plantar`, `Preparar`, `Esperar` e `Monitorar`.
- **Confiança e origem dos dados** — fonte, cobertura, observações, histórico,
  previsão, modelo e o que mudaria a decisão.
- **Porquê** — todos os sinais da decisão, chuva dos últimos 14 dias,
  climatologia histórica e previsão.
- **Histórico** — totais mensais e anuais, origem dos dados e última atualização.
- **Feedback** — respostas de um toque guardadas com o contexto da decisão;
  resumo e exportação CSV disponíveis apenas pela CLI do servidor.
- **Sobre** — fontes, metodologia, limitações e atribuição.
- **PWA instalável** com cache offline do ecrã principal.
- **Leitura em voz alta** (Web Speech API).
- **Quatro línguas**: português e inglês (revistos), Chitewe e Sena
  (provisórias).

## Arranque rápido (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe run.py
```

Abrir <http://127.0.0.1:8000>. Numa instalação limpa, a base SQLite é criada
vazia em `data/terrapulse.db`; a aplicação não inventa nem preenche dias sem
observações reais. Para obter decisões, carrega primeiro dados IMERG.

Carregar grânulos reais IMERG (`.nc4`) colocados em `download-data/`:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data
```

A ingestão é idempotente por dia e substitui os registos desse dia pela
observação IMERG mais recente. Dias sem ficheiro permanecem sem observação.
Também está disponível em `POST /api/admin/ingest`.

> **Espaço em disco:** cada grânulo global ocupa ~29 MB (~10 GB por ano). Com
> ~16 GB livres em `E:`, descarregue por lotes e ingira antes de apagar, ou use
> o subconjunto da bbox de Manica. O passo a passo está em
> [docs/DADOS.md](docs/DADOS.md), incluindo o gerador de URLs
> `scripts/list_imerg_urls.py`.

Servidor local de produção:

```powershell
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 run:app
```

Testes:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Configuração

As variáveis estão documentadas em `.env.example`. As principais:

| Variável | Default | Descrição |
| --- | --- | --- |
| `SECRET_KEY` | `dev-secret-change-me` | Chave local; na Vercel exige segredo de 32+ caracteres |
| `DATABASE_URL` | SQLite local | PostgreSQL persistente obrigatório na Vercel |
| `DEFAULT_REGION` | `manica` | Cidade inicial e fallback do seletor |
| `DEFAULT_CROP` | `milho` | Cultura inicial e fallback do seletor |
| `AUTO_TRAIN_MODEL` | `true` local / `false` Vercel | Treina apenas com IMERG real, quando há dados suficientes |
| `FORECAST_ENABLED` | `true` | Ativa a previsão Open-Meteo |
| `IMERG_DIR` | `<projeto>/download-data` | Pasta com os grânulos IMERG |
| `IMERG_PATTERN` | `*.nc4` | Padrão dos ficheiros a ingerir |
| `DECISION_DRY_DAY_MM` | `1.0` | Limiar de dia seco |
| `ONSET_WINDOW_DAYS` | `3` | Janela da regra de onset |
| `ONSET_THRESHOLD_MM` | `20.0` | Chuva mínima na janela |
| `ONSET_DRY_SPELL_DAYS` | `7` | Dias secos consecutivos que invalidam o onset |
| `ONSET_HORIZON_DAYS` | `21` | Horizonte de verificação do falso onset |
| `SEASON_START_MONTH` | `10` | Início da época das chuvas |

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/api/health` | Estado do serviço, nº de observações e origem dos dados |
| `GET` | `/api/decision` | Decisão atual completa (estado, razões, climatologia) |
| `GET` | `/api/history?days=90` | Série diária recente (1 a 3650 dias) |
| `GET` | `/api/climatology` | Totais mensais e anuais |
| `POST` | `/feedback` | Regista feedback sobre a decisão apresentada |
| `POST` | `/api/admin/ingest` | Lê `download-data/` e atualiza os dias IMERG |
| `POST` | `/api/admin/train` | Treina o modelo com observações IMERG reais |

Os endpoints `/api/admin/*` são locais; não são registados no runtime serverless
da Vercel.

O acesso ao resumo e à exportação de feedback é restrito à CLI do servidor:

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py feedback-summary
.\.venv\Scripts\python.exe -m flask --app run.py feedback-export --output feedback.csv
```

Uma repetição do mesmo envio (mesmo `submission_id`) é idempotente. Abrir uma
nova página gera um identificador novo, permitindo registar uma resposta nova
sem identificar o utilizador.

## Estrutura

```text
download-data/       grânulos NASA IMERG (.nc4) — ignorado no git
app/
  __init__.py        app factory e rotas web
  config.py          configuração e regras agronómicas
  i18n.py            catálogos PT / EN / Chitewe / Sena
  ml/onset.py        deteção de onset e falso onset
  services/          série diária, ingestão IMERG, previsão, decisão e treino real
  api/               endpoints REST
  templates/         ecrãs Jinja (Hoje, Porquê, Histórico, Sobre)
  static/            CSS, JS, manifest, service worker, ícones
data/
  raw/               (legado) grânulos NASA IMERG
  interim/           dados limpos intermédios
  processed/         séries prontas para treino
  models/            modelos treinados (Fase 2)
scripts/ingest_imerg.py ingestão manual de grânulos IMERG
scripts/list_imerg_urls.py lista de URLs GES DISC por período
tests/               pytest (dados auxiliares artificiais apenas para testes)
docs/                metodologia, dados, model card, línguas
```

## Fontes de dados

- **NASA GPM IMERG Early Daily** (`GPM_3IMERGDE`) e **Final Daily**
  (`GPM_3IMERGDF`), resolução de 0,1°, cobertura global desde 1998. Recorte de
  Manica: `32.69834, -19.13725, 33.17879, -18.70926`.
- **Open-Meteo** para previsão de precipitação até 16 dias (sem chave de API).
- **IMERG**: as observações carregadas usam `source="imerg_early_daily"` ou
  `source="imerg_final_daily"` e a média da bbox de Manica. Não há preenchimento
  sintético para dias em falta.

Atribuição: dados de precipitação cortesia da NASA GPM / GES DISC. A previsão
de curto prazo é fornecida pela Open-Meteo.

## Limitações atuais

- Cobertura real descontínua: a base local contém 6.680 observações IMERG
  (6.271 Final e 409 Early), entre 02/09/1998 e 13/11/2026. Há lacunas e os dados
  não representam necessariamente o tempo atual.
- Regra de onset heurística, ainda não calibrada com dados de campo de Manica.
- IMERG Early tem maior incerteza do que o Final Run; a escala de 0,1° não
  representa microclimas da machamba.
- Traduções Chitewe/Sena aguardam revisão de falantes nativos.
- Sem autenticação nem multi-utilizador; é um protótipo local.

## Próximos passos

1. **Fase 1 (em curso)** — descarregar 2–3 anos de IMERG para `download-data`,
   correr a ingestão, cobrir os dias em falta e comparar com pluviómetros e
   Open-Meteo.
2. **Fase 2** — modelos de onset (M1), risco de falso onset (M2) e análogos
   históricos (M3), com validação temporal e explicabilidade.
3. **Fase 3** — validação de campo com agricultores de Manica, revisão
   linguística e testes de usabilidade em telemóvel.

Ver [docs/METODOLOGIA.md](docs/METODOLOGIA.md),
[docs/DADOS.md](docs/DADOS.md), [docs/MODEL_CARD.md](docs/MODEL_CARD.md) e
[docs/LINGUAS.md](docs/LINGUAS.md).

## Deploy na Vercel

A aplicação tem configuração para deploy automático ao ligar o repositório
GitHub à Vercel. A Vercel não mantém ficheiros SQLite entre execuções; configura
uma base PostgreSQL persistente e segue [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md)
para configurar as variáveis e copiar para ela apenas observações IMERG reais.

## Aviso

Protótipo de investigação e demonstração. Não constitui aconselhamento agrícola
oficial nem substitui a observação local do agricultor.
