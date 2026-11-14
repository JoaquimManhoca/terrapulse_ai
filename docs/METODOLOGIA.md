# Metodologia — TerraPulse AI (Fase 1 em curso)

## 1. Âmbito

O TerraPulse AI responde a uma pergunta: **o agricultor de Manica deve semear
milho agora ou esperar?** A aplicação usa exclusivamente observações reais NASA
GPM IMERG para a série de precipitação. Dias sem observação permanecem em falta;
não são gerados nem tratados como chuva zero.

Região: distrito de Manica, província de Manica, Moçambique.
Cultura: milho de sequeiro.
Época: outubro a março.

## 2. Dados

### 2.1 Observações de satélite

- Produtos: **GPM IMERG Early Daily** (`GPM_3IMERGDE`,
  `C2723754850-GES_DISC`) e **Final Daily** (`GPM_3IMERGDF`,
  `C2723754864-GES_DISC`, V07).
- Variável: `precipitation`, em **mm/dia**.
- Resolução: 0,1° (~11 km).
- Período: 1998 até ao presente.
- Recorte de Manica: `lon 32.69834–33.17879`, `lat -19.13725–-18.70926`.
- Agregação: **média simples das células válidas da bbox** (até 5 × 4 = 20
  células). A cobertura é registada em `coverage_pct`.
- Controlo de qualidade (`qc_flag`): `imerg_bbox_mean` (todas as células
  válidas), `imerg_partial` (algumas células em falta) ou `imerg_missing`
  (nenhuma célula válida).
- Ingestão idempotente: um registo por dia, com origem
  `imerg_early_daily` ou `imerg_final_daily`. A observação real mais recente
  substitui o valor anterior desse dia. Um ficheiro pode conter um ou vários
  dias (dimensão `time`), como acontece com alguns resultados do subsetter.
- Download e ingestão: ver [DADOS.md](DADOS.md).

### 2.2 Previsão de curto prazo

- Open-Meteo, `precipitation_sum` e `precipitation_probability_max`.
- Horizonte: até 16 dias, dos quais os primeiros 14 são usados na decisão.
- Cache: 15 minutos. Sem rede, a decisão funciona só com o histórico.
- Regra visual do resumo diário: probabilidade de chuva **≥ 50%** mostra
  “Chuva”. Abaixo de 50%, um código/volume de precipitação é apresentado como
  “Nublado”, mantendo a percentagem visível; probabilidade baixa, por si só,
  não significa “Sol”. “Sol” continua a depender dos códigos WMO 0/1. O corte
  de 50% é uma regra de apresentação, não uma garantia meteorológica.

## 3. Definições

- **Dia seco**: precipitação diária inferior a `DECISION_DRY_DAY_MM`
  (default **1,0 mm**).
- **Janela de onset**: `ONSET_WINDOW_DAYS` dias consecutivos (default **3**)
  cuja soma é pelo menos `ONSET_THRESHOLD_MM` (default **20,0 mm**).
- **Época**: começa a 1 de outubro (`SEASON_START_MONTH=10`,
  `SEASON_START_DAY=1`).
- **Onset falso**: depois do onset, ocorre uma sequência de pelo menos
  `ONSET_DRY_SPELL_DAYS` dias secos consecutivos (default **7**) dentro de
  `ONSET_HORIZON_DAYS` dias (default **21**). Dias em falta quebram a
  sequência e nunca contam como secos.
- **Onset eficaz**: onset detetado que não é classificado como falso.
- **Evento recente**: o último onset candidato nos 30 dias anteriores à data
  mais recente da série, verificado com um horizonte mais curto (14 dias).

## 4. Regra de decisão (heurística v0 + modelo `onset-rf-v1`)

As regras são aplicadas por esta ordem:

| Prioridade | Condição | Estado | Confiança |
| --- | --- | --- | --- |
| 1 | Onset recente e (falso onset **ou** ≥ 5 dias secos consecutivos) | `HIGH_RISK` | 0,72–0,95 |
| 2 | Chuva nos últimos 7 dias ≥ 20 mm **e** seca atual ≤ 2 dias | `PLANT_NOW` | 0,60–0,90 |
| 2b | Modelo ML: `onset_21d ≥ 0,75` e sem onset em curso | `PLANT_IN_DAYS` | 0,60–0,90 |
| 3 | Previsão indica onset nos próximos 7 dias | `PLANT_IN_DAYS` | 0,65 |
| 4 | Chuva prevista para os próximos 7 dias ≥ 15 mm | `PLANT_IN_DAYS` | 0,60 |
| 5 | Abril a setembro (época seca) | `WAIT` | 0,80 |
| 6 | Sem evidência suficiente | `WAIT` | 0,55 |

A confiança é uma **heurística**, não uma probabilidade calibrada. Quando não
existe modelo treinado em `data/models/onset_rf.joblib` (ou a última janela de
features está incompleta), a regra 2b é ignorada e o motor fica em modo
heurístico puro; o campo `model_version` indica sempre o modo ativo.

## 5. Climatologia

Para cada época completa (onset + 21 dias dentro da série), calcula-se:

