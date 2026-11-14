# Deploy na Vercel com GitHub

O projeto está configurado para a Vercel executar o Flask como uma Python
Function. Os ficheiros estáticos são publicados no CDN; a base local SQLite,
os modelos locais e as credenciais ficam fora do deploy.

## 1. Preparar o repositório

1. Envia as alterações para o GitHub.
2. Na Vercel, escolhe **Add New → Project** e importa o repositório.
3. Define **Root Directory** como a pasta que contém `vercel.json` e
   `requirements.txt` (no checkout deste projeto, `nassa-app2`).
4. Mantém o preset Flask/Python detetado automaticamente. O ponto de entrada é
   `index.py`, e `build_vercel.py` prepara os ficheiros em `public/`.

## 2. Configurar a base de dados e segredos

Cria uma base PostgreSQL persistente, por exemplo Neon através do Marketplace
da Vercel, e usa a URL de ligação com SSL. Em **Project → Settings →
Environment Variables**, adiciona para Preview e Production:

| Variável | Valor |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL do fornecedor (`postgresql://...`) |
| `SECRET_KEY` | Segredo aleatório com pelo menos 32 caracteres |
| `AUTO_TRAIN_MODEL` | `false` |
| `FORECAST_ENABLED` | `true` |

A aplicação converte `postgresql://` para o driver `psycopg`, desativa
prepared statements para compatibilidade com poolers em modo transaction e
recusa SQLite na Vercel. No Supabase, escolhe **Connect → Transaction pooler**
(porta `6543`) para as Functions e usa SSL (`sslmode=require`). Não coloques
URLs, palavras-passe nem `.env` no GitHub. A Vercel define automaticamente
`VERCEL=1`.

## 3. Copiar as observações reais

O ficheiro `data/terrapulse.db` é local e ignorado pelo Git, portanto não é
carregado para a Vercel. Para preencher a base PostgreSQL com as observações
reais existentes:

1. Na máquina que tem a base local, coloca a URL PostgreSQL no `.env` local
   como `DATABASE_URL=postgresql://...`.
2. Confirma o que será copiado:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sync_database.py --source data\terrapulse.db --dry-run
   ```

3. Copia os registos:

   ```powershell
   .\.venv\Scripts\python.exe scripts\sync_database.py --source data\terrapulse.db
   ```

O sincronizador é idempotente, copia exclusivamente `imerg_early_daily` e
`imerg_final_daily` e remove do destino registos de outras origens. Também cria
as tabelas necessárias. Não copia o modelo treinado localmente; na Vercel a
aplicação usa o fallback heurístico até existir um modelo preparado para esse
runtime.

## 4. Deploy e verificação

Faz push para o GitHub; a integração cria um Preview e publica Production após
o merge conforme as definições do projeto. Verifica:

- `/api/health`: `data_status` deve ser `real`, `synthetic_observations` deve
  ser `0` e `latest_observation` deve refletir a base importada.
- `/api/decision`: confirma `data_status`, `last_updated` e o modo do modelo.
- `/`: confirma o carregamento de CSS, ícones e service worker.

Os endpoints administrativos de ingestão/treino não são registados na Vercel:
ingestão Harmony usa threads e ficheiros locais, que não são duráveis em
Functions. Atualiza os dados a partir de uma máquina/worker persistente e volta
a executar o sincronizador.

**Antes de disponibilizar aconselhamento:** a base local atual tem observações
até 01/01/2026. Atualiza os dados IMERG; a aplicação exibe a data da última
observação para deixar explícita a cobertura temporal.
