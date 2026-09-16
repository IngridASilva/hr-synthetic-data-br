# Dicionário de dados

Modelo em estrela, pronto para importação direta no Power BI.
Todos os arquivos ficam em `data/synthetic/` em formato Parquet
(o Power Query lê nativamente com `Parquet.Document`).

## Diagrama de relacionamentos

```
                   dim_calendario (dia)
                          │ id_mes
                          ▼
dim_colaborador ──► fato_headcount_mensal ◄── dim_area
   matricula            matricula                id_area
        │                  │ id_cargo                │
        │                  ▼                         │
        │              dim_cargo ──► dim_faixa_salarial
        │                  (id_cargo)      (id_cargo + ano)
        │
        ├──► fato_folha_mensal        (matricula + id_mes)
        ├──► fato_movimentacao        (evento)
        ├──► fato_desligamento_custo  (desligamento)
        └──► dim_avaliacao            (matricula + ciclo)
```

Cardinalidade: todas as relações são 1:N, direção única da dimensão para o
fato. `dim_faixa_salarial` é a única com chave composta (`id_cargo` + `ano`);
resolva com coluna concatenada ou com `TREATAS` no DAX.

---

## dim_colaborador
Grão: uma linha por pessoa. SCD tipo 1 (atributos fixos ao longo do tempo).

| Coluna | Tipo | Descrição |
|---|---|---|
| matricula | int | Chave primária |
| nome | texto | Nome fictício, gerado por combinação aleatória |
| hash_documento | texto | Pseudônimo SHA-256. Não há CPF na base, por desenho |
| data_nascimento | data | |
| genero, raca_cor | texto | Autodeclaração. Dado sensível: ver `governanca_lgpd.md` |
| escolaridade | texto | Correlacionada com o grade de entrada |
| estado_civil, num_dependentes | texto / int | |
| uf, cidade | texto | |
| distancia_km | decimal | Distância casa–escritório |
| data_admissao | data | |
| data_desligamento | data | Nulo para ativos |
| tipo_desligamento | texto | Voluntário / Involuntário |
| motivo_desligamento | texto | |
| status | texto | Ativo / Desligado |

## dim_area
Grão: área (gerência). 15 linhas.

| Coluna | Descrição |
|---|---|
| id_area | Chave primária |
| diretoria, gerencia | Hierarquia organizacional |
| familia_cargo | Família predominante na área |
| centro_custo | Chave de rateio para Finanças |
| criticidade | Alta / Média / Baixa. Define o múltiplo de custo de reposição |
| sindicato, mes_data_base | Mês do dissídio da categoria |

## dim_cargo / dim_faixa_salarial
`dim_cargo` traz a estrutura (família × grade × nível) e a faixa de
referência do ano-base. `dim_faixa_salarial` traz a faixa **corrigida ano a
ano**, que é a referência correta para calcular compa-ratio histórico.

## dim_calendario
Grão: dia. Marque como tabela de datas no Power BI para habilitar time
intelligence. Traz `id_mes`, `ano_mes`, `trimestre`, `semestre`,
`eh_dia_util` e `ultimo_dia_mes`.

## fato_headcount_mensal
Grão: matrícula × mês. É a foto do quadro no último dia do mês.

| Coluna | Descrição |
|---|---|
| id_mes, data_referencia | Chaves de tempo |
| matricula, id_area, id_cargo, id_gestor | Chaves |
| grade, familia_cargo, modelo_trabalho | Atributos do momento |
| salario | Salário base vigente |
| compa_ratio | salário ÷ mediana da faixa vigente no ano |
| performance | Rating 1–5 do último ciclo |
| meses_de_casa, meses_sem_promocao, num_promocoes | Features de carreira |
| idade, horas_extras | |

Cuidado com `meses_sem_promocao`: ela é a feature mais preditiva da base e
também a mais fácil de vazar se você construir o dataset de ML sem corte
temporal correto.

## fato_folha_mensal
Grão: matrícula × mês. Mesmo grão do headcount, o que evita fan-out.

Decomposição: `salario` → `valor_horas_extras` → `remuneracao_bruta` →
`encargos` → `provisao_13o` → `provisao_ferias` → `beneficios_total` →
`custo_total`. A coluna `fator_custo_sobre_salario` mostra quanto o custo
real supera o salário (mediana ~1,9; chega a 3,0 nos salários mais baixos,
porque benefício é valor fixo e portanto regressivo).

## fato_movimentacao
Grão: evento. Tipos: `Dissídio`, `Mérito`, `Promoção`, `Desligamento`.
Traz `salario_anterior`, `salario_novo` e `variacao_pct`. É a base para
qualquer análise de progressão de carreira e de composição do reajuste
(quanto do aumento da folha veio de dissídio, quanto de mérito, quanto de
promoção — pergunta clássica de FP&A).

## fato_desligamento_custo
Grão: desligamento. Decompõe o custo em verbas rescisórias
(`aviso_previo`, `ferias_proporcionais`, `decimo_terceiro_prop`,
`multa_fgts`) e `custo_reposicao` (múltiplo do salário conforme a
criticidade da área). `custo_total_desligamento` é a soma.

Esta tabela é a ponte entre o modelo preditivo e a conversa com o CFO.

## dim_avaliacao
Grão: matrícula × ciclo anual. Ratings de performance e potencial (insumo
para matriz 9-box).

## Arquivos de gabarito (não são features)

- `ground_truth_coeficientes.json`: os coeficientes verdadeiros do modelo de
  hazard e a hierarquia esperada de drivers.
- `ground_truth_efeito_gestor.parquet`: o efeito latente de cada gestor.

Use para validar o SHAP do seu modelo. Treinar com eles é autoengano.
