# Governança e privacidade

A base é sintética, então não há dado pessoal aqui. Mesmo assim, o pipeline
foi desenhado como se houvesse. O motivo é prático: quando esta arquitetura
for apontada para o HRIS real, o comportamento correto já é o padrão.

## Decisões tomadas

**Não existe CPF.** Em vez disso, `hash_documento` traz um SHA-256 truncado.
A matrícula é a chave funcional. Nenhum identificador nacional trafega no
modelo analítico.

**Nome fica na dimensão, não no fato.** Isso permite publicar o modelo com a
coluna `nome` removida ou mascarada sem reconstruir nada.

**Dado sensível é marcado.** `genero` e `raca_cor` são autodeclarações e só
existem porque o Projeto 3 (equidade salarial) precisa deles. Em produção,
o tratamento se apoia no cumprimento de obrigação legal
(Lei 14.611/2023 e Decreto 11.795/2023) para o relatório de transparência
salarial, e o acesso deve ser restrito à equipe que produz o relatório.

**Agregação mínima.** Nenhuma visualização que cruze dado sensível com
remuneração deve exibir grupos com menos de 5 pessoas. Com n=3, o painel
deixa de ser estatística e passa a ser exposição individual.

## O que implementar no Power BI

1. **RLS por diretoria.** Gestor vê o próprio grupo, não a empresa.
2. **Duas versões do relatório.** Uma nominal, restrita ao RH; outra agregada,
   para gestores. Não resolva isso com "esconder a coluna" — o usuário exporta
   os dados subjacentes.
3. **Supressão por n mínimo.** Medida DAX que retorna `BLANK()` quando
   `DISTINCTCOUNT(matricula) < 5`.
4. **Trilha de auditoria.** Ative o log de atividades do tenant para relatórios
   com dado de pessoas.

## Sobre risco no modelo preditivo

Um score de propensão de saída é dado pessoal derivado e pode gerar efeito
adverso: gestor que vê "risco alto" pode parar de investir na pessoa, o que
vira profecia autorrealizável.

Mitigações que valem documentar no seu projeto:
- Entregar o score ao RH, não diretamente ao gestor de linha.
- Comunicar em faixas, nunca em probabilidade decimal.
- Reportar drivers acionáveis (estagnação, compa-ratio), não o número puro.
- Excluir `genero` e `raca_cor` das features do modelo de turnover e testar
  disparidade de erro entre grupos como controle.
