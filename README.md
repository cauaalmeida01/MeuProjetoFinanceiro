# Meu Painel Financeiro

Painel pessoal com entradas, saídas, categorias, insights e investimentos, a partir do extrato do Inter. A XP entra depois.

## Estrutura

```
regras_categorias.json      regras por estabelecimento (iFood → Alimentação…)
scripts/gerar_painel.py     classifica o extrato e gera o painel
scripts/importar_extrato.py junta um extrato novo ao histórico
scripts/sincronizar_pluggy.py busca o extrato na Pluggy e gera o painel
scripts/agendar_sincronizacao.sh liga/desliga a sincronização diária no Mac
painel/base.html            o painel (HTML + gráficos), sem dados
template/livro-caixa.html   versão de demonstração com dados fictícios

dados/                      NÃO vai para o GitHub
  inter_extrato.psv         histórico bruto do Inter
  regras_pessoais.json      pessoas → categoria, e seus próprios nomes
  xp.json                   posição, evolução mensal e conciliação da XP
  inter_invest.json         posição e evolução mensal dos investimentos do Inter
  transacoes.json           gerado
painel/index.html           gerado, com seus dados (NÃO vai para o GitHub)
```

## Gerar o painel

```bash
python3 scripts/gerar_painel.py
```

Depois abra `painel/index.html` no navegador.

## Atualização automática (Pluggy / Open Finance)

Os bancos ficam conectados no [Meu Pluggy](https://meu.pluggy.ai), e a API da Pluggy entrega o extrato dos últimos ~12 meses. Crie um `.env` na raiz (já está no `.gitignore`):

```
PLUGGY_CLIENT_ID=...
PLUGGY_CLIENT_SECRET=...
PLUGGY_ITEM_IDS=id-do-inter,id-da-xp
```

Os Item IDs ficam em dashboard.pluggy.ai, em Demo, no menu ⋮ de cada conexão, opção "Copiar Item ID".

```bash
python3 scripts/sincronizar_pluggy.py          # sincroniza agora
scripts/agendar_sincronizacao.sh               # liga a sincronização diária (13h)
scripts/agendar_sincronizacao.sh remover       # desliga
```

O histórico antigo continua em `dados/inter_extrato.psv`; só o período que a Pluggy cobre é substituído. Da XP vêm as posições, o saldo, os proventos e os Pix recebidos do Inter (que entram na conciliação de `envios_inter_para_xp`), gravados em `dados/xp.json`. A cada mês o script guarda o patrimônio da XP em `fotos_mensais` e, a partir de novembro de 2026, calcula aportes e rendimento do mês; a rentabilidade acumulada e o % do CDI continuam os do portal da XP em 28/10/2026. O log da execução diária fica em `dados/sincronizacao.log`. A autorização do Open Finance vence em até 12 meses e precisa ser renovada no Meu Pluggy.

## Atualizar à mão

1. Pegue o extrato do período novo no formato `data|titulo|descricao|valor|tipo`.
2. `python3 scripts/importar_extrato.py caminho/do/novo.psv`. Ele substitui tudo a partir da primeira data do arquivo novo, então repetir um período não duplica nada.
3. `python3 scripts/gerar_painel.py`

## Categorias

- Estabelecimentos: `regras_categorias.json`. A primeira regra que bater vence.
- Pessoas: `dados/regras_pessoais.json`. Em `destinos` ficam os Pix enviados (amigos, família, faxina…) e em `origens`, os recebidos (ex.: família). Essas regras têm prioridade.
- Pix para pessoas físicas que nenhuma regra reconhece vão para **Pix para pessoas**. O resto que nada reconhece vai para **Outros**. Aplicações e resgates contam como investimento, e Pix entre contas suas não conta como gasto.