- taxa de onsets falsos;
- mediana, mínimo e máximo do dia do onset, medidos em dias desde 1 de outubro
  e apresentados como data (`dd/mm`).

Épocas incompletas são excluídas da climatologia, mas o evento recente é
avaliado separadamente.

## 6. Probabilidades apresentadas

- `onset_7d` (início eficaz nos próximos 7 dias): 0,90 se o evento recente não
  é falso; 0,75 se a previsão indica onset ≤ 7 dias; 0,60 se choveu ≥ 15 mm na
  última semana; 0,25 caso contrário.
- `onset_21d` (início eficaz nos próximos 21 dias): probabilidade do modelo
  `onset-rf-v1` para o dia mais recente da série; nulo quando não há modelo.
- `false_onset`: 0,90 se o evento recente é falso; caso contrário
  `max(0,05, taxa_histórica × 0,5)`. Sem evento, usa a taxa histórica ou 0,50.

Estes valores são indicativos e serão calibrados com dados de campo na Fase 3.

## 6a. Modelo ML (`onset-rf-v1`)

- **Algoritmo:** `RandomForestClassifier` (scikit-learn), 150 árvores,
  profundidade máxima 8, folha mínima 5, `class_weight="balanced_subsample"`.
- **Alvo:** `effective_onset_next_21d` — onset eficaz (não falso) nos 21 dias
  seguintes, rotulado pela regra da secção 3 (rotulagem fraca).
- **Features (10):** mês, dia da época, seno/cosseno do dia do ano, chuva
  acumulada 3/7/14/30 dias, dias secos em 7 dias, cobertura IMERG média 30 dias.
- **Split:** cronológico por época chuvosa (60/20/20); requer ≥ 5 épocas
  completas.
- **Treino:** usa apenas fontes `imerg_early_daily` e `imerg_final_daily`;
  registos de outras origens são excluídos. O treino automático no arranque e
  `flask train` só usam dados reais. `POST /api/admin/train` devolve o registo
  com métricas holdout (accuracy, precision, recall, F1, ROC-AUC).
- **Inferência:** a decisão usa `P(onset eficaz ≤ 21 dias)` do dia mais
  recente; o modelo + metadata vivem em `data/models/onset_rf.joblib`.
- Detalhes completos no `docs/MODEL_CARD.md`.

## 7. Limitações

- Cobertura IMERG descontínua: a base local tem 6.288 observações (6.271 Final
  e 17 Early), entre 02/09/1998 e 01/01/2026. Dias em falta limitam a decisão
  sobre condições atuais; a previsão Open-Meteo é uma fonte separada.
- IMERG Early tem maior erro do que o Final Run; o relevo de Manica e as
  chuvas convectivas aumentam a incerteza.
- 0,1° não representa microclimas da machamba.
- A regra de 20 mm/3 dias é um ponto de partida agronómico, não uma verdade
  local validada.
- A previsão de 14 dias tem incerteza crescente.
- Não há ainda validação com dados de campo nem com produtividade observada.

## 8. Validação planeada

1. Comparar IMERG com pluviómetros e registos locais.
2. Retrospetiva: para cada época, comparar a decisão da regra com o sucesso da
   sementeira (quando houver dados).
3. Testes de usabilidade e validação linguística com agricultores de Manica.
4. Calibração dos limiares por localidade e por variedade de milho.

### 8.1 Comparação preliminar (dezembro de 2025)

Os 17 dias IMERG Early ingeridos nesse período permitiram uma primeira
comparação, apenas exploratória, entre a média da bbox IMERG e o arquivo
Open-Meteo (modelo ERA5/IFS) no ponto de Manica:

| Data | IMERG bbox (mm/dia) | Open-Meteo (mm/dia) |
| --- | ---: | ---: |
| 2025-12-20 | 5,0 | 21,0 |
| 2025-12-21 | 21,8 | 32,0 |
| 2025-12-22 | 55,0 | 29,3 |
| 2025-12-23 | 36,9 | 38,7 |
| 2025-12-24 | 45,9 | 17,8 |
| 2025-12-25 | 9,2 | 48,1 |

As diferenças são grandes em vários dias. Isto é esperado: a célula IMERG é uma
média de 20 células de 0,1°, o Open-Meteo é um ponto de grelha e a chuva
convectiva varia muito no espaço. Esta comparação **não** é uma validação e não
foi usada para calibrar a regra; serve para orientar a recolha de pluviómetros
locais.

## 9. Reprodutibilidade

- Regras e limiares em `app/config.py`, configuráveis por `.env`.
- Testes automáticos cobrem onset, classificador, treino/persistência do
  modelo, decisão, API, ingestão IMERG (um ou vários dias por ficheiro), URLs
  GES DISC, i18n, seletor cidade/cultura e páginas. Os dados fabricados usados
  nos testes ficam isolados em `tests/data_fixtures.py` e nunca entram na base
  operacional.
- `flask train` treina e persiste o modelo `onset-rf-v1` exclusivamente a
  partir das observações IMERG reais da base de dados.
- `scripts/ingest_imerg.py --dir download-data` carrega os grânulos IMERG.
