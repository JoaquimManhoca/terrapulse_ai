# Dados IMERG — como descarregar

Guia para obter observações **NASA GPM IMERG Early Daily** (`GPM_3IMERGDE`,
`C2723754850-GES_DISC`) para o distrito de Manica e alimentar o TerraPulse AI.

## 0. Ingestão remota via API (recomendada — sem disco local)

O endpoint `POST /api/admin/ingest-harmony` descarrega o **IMERG Final Daily**
(`GPM_3IMERGDF`, V07, coleção `C2723754864-GES_DISC`) através da NASA **Harmony**,
que corta os dados **no servidor**: só a variável `precipitation`, só a bbox de
Manica, só épocas chuvosas completas. Cada época transfere poucas centenas de KB
(em vez de ~5,3 GB por época em grânulos globais) e é escrita diretamente na
base de dados; no fim, o classificador `onset-rf-v1` é retreinado
automaticamente.

Pré-requisitos (igual à secção 8): conta Earthdata Login autorizada para o GES
DISC, com `%USERPROFILE%\.netrc` (entrada `urs.earthdata.nasa.gov`) ou
`EARTHDATA_TOKEN` no ambiente. Nunca coloque credenciais no código.

Os endpoints `/api/admin/*` exigem o segredo `ADMIN_TOKEN` no cabeçalho
`X-Admin-Token` (sem ele respondem `401`; se `ADMIN_TOKEN` não estiver
configurado, respondem `503`).

```powershell
# 1. Iniciar a ingestão (corre em segundo plano)
curl.exe -X POST http://127.0.0.1:8000/api/admin/ingest-harmony ^
  -H "X-Admin-Token: $env:ADMIN_TOKEN"

# Opcional: limitar o intervalo (corpo JSON)
curl.exe -X POST http://127.0.0.1:8000/api/admin/ingest-harmony ^
  -H "X-Admin-Token: $env:ADMIN_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{\"start_date\": \"2023-06-01\", \"end_date\": \"2026-07-01\"}"

# 2. Consultar o progresso (épocas, dias, erros, retreino)
curl.exe http://127.0.0.1:8000/api/admin/ingest-harmony/status ^
  -H "X-Admin-Token: $env:ADMIN_TOKEN"
```

Notas operacionais:

- O intervalo por omissão é `1998-01-01` a `hoje - 120 dias`, e é **limitado
  (clamp) à cobertura real do arquivo** consultada via CMR — em novembro de
  2026, o IMERG Final V07 em `C2723754864` vai de 1998-01-01 a 2025-09-30,
  pelo que as épocas 1998–2024 (27 épocas) são ingiríveis. A época em curso
  (2025/26) não está ainda no IMERG Final; para operação recente use a
  atualização incremental de IMERG Early (secção 9) ou aguarde a publicação
  pela NASA.
- Só são pedidas épocas completas (1 out → 31 mar) com janelas de suporte
  (29 dias antes, 21 dias depois) dentro do intervalo limitado.
- Até 8 jobs Harmony correm em paralelo; cada época pode demorar vários
  minutos no servidor da NASA. O estado reporta `progress_pct`, dias
  `ingested`/`updated` e erros por época.
- Dias já existentes são **atualizados** com a observação real
  (`imerg_final_daily`); nenhum dia real é apagado.
- Épocas com dias em falta (`imerg_missing`) ficam excluídas do treino — o
  modelo só treina com séries diárias completas.
- No fim, o estado inclui `model_version` e as métricas holdout do retreino
  (`model_metrics`). Se os dados forem insuficientes, `model_error` indica a
  razão e a decisão continua em modo heurístico.
- Épocas distantes (antes de junho de 2000) não existem no IMERG: use
  `start_date >= 2000-06-01`.

## 1. Período e espaço em disco

Para o MVP de 2–3 anos, o período escolhido é **2023-10-01 a 2026-11-12**
(3 épocas completas + época atual):

