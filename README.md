# Gestão Operacional — Mamba Growth

Dashboard interno para acompanhamento de performance das equipes de Edição, Copy, VSL, Estratégico e CS.

## Acesso

**Dashboard:** https://gestao.mambagrowthco.com/dashboard/

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

| Componente | Função |
|---|---|
| **ClickUp** | Base dos dados — tasks, status, assignees |
| **Railway** | Servidor do sync — roda sync.py a cada 6h |
| **Supabase** | Banco de dados — tabela `tasks` |
| **GitHub Pages** | Dashboard HTML estático |

## Variáveis de Ambiente

Todas as credenciais são configuradas como variáveis de ambiente no Railway e **nunca** devem ser commitadas neste repositório.

Consulte o administrador do projeto para acesso.
