# Deploy na Vercel com GitHub

O projeto está configurado para a Vercel executar o Flask como uma Python
Function. Os ficheiros estáticos são publicados no CDN; a base local SQLite,
os modelos locais e as credenciais ficam fora do deploy.

## 1. Rever o projeto existente

Se a aplicação já está publicada, **não cries outro projeto nem alteres o
domínio de produção**. Confirma primeiro o projeto Vercel, o repositório ligado,
o branch de produção e a pasta que contém `vercel.json` e `requirements.txt`.
Usa um deployment Preview para validar alterações antes de promover para
Production. Só importa o repositório em **Add New → Project** numa instalação
nova.

Mantém o preset Flask/Python detetado automaticamente. O ponto de entrada é
`index.py`, e `build_vercel.py` prepara os ficheiros em `public/`.

## 2. Confirmar a base de dados e os segredos

Se já existe uma base ligada à aplicação publicada, confirma o fornecedor,
host, pooler e variáveis no projeto Vercel; não substituas a ligação por uma
base nova. Numa instalação nova, cria uma base PostgreSQL persistente e usa a
URL de ligação com SSL. Em **Project → Settings → Environment Variables**,
confirma as variáveis para Preview e Production:

| Variável | Valor |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL do fornecedor (`postgresql://...`) |
| `SECRET_KEY` | Segredo aleatório com pelo menos 32 caracteres |
| `AUTO_TRAIN_MODEL` | `false` (não treina durante pedidos serverless) |
| `TRAIN_MODEL_AT_BUILD` | `false` (usa o artefacto real versionado) |
| `FORECAST_ENABLED` | `true` |

A aplicação converte `postgresql://` para o driver `psycopg`, desativa
prepared statements para compatibilidade com poolers em modo transaction,
força SSL em hosts Supabase e recusa SQLite na Vercel. Em Functions, o engine
usa um pool pequeno para reutilizar ligações sem esgotar o pooler. `DATABASE_URL`
e `SECRET_KEY` têm de estar disponíveis no runtime. `DATABASE_URL` só é
necessária também durante o build quando se ativa intencionalmente
`TRAIN_MODEL_AT_BUILD=true`.

> **Importante (Supabase):** `db.<ref>.supabase.co` só publica registos IPv6.
> A Vercel corre em IPv4, pelo que a ligação direta falha (DNS/host irresolúvel)
> e a aplicação responde `500 Internal Server Error`. Usa sempre o
> **Connect → Transaction pooler** (porta `6543`, IPv4), por exemplo:
>
> ```
> DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres?sslmode=require
> ```
>
> Em alternativa, mantém a URL direta e define
> `SUPABASE_POOLER_HOST=aws-1-<region>.pooler.supabase.com` para a aplicação
> reescrever o host automaticamente. Não coloques URLs, palavras-passe nem
> `.env` no GitHub. A Vercel define automaticamente `VERCEL=1`.

## 3. Copiar as observações reais

Esta etapa é apenas para a primeira configuração de uma base nova. Se a
aplicação já está em produção com dados persistidos, não repitas a cópia sem
primeiro comparar as bases e confirmar o destino.

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
as tabelas necessárias.

O comando de build (`python build_vercel.py`) valida o artefacto real
versionado, e a configuração inclui explicitamente
`data/models/onset_rf.joblib` na Function. Assim, um deploy normal não consulta
nem modifica a base nem retreina o modelo. Define
`TRAIN_MODEL_AT_BUILD=true` apenas num ciclo planeado de atualização do modelo,
com acesso à `DATABASE_URL` de Preview, dados IMERG suficientes e revisão do
artefacto e dos resultados antes de promover para Production. Um treino sem
dados adequados ou com erro faz o build falhar, em vez de publicar um modelo
inválido.

### Preparar a tabela de feedback

Esta versão acrescenta colunas opcionais à tabela de feedback; a atualização é
aditiva e mantém as respostas existentes. Para uma publicação segura:

1. Confirma que Preview usa uma base separada da Production e testa a migração
   primeiro na base de Preview.
2. Faz uma cópia de segurança da base Production e confirma que tens acesso a
   restaurá-la.
3. Só depois de o Preview passar os testes, executa a migração contra a base de
   Production antes de promover o código. Não uses `sync_database.py` para uma
   publicação que só altera a aplicação.

Executa a migração a partir de uma máquina de confiança, com `DATABASE_URL`
apontado explicitamente para a base a atualizar:

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py upgrade-feedback-schema
```

O comando cria a tabela de feedback se ainda não existir; caso contrário,
adiciona as colunas de idempotência e resultados de campo sem apagar respostas
anteriores. As colunas novas aceitam `NULL` para preservar registos antigos.
O acesso às respostas é feito pela CLI privada (`feedback-summary`,
`feedback-export` e `feedback-outcomes`), não por uma rota pública.

## 4. Preview e promoção

Não publiques diretamente a partir da máquina de desenvolvimento. Envia a
alteração para um branch/PR para criar um Preview; confirma que as variáveis de
Preview apontam para a base Preview correta. Verifica:

- `/api/health`: `data_status` deve ser `real`, `synthetic_observations` deve
  ser `0` e `latest_observation` deve refletir a base importada.
- `/api/decision`: confirma `data_status`, `last_updated` e
  `model_version=onset-rf-v1` (não `heuristic-v0`).
- `/`: confirma o carregamento de CSS, ícones e service worker.
- feedback normal e reporte de resultado após os 21 dias, sem usar a base
  Production para os testes.

Só promove para Production depois de confirmar o Preview, a migração e as
variáveis de ambiente do projeto existente. Os endpoints administrativos de
ingestão/treino não são registados na Vercel. Atualizar dados ou modelo é um
processo separado e não é necessário para publicar alterações da interface ou
do feedback.

**Antes de disponibilizar aconselhamento:** a base local atual tem observações
até 13/11/2026. Atualiza os dados IMERG; a aplicação exibe a data da última
observação para deixar explícita a cobertura temporal.
