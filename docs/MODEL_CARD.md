# Model Card — `onset-rf-v1`

## Identificação

- **Nome:** classificador de onset efetivo (`onset-rf-v1`) + fallback
  heurístico (`heuristic-v0`).
- **Tipo:** Random Forest de classificação binária (scikit-learn).
- **Versão:** 0.3.0 (Fase 2 integrada).
- **Data:** novembro de 2026.
- **Projeto:** TerraPulse AI · Assistente de Plantio (NASA Space Apps Challenge,
  equipa GRUTA).

## Descrição

Prevê a probabilidade de um **onset efetivo da época chuvosa nos próximos 21
dias** (`effective_onset_next_21d`), a partir da série IMERG diária de Manica.
O rótulo é gerado pela regra de onset documentada em `docs/METODOLOGIA.md`
(rotulagem fraca). Quando existe um modelo treinado em `data/models`, a
decisão (`app/services/decision.py`) usa a probabilidade do modelo; quando não
existe (ou a última janela de features está incompleta), o motor mantém a
heurística da Fase 0 com o mesmo contrato de saída.

## Algoritmo

- `sklearn.ensemble.RandomForestClassifier`
- `n_estimators=150`, `max_depth=8`, `min_samples_leaf=5`,
  `class_weight="balanced_subsample"`, `random_state=42`
- 10 features: mês, dia da época, seno/cosseno do dia do ano, chuva
  acumulada 3/7/14/30 dias, dias secos em 7 dias, cobertura IMERG média 30 dias
- Split temporal por época chuvosa (60/20/20) para evitar fuga temporal

## Uso pretendido

- Apoio à decisão de plantio de milho de sequeiro no distrito de Manica.
- Demonstração do fluxo completo TerraPulse AI (Fase 2).
- Base para validação de campo.

## Treino e persistência

- **Auto-treino no arranque** quando não existe um modelo treinado com dados
  reais (`AUTO_TRAIN_MODEL`, por omissão ativo); um modelo legado sem
  `data_status="real"` é ignorado e substituído. Pode ser desativado por
  variável de ambiente.
- O treino aceita exclusivamente `imerg_early_daily` e `imerg_final_daily`;
  falha explicitamente quando não há dados reais ou épocas completas
  suficientes.
- **CLI:** `flask train` (usa o modelo existente) / `flask train --force`
  (re-treina).
- **API:** `POST /api/admin/train` devolve o registo de treino com métricas de
  validação/teste (409 quando os dados são insuficientes).
- Modelo + metadata (versão, data, métricas) num único ficheiro
  `data/models/onset_rf.joblib`, gravado atomicamente.

## Fora de âmbito

- Outras culturas, regiões ou sistemas de rega.
- Aconselhamento agrícola oficial, crédito, seguro ou compensação.
- Substituir a observação local do agricultor.
- Previsão de quantidade de chuva (apenas probabilidade de onset).

## Entradas

- Série diária de precipitação (mm/dia), cobertura IMERG (%) e data
  (`app/models.py::DailyObservation`).
- Calendário agronómico: época de 1 de outubro a 31 de março.

## Saídas (no contrato da decisão)

- `probabilities.onset_21d`: probabilidade do modelo (nulo se sem modelo).
- `model_version`: `onset-rf-v1` quando o modelo informa a decisão;
  `heuristic-v0` no fallback.
- Nova razão `ml_onset_prob` na lista de `reasons`.
- Estado `PLANT_IN_DAYS` pode ser derivado do modelo quando
  `onset_21d >= 0.75` e não há onset em curso.

## Avaliação

- Métricas de holdout (accuracy, precision, recall, F1, ROC-AUC) reportadas no
  registo de treino e visíveis via `flask train` / `/api/admin/train`.
- As métricas disponíveis são calculadas apenas com observações IMERG reais.
  Continuam a medir rótulos fracos derivados da regra de onset, não sucesso da
  sementeira nem habilidade preditiva validada em campo.
- Rotulagem fraca: o rótulo deriva da mesma regra que a heurística; a vantagem
  esperada do modelo é capturar interações entre acumulados, cobertura e
  calendário que as regras fixas não modelam.

## Riscos e mitigações

| Risco | Mitigação |
| --- | --- |
| Falso positivo (plantar cedo e perder semente) | Estado `HIGH_RISK` conservador; limiar alto (≥ 0.75) para antecipar plantio |
| Rótulos fracos herdarem enviesamentos da regra | Documentado; validação com pluviómetros e produtores na Fase 3 |
| Modelo legado treinado com dados sintéticos/mistos | O treino e a inferência rejeitam modelos cujo `data_status` não seja `real` |
| Modelo corrupto/desatualizado | `load_active_model` ignora ficheiros inválidos e cai na heurística |
| Janela de features incompleta (fim de série) | `build_inference_frame` devolve nulo → fallback heurístico |
| Traduções inadequadas | Fallback para português; revisão nativa obrigatória |
| Excesso de confiança na probabilidade | Nota explícita de que não é probabilidade calibrada |

## Considerações éticas

- A aplicação deve ser **conservadora**: é preferível esperar do que induzir a
  perda de semente.
- O modelo não substitui a regra de falso onset em curso: `HIGH_RISK` tem
  prioridade sobre a probabilidade do modelo.
- Não recolhe dados pessoais nesta fase.

## Manutenção

- Treino: `app/services/training.py`; features: `app/ml/training_data.py`;
  algoritmo: `app/ml/classifier.py`; persistência: `app/ml/persistence.py`.
- Integração na decisão: `app/services/decision.py::_model_onset_probability`.
- Limiares agronómicos: `app/config.py`.
- Testes: `tests/test_model_training.py`, `tests/test_classifier.py`,
  `tests/test_training_data.py`, `tests/test_onset.py`.
- Revisão obrigatória antes de qualquer uso em campo: agronomia, dados e
  línguas.
