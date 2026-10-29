# Meu Painel Financeiro

Painel pessoal com entradas, saídas, categorias, insights e investimentos, a partir do extrato do Inter. A XP entra depois.

## Estrutura

```
regras_categorias.json      regras por estabelecimento (iFood → Alimentação…)
scripts/gerar_painel.py     classifica o extrato e gera o painel
scripts/importar_extrato.py junta um extrato novo ao histórico
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

## Atualizar todo mês

1. Pegue o extrato do período novo no formato `data|titulo|descricao|valor|tipo`.
2. `python3 scripts/importar_extrato.py caminho/do/novo.psv`. Ele substitui tudo a partir da primeira data do arquivo novo, então repetir um período não duplica nada.
3. `python3 scripts/gerar_painel.py`

## Categorias

- Estabelecimentos: `regras_categorias.json`. A primeira regra que bater vence.
- Pessoas: `dados/regras_pessoais.json`. Em `destinos` ficam os Pix enviados (amigos, família, faxina…) e em `origens`, os recebidos (ex.: família). Essas regras têm prioridade.
- Pix para pessoas físicas que nenhuma regra reconhece vão para **Pix para pessoas**. O resto que nada reconhece vai para **Outros**. Aplicações e resgates contam como investimento, e Pix entre contas suas não conta como gasto.