| Opção | Dias | Tamanho aproximado (grânulos globais) |
| --- | ---: | ---: |
| Período contínuo | ~1139 | ~33 GB |
| Apenas época das chuvas (Out–Mar) | ~590 | ~17 GB |

Cada grânulo global tem ~29 MB. O disco `E:` tem ~16 GB livres, por isso:

- prefira o **subconjunto da bbox** (Opção A), que gera ficheiros muito pequenos;
- ou descarregue **uma época de cada vez**, ingira e apague os `.nc4` (Opção B).

O período mínimo para a climatologia de onset é Out–Mar. Os meses secos só são
necessários para os totais mensais/anuais do ecrã Histórico.

### Estado atual da pasta

Para completar automaticamente todos os dias em falta, incluindo a época em
curso, use a atualização incremental da secção 9. Os métodos manuais abaixo
continuam válidos para lotes controlados; os dias já existentes são atualizados
sem criar duplicados.

## 2. Pré-requisitos

1. Criar uma conta **Earthdata Login**: <https://urs.earthdata.nasa.gov/>.
2. Autorizar a aplicação **NASA GESDISC DATA ARCHIVE** em
   <https://urs.earthdata.nasa.gov/applications> (ou na primeira tentativa de
   download, quando o GES DISC pedir autorização).
3. Confirmar o produto:
   <https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDE_07/summary>.
4. Criar a pasta de destino:

```powershell
New-Item -ItemType Directory -Force -Path E:\code\nassa-app2\download-data
```

> `download-data/` está no `.gitignore`. Nunca é enviada para o Git.

## 3. Opção A — subconjunto da bbox (recomendada)

O subconjunto só descarrega a área de Manica, pelo que cada dia ocupa poucos
KB em vez de ~29 MB.

1. Abrir a página do produto e escolher **Subset / Get Data**.
2. Escolher **Get File Subsets using the GES DISC Subsetter**.
3. Preencher:
   - **Data inicial:** `2023-10-01`
   - **Data final:** `2026-11-12` (ou uma época de cada vez)
   - **Variável:** `precipitation`
   - **Bounding box:**
     - Norte: `-18.70926`
     - Sul: `-19.13725`
     - Oeste: `32.69834`
     - Leste: `33.17879`
   - **Formato:** NetCDF
4. Clicar em **Get Data** e descarregar os ficheiros para
   `E:\code\nassa-app2\download-data`.
5. Ingerir:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data
```

Os ficheiros do subsetter podem ter nomes diferentes dos grânulos originais e
podem conter um ou vários dias na dimensão `time`. O loader usa o atributo
`BeginDate` ou a coordenada `time` e processa cada dia do ficheiro, por isso os
nomes não importam. Se o subsetter gerar `.nc` em vez de `.nc4`:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data --pattern "*.nc"
```

Se o subsetter limitar o número de dias por pedido, faça um pedido por época
(Out–Mar) e ingira no fim de cada um.

## 4. Opção B — grânulos completos em lotes

### 4.1 Gerar a lista de URLs

```powershell
# Período contínuo (~1139 URLs)
.\.venv\Scripts\python.exe scripts\list_imerg_urls.py `
  --start 2023-10-01 --end 2026-11-12 --out urls-3seasons.txt

# Apenas épocas das chuvas (~590 URLs, recomendado para o disco)
.\.venv\Scripts\python.exe scripts\list_imerg_urls.py `
  --start 2023-10-01 --end 2026-11-12 --seasons-only --out urls-rainy.txt
```

As URLs seguem o padrão:

```text
https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDE.07/YYYY/MM/3B-DAY-E.MS.MRG.3IMERG.YYYYMMDD-S000000-E235959.V07B.nc4
```

### 4.2 Configurar o Earthdata Login para o `curl`

Criar `%USERPROFILE%\.netrc` (sem extensão) com:

