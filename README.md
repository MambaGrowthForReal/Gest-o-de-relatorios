# Gestão Operacional — Mamba Growth

Dashboard interno para acompanhamento de performance das equipes de Edição, Copy, VSL e Estratégico.

## Acesso

**Dashboard:** https://mambagrowthforreal.github.io/Gest-o-de-relatorios/dashboard/

## Estrutura do Projeto

```
MambaGrowthForReal/Gest-o-de-relatorios/
├── dashboard/
│   └── index.html       # Dashboard HTML (GitHub Pages)
├── sync.py              # Worker de sincronização ClickUp → Supabase
├── requirements.txt     # Dependências Python
└── Procfile             # Configuração Railway
```

## Infraestrutura

| Componente | Função | Detalhes |
|---|---|---|
| **ClickUp** | Base dos dados | Tasks, status, assignees, due_date |
| **Railway** | Servidor do sync | Roda sync.py a cada 6h |
| **Supabase** | Banco de dados | Tabela `tasks` com dados sincronizados |
| **GitHub Pages** | Dashboard | HTML estático servido publicamente |

## Sync (Railway)

- **Projeto:** mindful-integrity
- **Intervalo:** a cada 6h
- **Repositório conectado:** MambaGrowthForReal/Gest-o-de-relatorios
- **Funcionamento:**
  1. Busca todas as tasks do ClickUp
  2. Para a lista "Novos criativos" (ID: `901700896208`): faz chamada individual por task para recuperar `due_date`
  3. Faz upsert no Supabase via REST API

## Supabase

- **Projeto:** wlfrmnpntpnbjekwnvcs
- **Tabela:** `tasks`
- **Campos:** `id`, `name`, `status`, `assignees` (jsonb), `space_id`, `space_name`, `list_id`, `list_name`, `due_date`, `date_created`, `date_updated`, `synced_at`
- **RLS:** desabilitado (leitura pública via chave publishable)

## Dashboard

### Abas

| Aba | Sub-aba | Dados |
|---|---|---|
| Edição | Ads | Criativos por editor (planejado/entregue/%) |
| Edição | VSL | Status de edição VSL por editor |
| Copy | — | Ads por copywriter + planejamento da semana |
| Estratégico | — | Demandas estratégicas por responsável |
| CS | — | Em breve |

### Editores Ads (IDs ClickUp)

| Editor | ID |
|---|---|
| Luan Pereira | 82160031 |
| Malcom Severiano | 89397911 |
| Gustavo Teixeira | 170645656 |
| Victor Ravi | 89297830 |
| Vitu Sgmk | 89362557 |
| Thiago Leite | 89133258 |

## Variáveis de Ambiente (Railway)

```
CLICKUP_TOKEN=pk_206504924_97P74AJM8PTO06YGY0P17EXV366HV81N
SUPABASE_URL=https://wlfrmnpntpnbjekwnvcs.supabase.co
SUPABASE_KEY=sb_secret_r7ZC2OnfvL7NCKsm_nSrIA_c6oS7BOZ
```

## Observações

- Dados da aba Ads estão atualmente hardcoded (atualização manual semanal)
- `due_date` de algumas tasks retorna `null` via API do ClickUp — investigação em andamento
- 1 task = 5 criativos (vídeos)
- Tasks sem `due_date` = ainda com time de copy → ignoradas no dashboard de Edição
