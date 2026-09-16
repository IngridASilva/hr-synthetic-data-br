# Verdade-base: coeficientes e como validar seu modelo

O arquivo `data/synthetic/ground_truth_coeficientes.json` é gerado junto com a
base e contém os coeficientes reais usados no modelo de hazard.

## Hierarquia esperada de drivers (turnover voluntário)

Ordem aproximada por magnitude de efeito na faixa típica de cada variável:

1. `meses_sem_promocao` — estagnação de carreira, com saturação logarítmica
2. `compa_ratio` — posicionamento salarial contra a faixa
3. interação `performance × subremuneração` — a origem do *regretted attrition*
4. `tempo_de_casa` — curva em U invertido, pico em ~18 meses
5. efeito latente de gestor — não observável diretamente
6. `modelo_trabalho` — presencial > híbrido > remoto
7. `idade`
8. `horas_extras`
9. `distancia_km` — só pesa para quem vai ao escritório

## Como usar isso

Rode o SHAP do seu modelo e compare o ranking de importância global com a
lista acima. Alguns diagnósticos:

**Seu top-1 é `salario` em vez de `compa_ratio`.** O modelo achou o proxy, não
a causa. Salário alto em valor absoluto indica senioridade, não satisfação.
Quem decide sair compara com a faixa do próprio cargo. Feature engineering
corrige: alimente `compa_ratio` explicitamente.

**A interação performance × subremuneração não aparece.** Modelo linear sem
termo de interação não captura. É o argumento prático para usar árvore, ou
para criar a feature cruzada à mão numa regressão logística.

**`meses_sem_promocao` aparece com efeito linear.** O efeito verdadeiro é
logarítmico: de 12 para 24 meses sem promoção dói muito mais que de 60 para
72. Se o seu PDP mostra reta, você está extrapolando mal na cauda.

**Sua AUC passou de 0,85.** Procure vazamento. Os candidatos usuais:
- usar `data_desligamento` ou qualquer derivada dela como feature;
- construir o dataset sem corte temporal, treinando com meses futuros;
- incluir os arquivos `ground_truth_*`;
- usar o último snapshot do colaborador, que por definição é o mês da saída.

## Efeito de gestor

`ground_truth_efeito_gestor.parquet` traz o deslocamento em log-odds de cada
líder. O efeito tem desvio-padrão de 0,40, o que significa que um gestor no
percentil 90 tem risco de saída do time cerca de 60% maior que a mediana,
controlando por todo o resto.

Seu modelo não vê essa coluna. Para capturá-la você precisa construir features
de equipe: turnover histórico do gestor, span de controle, compa-ratio médio
do time, tempo médio sem promoção do time. Essa é a diferença entre um modelo
que aponta pessoas e um modelo que aponta problemas de gestão — e a segunda
conversa é a que gera ação.
