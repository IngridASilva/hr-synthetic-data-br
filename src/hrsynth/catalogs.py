"""
Catálogos estruturais da organização sintética.

Estes objetos descrevem a *estrutura* da empresa (cargos, níveis, áreas,
sindicatos). Eles não são aleatórios: são a espinha dorsal que garante que
salário, cargo e área sejam internamente coerentes em toda a simulação.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Níveis de carreira (grade). A ordem define a escada de promoção.
# `mediana_base` é o ponto médio da faixa salarial antes do multiplicador
# da família de cargo.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Nivel:
    grade: int
    nome: str
    mediana_base: float
    amplitude: float  # largura da faixa: min = mediana*(1-a), max = mediana*(1+a)
    prob_promocao_mes: float  # chance mensal de promoção quando elegível


NIVEIS: list[Nivel] = [
    Nivel(1, "Assistente", 2_800, 0.20, 0.030),
    Nivel(2, "Analista Júnior", 4_200, 0.20, 0.028),
    Nivel(3, "Analista Pleno", 6_500, 0.22, 0.022),
    Nivel(4, "Analista Sênior", 9_500, 0.22, 0.016),
    Nivel(5, "Especialista", 13_500, 0.25, 0.010),
    Nivel(6, "Coordenador", 16_000, 0.25, 0.008),
    Nivel(7, "Gerente", 24_000, 0.28, 0.004),
    Nivel(8, "Diretor", 45_000, 0.30, 0.000),
]

NIVEL_POR_GRADE: dict[int, Nivel] = {n.grade: n for n in NIVEIS}

# --------------------------------------------------------------------------
# Famílias de cargo. O multiplicador reflete o prêmio de mercado por família
# (TI paga mais que Atendimento no mesmo grade).
# --------------------------------------------------------------------------

FAMILIAS: dict[str, float] = {
    "Tecnologia": 1.35,
    "Jurídico": 1.20,
    "Financeiro": 1.15,
    "Comercial": 1.10,
    "Marketing": 1.00,
    "Recursos Humanos": 0.95,
    "Operações": 0.90,
    "Atendimento": 0.80,
}

# --------------------------------------------------------------------------
# Estrutura organizacional: diretoria -> gerência (área).
# `peso` controla o tamanho relativo da área no headcount.
# `piramide` é a distribuição de grades dentro da área (chave = grade).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Area:
    id_area: int
    diretoria: str
    gerencia: str
    familia: str
    centro_custo: str
    peso: float
    criticidade: str  # Alta / Média / Baixa -> usado no custo de reposição
    grade_max: int


AREAS: list[Area] = [
    Area(1, "Comercial", "Vendas Corporativas", "Comercial", "CC-1010", 0.13, "Alta", 7),
    Area(2, "Comercial", "Vendas Varejo", "Comercial", "CC-1020", 0.11, "Média", 7),
    Area(3, "Comercial", "Customer Success", "Atendimento", "CC-1030", 0.10, "Média", 6),
    Area(4, "Operações", "Logística", "Operações", "CC-2010", 0.12, "Média", 7),
    Area(5, "Operações", "Produção", "Operações", "CC-2020", 0.14, "Baixa", 7),
    Area(6, "Operações", "Qualidade", "Operações", "CC-2030", 0.05, "Média", 6),
    Area(7, "Tecnologia", "Engenharia de Software", "Tecnologia", "CC-3010",
         0.09, "Alta", 7),
    Area(8, "Tecnologia", "Dados & BI", "Tecnologia", "CC-3020", 0.05, "Alta", 6),
    Area(9, "Tecnologia", "Infraestrutura", "Tecnologia", "CC-3030", 0.04, "Alta", 6),
    Area(10, "Financeira", "Controladoria", "Financeiro", "CC-4010", 0.04, "Alta", 7),
    Area(11, "Financeira", "FP&A", "Financeiro", "CC-4020", 0.03, "Alta", 6),
    Area(12, "Financeira", "Fiscal", "Financeiro", "CC-4030", 0.03, "Média", 6),
    Area(13, "Pessoas & Adm", "Recursos Humanos", "Recursos Humanos", "CC-5010",
         0.04, "Média", 7),
    Area(14, "Pessoas & Adm", "Jurídico", "Jurídico", "CC-5020", 0.02, "Alta", 6),
    Area(15, "Pessoas & Adm", "Marketing", "Marketing", "CC-5030", 0.01, "Média", 6),
]

AREA_POR_ID: dict[int, Area] = {a.id_area: a for a in AREAS}

# Pirâmide de senioridade padrão (probabilidade por grade na contratação).
PIRAMIDE_PADRAO: dict[int, float] = {
    1: 0.18,
    2: 0.26,
    3: 0.24,
    4: 0.16,
    5: 0.07,
    6: 0.06,
    7: 0.025,
    8: 0.005,
}

# --------------------------------------------------------------------------
# Sindicato / data-base do dissídio por diretoria.
# No Brasil o reajuste coletivo não é uniforme na empresa: cada categoria tem
# sua data-base. Ignorar isso é o erro mais comum em forecast de folha.
# --------------------------------------------------------------------------

SINDICATOS: dict[str, dict] = {
    "Comercial": {"sindicato": "SINDCOM", "mes_data_base": 9},
    "Operações": {"sindicato": "SINDMETAL", "mes_data_base": 5},
    "Tecnologia": {"sindicato": "SINDPD", "mes_data_base": 1},
    "Financeira": {"sindicato": "SINDCONT", "mes_data_base": 1},
    "Pessoas & Adm": {"sindicato": "SINDCOM", "mes_data_base": 5},
}

# --------------------------------------------------------------------------
# Domínios categóricos simples.
# --------------------------------------------------------------------------

MODELOS_TRABALHO = ["Presencial", "Híbrido", "Remoto"]

ESCOLARIDADES = [
    "Ensino Médio",
    "Superior Incompleto",
    "Superior Completo",
    "Pós-graduação",
    "Mestrado/Doutorado",
]

RACA_COR = ["Branca", "Parda", "Preta", "Amarela", "Indígena", "Não informado"]

GENEROS = ["Feminino", "Masculino", "Não informado"]

ESTADO_CIVIL = ["Solteiro(a)", "Casado(a)", "Divorciado(a)", "Viúvo(a)"]

MOTIVOS_VOLUNTARIO = [
    "Pedido de demissão - proposta externa",
    "Pedido de demissão - insatisfação com liderança",
    "Pedido de demissão - remuneração",
    "Pedido de demissão - motivos pessoais",
    "Pedido de demissão - falta de perspectiva de carreira",
]

MOTIVOS_INVOLUNTARIO = [
    "Dispensa sem justa causa - desempenho",
    "Dispensa sem justa causa - reestruturação",
    "Dispensa sem justa causa - fim de projeto",
    "Dispensa por justa causa",
]

# Nomes fictícios. Não representam pessoas reais.
NOMES_F = [
    "Ana", "Beatriz", "Camila", "Daniela", "Eduarda", "Fernanda", "Gabriela",
    "Helena", "Isabela", "Juliana", "Karina", "Larissa", "Mariana", "Natália",
    "Patrícia", "Renata", "Sabrina", "Tatiane", "Vanessa", "Yasmin",
]
NOMES_M = [
    "Alexandre", "Bruno", "Carlos", "Diego", "Eduardo", "Felipe", "Gustavo",
    "Henrique", "Igor", "João", "Leonardo", "Marcelo", "Nelson", "Otávio",
    "Paulo", "Rafael", "Sérgio", "Thiago", "Vinícius", "Wagner",
]
SOBRENOMES = [
    "Almeida", "Barbosa", "Carvalho", "Dias", "Esteves", "Ferreira", "Gomes",
    "Henriques", "Ibrahim", "Jesus", "Lima", "Martins", "Nascimento", "Oliveira",
    "Pereira", "Queiroz", "Rodrigues", "Santos", "Teixeira", "Vieira",
]


def mediana_salarial(familia: str, grade: int) -> float:
    """Ponto médio da faixa salarial para uma combinação família x grade."""
    return NIVEL_POR_GRADE[grade].mediana_base * FAMILIAS[familia]