```text
machine urs.earthdata.nasa.gov
  login O_SEU_UTILIZADOR
  password A_SUA_PASSWORD
```

Restringir as permissões:

```powershell
icacls "$env:USERPROFILE\.netrc" /inheritance:r /grant:r "${env:USERNAME}:(R)"
```

O `curl` usa este ficheiro para responder ao redirecionamento do Earthdata
Login. Evite passwords com espaços.

### 4.3 Descarregar um lote

Exemplo para uma época (Out–Mar). Ajuste `--start`/`--end` a cada lote:

```powershell
.\.venv\Scripts\python.exe scripts\list_imerg_urls.py `
  --start 2023-10-01 --end 2024-03-31 --out urls-batch.txt

$dest = "E:\code\nassa-app2\download-data"
Get-Content urls-batch.txt | ForEach-Object {
    $name = Split-Path $_ -Leaf
    $target = Join-Path $dest $name
    if (-not (Test-Path $target)) {
        curl.exe -L -C - --netrc-file "$env:USERPROFILE\.netrc" `
          --retry 5 --retry-delay 10 -o $target $_
    }
}
```

(`-L` segue o redirecionamento; `-C -` retoma downloads interrompidos.)

### 4.4 Ingerir e libertar espaço

```powershell
.\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data
```

Depois de a ingestão terminar sem erros, apague os grânulos do lote:

```powershell
Get-ChildItem download-data\*.nc4 | Remove-Item
```

A base de dados guarda apenas um valor diário por dia; os ficheiros brutos podem
ser descarregados outra vez. A ingestão é idempotente, por isso repetir um dia
não cria duplicados.

Lotes sugeridos:

| Lote | Período | Ficheiros aprox. | Espaço aprox. |
| --- | --- | ---: | ---: |
| 2023–24 | 2023-10-01 a 2024-03-31 | 183 | 5,3 GB |
| 2024–25 | 2024-10-01 a 2025-03-31 | 182 | 5,3 GB |
| 2025–26 | 2025-10-01 a 2026-03-31 | 182 | 5,3 GB |
| 2026–27 (parcial) | 2026-10-01 a 2026-11-12 | 43 | 1,3 GB |

Para o Histórico mensal/anual completo, repita o processo para os meses secos
(Abr–Set) ou use o subsetter da Opção A.

## 5. Verificação

1. Confirmar o número de dias reais:

```powershell
curl.exe http://127.0.0.1:8000/api/health
```

O campo `real_observations` deve crescer e `data_status` deve permanecer
`real`. `synthetic_observations` é mantido como verificação e deve ser zero.

2. Ver a cobertura da última ingestão:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data
```

O comando imprime `Ingested`, `updated`, `skipped` e `errors`, além do primeiro
e último dia.

3. Abrir **Hoje**, **Porquê** ou **Histórico** em <http://127.0.0.1:8000> e
   confirmar o badge de dados reais e a data da última observação.

## 6. Resolução de problemas

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| `401`/`403` | Conta sem autorização GES DISC | Autorizar “NASA GESDISC DATA ARCHIVE” |
| Ficheiro `.nc4` com HTML dentro | Redirecionamento de login | Usar `.netrc` com `--netrc-file` e `-L` |
| `.crdownload` ou ficheiro pequeno | Download interrompido | Apagar o parcial e repetir, ou `curl -C -` |
| `FileNotFoundError` | Pasta `download-data` ausente | Criar a pasta ou definir `IMERG_DIR` |
| Nenhum dia ingerido | Extensão diferente | Usar `--pattern "*.nc"` |
| Dia em falta | URL inexistente ou erro de rede | Confirmar a data e repetir o lote |
| `coverage_pct < 100` / `imerg_partial` | Células sem valor no grânulo | Verificar o ficheiro de origem; o dia é mantido com QC |
| `imerg_missing` | Nenhuma célula válida | Substituir o ficheiro ou marcar o dia como em falta |

Duplicados do mesmo dia são ignorados automaticamente; o loader prefere o
ficheiro sem sufixo `(1)`.

## 7. Atribuição

Dados de precipitação cortesia da **NASA GPM / GES DISC**, produto
**GPM_3IMERGDE** (IMERG Early Daily), DOI
[10.5067/GPM/IMERGDE/DAY/07](https://doi.org/10.5067/GPM/IMERGDE/DAY/07).

## 8. Preparar dados de treino via Harmony

O script `scripts/prepare_harmony_dataset.py` usa o cliente oficial Harmony-Py
para descarregar o **IMERG Final Daily** (`GPM_3IMERGDF`, V07), limitado à bbox
de Manica. Requer uma conta Earthdata Login autorizada para o GES DISC.

Configure as credenciais localmente, sem as colocar no código:

```text
machine urs.earthdata.nasa.gov
  login O_SEU_UTILIZADOR
  password A_SUA_PASSWORD
```

Guarde esse conteúdo em `%USERPROFILE%\.netrc`. Em alternativa, defina
`EARTHDATA_TOKEN` no ambiente ou `EARTHDATA_NETRC` com o caminho para o ficheiro
`.netrc`. Nunca partilhe o token ou a palavra-passe.

Execute:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_harmony_dataset.py
```

O resultado fica em `data/processed/harmony_onset/`:
`train.csv`, `validation.csv`, `test.csv` e `manifest.json`. A divisão é
cronológica por época chuvosa (aproximadamente 60/20/20), não aleatória. O
script exige pelo menos cinco épocas completas e só inclui dados IMERG; épocas
com dias em falta são excluídas. O alvo é um *proxy* de início eficaz das
chuvas, derivado da regra agronómica de onset existente — não representa sucesso
da sementeira nem produtividade observada.

## 9. Atualização incremental e agendamento

O comando abaixo descarrega o **IMERG Early Daily** em falta através do Harmony,
corta os dados para a bbox de Manica no servidor, grava no SQLite local,
retreina o modelo e sincroniza as observações reais com o PostgreSQL/Supabase
configurado em `DATABASE_URL`:

```powershell
.\.venv\Scripts\python.exe scripts\update_data.py --retrain
```

Por omissão começa no dia seguinte à última observação local e termina
ontem, mas nunca depois do último dia já publicado pela coleção Early. Se
ainda não existir um novo dia, o comando termina com sucesso sem alterar dados
nem modelo. Para um intervalo explícito:

```powershell
.\.venv\Scripts\python.exe scripts\update_data.py `
  --start 2025-10-01 --end 2026-11-13 --retrain
```

Opções úteis:

- `--no-sync` — atualiza só o SQLite, sem escrever no Supabase.
- `--dry-run` — mostra o intervalo e termina.
- `--chunk-days 31` — dias por job Harmony (por omissão 31).
- `--sqlite data\terrapulse.db` — base local a atualizar.

Garantias:

- Observações `imerg_final_daily` existentes **nunca** são substituídas por
  Early.
- O intervalo é limitado à cobertura real da coleção Early consultada via CMR;
  sem dias novos, a execução é um no-op bem-sucedido.
- A sincronização é idempotente e remove apenas linhas não-IMERG do destino.
- Se não houver dados suficientes para treinar, o modelo anterior é mantido e o
  aviso é registado.

Para agendar diariamente no Windows Task Scheduler:

```powershell
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\update_data.ps1`" --retrain" `
  -WorkingDirectory $PWD

Register-ScheduledTask `
  -TaskName "TerraPulse IMERG Update" `
  -Action $action `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 12:00) `
  -Description "Atualiza IMERG, retreina o modelo e sincroniza o Supabase."
```

A tarefa corre ao meio-dia para dar tempo ao CMR de publicar o dia anterior.
O wrapper escreve o registo em `data\update_data.log`. Confirme o resultado em
`/api/health` e na data das observações mostrada na aplicação.

