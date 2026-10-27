# Quem é meu deputado estadual (São Paulo)

Painel dos 94 deputados estaduais de São Paulo: projetos apresentados, quantos foram aprovados e presença nas reuniões das comissões, por deputado e por espectro político (esquerda em vermelho, centro em cinza, direita em azul). Os dados vêm dos [Dados Abertos da Alesp](https://www.al.sp.gov.br/dados-abertos/) e são recalculados todos os dias, sem intervenção manual.

**Painel:** https://reset-hightide.github.io/quem-e-meu-deputado-estadual/

Versão para deputados federais: [quem-e-meu-deputado](https://github.com/reset-hightide/quem-e-meu-deputado).

## Atenção: o que a Alesp publica

A Alesp **não publica presença em plenário nem votações nominais** em dados abertos (o serviço de presença está com erro e só há votações de comissões). Por isso, a presença aqui é medida nas **reuniões das comissões permanentes**, e não é comparável com a presença em plenário dos deputados federais.

## Como funciona

| Peça | O que faz |
|---|---|
| `atualizar.py` | Baixa os arquivos oficiais (deputados, proposituras, autores, tramitação, reuniões, presenças e membros de comissões), calcula os indicadores e grava `deputados.json`. Só usa a biblioteca padrão do Python. |
| `espectro.json` | Tabela partido → esquerda, centro ou direita. É uma convenção simplificada: edite para ajustar. |
| `index.html` | O painel. Lê `deputados.json` e mostra rankings, dispersão, tabela e a ficha de cada deputado. |
| `.github/workflows/atualizar.yml` | GitHub Actions: roda `atualizar.py` todo dia às 06:45 (Brasília) e commita o resultado. |

## Indicadores

- **Projetos apresentados:** PL, PLC, PR, PDL e PEC da legislatura atual (desde 15/03/2023) em que o deputado é autor ou coautor. Coautoria conta para cada autor. Requerimentos, moções e indicações ficam de fora.
- **Aprovados:** já aprovados pela Alesp (enviados ao governador, com autógrafo ou aprovados em plenário) ou que viraram lei. **Viraram lei:** publicados como lei, lei complementar, emenda, resolução ou decreto legislativo.
- **Presença e faltas em comissões:** reuniões realizadas das comissões permanentes de que o deputado é membro efetivo, no período em que foi membro. Só entram reuniões com lista de presença preenchida. A base não separa ausência justificada.

## Se algo der errado, e se der certo

O script termina com erro se os dados vierem incompletos (poucos deputados, projetos, reuniões ou presenças casadas). Em todo caso o workflow avisa:

1. **Deu certo:** push no celular ("atualizado"), se o segredo `NTFY_TOPIC` estiver configurado.
2. **Deu errado:** push de alta prioridade, uma **issue** automática com o link do log e o e-mail do GitHub (se as notificações do Actions estiverem ligadas).
3. A página mostra um **aviso vermelho** quando os dados têm mais de 3 dias.

### Configurar o aviso no celular (opcional)

1. Instale o app **ntfy** e assine um tópico com um nome difícil de adivinhar.
2. No GitHub: *Settings → Secrets and variables → Actions → New repository secret*, nome `NTFY_TOPIC`, valor o nome do tópico.

## Rodar localmente

```bash
python atualizar.py        # baixa e calcula (cerca de 300 MB de XML descompactado)
python -m http.server      # abrir http://localhost:8000
```
