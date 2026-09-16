"""
Modelo de hazard (risco de desligamento) - a VERDADE-BASE da simulação.

Este é o módulo mais importante do repositório.

A maioria dos datasets sintéticos de RH sorteia a coluna `desligado` de forma
independente das demais. O resultado é uma base onde nenhum modelo de ML
consegue aprender nada real, e qualquer AUC acima de 0,55 é ruído.

Aqui o desligamento é gerado por um modelo de risco mensal com estrutura
causal explícita. Isso significa que:

1. Existe sinal real a ser descoberto pelo modelo preditivo;
2. Você conhece os coeficientes verdadeiros, então pode validar se o SHAP do
   seu XGBoost recupera a hierarquia de drivers correta;
3. Há confundimento e interação de propósito (ex.: alto desempenho + baixo
   compa-ratio), o que separa um modelo bem especificado de um ingênuo.

Os coeficientes estão em escala de log-odds mensal.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

# --------------------------------------------------------------------------
# Coeficientes verdadeiros (log-odds do desligamento VOLUNTÁRIO no mês)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CoefVoluntario:
    # Intercepto: calibra o turnover voluntário anual de base.
    # Calibrado para ~14% de turnover voluntário ao ano DEPOIS de somados
    # todos os demais termos (tenure, estagnação, sazonalidade, choque de
    # mercado). Confira sempre no relatório de sanidade da CLI.
    intercepto: float = -5.95

    # Curva de sobrevivência em U invertido: risco sobe até ~18 meses de casa
    # e cai depois (efeito "vesting" emocional e financeiro).
    pico_tenure_meses: float = 18.0
    largura_tenure: float = 16.0
    amp_tenure: float = 0.95
    decaimento_tenure_ano: float = -0.075  # por ano de casa acima do pico

    # Estagnação de carreira. log1p para saturar: o salto de 12 -> 24 meses
    # sem promoção dói mais que 60 -> 72.
    meses_sem_promocao: float = 0.42

    # Posicionamento salarial. compa_ratio = salário / mediana da faixa.
    # Centrado em 1,0. Quem está 20% abaixo da mediana ganha +0,26 de log-odds.
    compa_ratio: float = -1.30

    # Idade centrada em 35, em décadas. Mais velho, menos propenso a sair.
    idade_decadas: float = -0.30

    # Desempenho centrado em 3 (escala 1-5). Alto desempenho tem mais opções
    # externas -> risco levemente maior.
    performance: float = 0.14

    # INTERAÇÃO-CHAVE: alto desempenho subremunerado.
    # Só ativa quando compa_ratio < 1. É a origem do "regretted attrition".
    perf_x_subremuneracao: float = 1.15

    # Modelo de trabalho (Híbrido é a referência).
    modelo_presencial: float = 0.30
    modelo_hibrido: float = 0.0
    modelo_remoto: float = -0.22

    # Deslocamento casa-trabalho, em dezenas de km. Só pesa para quem vai ao
    # escritório - interação com modelo de trabalho.
    distancia_10km: float = 0.16

    # Horas extras médias no mês (proxy de sobrecarga).
    horas_extras_10h: float = 0.20

    # Senioridade: base da pirâmide roda mais.
    grade: float = -0.11

    # Efeito de liderança: desvio-padrão do efeito aleatório por gestor.
    # É o "fator gestor" que todo RH afirma existir e raramente mede.
    sd_efeito_gestor: float = 0.40

    # Sazonalidade brasileira (índice 1-12). Pico em jan/fev (pós 13º e
    # férias), vale em novembro/dezembro (ninguém sai antes do 13º).
    sazonalidade: tuple = (
        0.38, 0.30, 0.14, 0.02, -0.02, 0.00,
        0.08, 0.06, 0.02, -0.05, -0.30, -0.45,
    )


@dataclass(frozen=True)
class CoefInvoluntario:
    intercepto: float = -5.60           # ~0,37% ao mês -> ~4% ao ano
    performance_baixa: float = 1.45     # rating <= 2
    performance_alta: float = -0.90     # rating >= 4
    experiencia_meses_12: float = -0.10  # período de experiência concentra corte
    grade: float = -0.08


COEF_VOLUNTARIO = CoefVoluntario()
COEF_INVOLUNTARIO = CoefInvoluntario()


def _sigmoide(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _efeito_tenure(meses_casa: float, c: CoefVoluntario) -> float:
    """Risco em U invertido ao longo do tempo de casa."""
    pico = c.amp_tenure * math.exp(
        -(((meses_casa - c.pico_tenure_meses) / c.largura_tenure) ** 2)
    )
    decaimento = c.decaimento_tenure_ano * (min(meses_casa, 180.0) / 12.0)
    return pico + decaimento


def hazard_voluntario(
    *,
    meses_casa: float,
    meses_sem_promocao: float,
    compa_ratio: float,
    idade: float,
    performance: float,
    modelo_trabalho: str,
    distancia_km: float,
    horas_extras: float,
    grade: int,
    efeito_gestor: float,
    mes: int,
    choque_externo: float = 0.0,
    c: CoefVoluntario = COEF_VOLUNTARIO,
) -> float:
    """Probabilidade de pedir demissão neste mês.

    `choque_externo` permite injetar conjuntura (aquecimento do mercado de
    trabalho, por exemplo) de forma exógena e documentada.
    """
    subremuneracao = max(0.0, 1.0 - compa_ratio)

    logit = (
        c.intercepto
        + _efeito_tenure(meses_casa, c)
        + c.meses_sem_promocao * math.log1p(meses_sem_promocao / 12.0)
        + c.compa_ratio * (compa_ratio - 1.0)
        + c.idade_decadas * ((idade - 35.0) / 10.0)
        + c.performance * (performance - 3.0)
        + c.perf_x_subremuneracao * max(0.0, performance - 3.0) * subremuneracao
        + c.horas_extras_10h * (horas_extras / 10.0)
        + c.grade * (grade - 3)
        + efeito_gestor
        + c.sazonalidade[mes - 1]
        + choque_externo
    )

    if modelo_trabalho == "Presencial":
        logit += c.modelo_presencial
        logit += c.distancia_10km * (distancia_km / 10.0)
    elif modelo_trabalho == "Híbrido":
        logit += c.modelo_hibrido
        logit += 0.5 * c.distancia_10km * (distancia_km / 10.0)
    else:
        logit += c.modelo_remoto

    return _sigmoide(logit)


def hazard_involuntario(
    *,
    performance: float,
    meses_casa: float,
    grade: int,
    c: CoefInvoluntario = COEF_INVOLUNTARIO,
) -> float:
    """Probabilidade de dispensa pela empresa neste mês (fora de reestruturação)."""
    logit = c.intercepto + c.grade * (grade - 3)
    if performance <= 2:
        logit += c.performance_baixa
    elif performance >= 4:
        logit += c.performance_alta
    if meses_casa <= 12:
        logit += c.experiencia_meses_12 * (12 - meses_casa)
    return _sigmoide(logit)


def exportar_coeficientes() -> dict:
    """Serializa a verdade-base para conferência posterior no projeto de ML."""
    return {
        "voluntario": asdict(COEF_VOLUNTARIO),
        "involuntario": asdict(COEF_INVOLUNTARIO),
        "hierarquia_esperada_drivers": [
            "meses_sem_promocao",
            "compa_ratio",
            "interacao_performance_x_subremuneracao",
            "tempo_de_casa",
            "efeito_gestor",
            "modelo_trabalho",
            "idade",
            "horas_extras",
            "distancia_km",
        ],
        "nota": (
            "Hierarquia aproximada por magnitude de efeito na faixa típica das "
            "variáveis. Use como gabarito ao comparar com o ranking do SHAP."
        ),
    }
