"""
Camada financeira: encargos, provisões, benefícios e custo de desligamento.

É aqui que o projeto deixa de ser "dataset de RH" e vira insumo para Finanças.
Salário base não é custo. Custo é salário + encargos + provisões + benefícios,
e a diferença passa de 60% em regime CLT no Simples/Lucro Real sem desoneração.

Aviso: os percentuais abaixo são a configuração padrão do regime geral
(Anexo V / Lucro Real, sem desoneração da folha). Regime tributário,
enquadramento sindical e acordos coletivos mudam esses números. Trate como
premissa configurável, nunca como verdade fiscal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Params
from .people import faixa_etaria


def taxa_encargos(p: Params) -> float:
    """Encargos incidentes sobre a remuneração, em fração do salário."""
    e = p["encargos"]
    return e["inss_patronal"] + e["rat"] + e["terceiros"] + e["fgts"]


def calcular_folha(snapshots: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Gera o fato de custo mensal por colaborador.

    Grão: uma linha por matrícula por mês. Mesmo grão do fato de headcount,
    o que permite relacionar os dois no Power BI sem fan-out.
    """
    enc = taxa_encargos(p)
    ben = p["beneficios"]

    df = snapshots.copy()
    # Hora extra a 50% sobre o valor-hora (jornada de 220h).
    df["valor_horas_extras"] = (df["salario"] / 220.0) * df["horas_extras"] * 1.5
    df["remuneracao_bruta"] = df["salario"] + df["valor_horas_extras"]

    df["encargos"] = df["remuneracao_bruta"] * enc
    df["provisao_13o"] = (
        df["remuneracao_bruta"] / 12.0 * (1 + enc)
        if p["encargos"]["provisao_13o"] else 0.0
    )
    df["provisao_ferias"] = (
        df["remuneracao_bruta"] * (4.0 / 3.0) / 12.0 * (1 + enc)
        if p["encargos"]["provisao_ferias"] else 0.0
    )

    df["vale_refeicao"] = ben["vale_refeicao_dia"] * ben["dias_uteis_mes"]
    df["vale_transporte"] = np.where(
        df["modelo_trabalho"] == "Presencial", ben["vale_transporte_mes"],
        np.where(df["modelo_trabalho"] == "Híbrido",
                 ben["vale_transporte_mes"] * 0.5, 0.0),
    )
    df["plano_saude"] = df["idade"].map(
        lambda i: ben["plano_saude_por_faixa"][faixa_etaria(int(i))]
    )
    df["seguro_vida"] = ben["seguro_vida_mes"]
    df["beneficios_total"] = (
        df["vale_refeicao"] + df["vale_transporte"]
        + df["plano_saude"] + df["seguro_vida"]
    )

    df["custo_total"] = (
        df["remuneracao_bruta"] + df["encargos"]
        + df["provisao_13o"] + df["provisao_ferias"] + df["beneficios_total"]
    )
    df["fator_custo_sobre_salario"] = df["custo_total"] / df["salario"]

    colunas = [
        "id_mes", "data_referencia", "matricula", "id_area", "grade",
        "salario", "valor_horas_extras", "remuneracao_bruta", "encargos",
        "provisao_13o", "provisao_ferias", "vale_refeicao", "vale_transporte",
        "plano_saude", "seguro_vida", "beneficios_total", "custo_total",
        "fator_custo_sobre_salario",
    ]
    num = df[colunas].select_dtypes("number").columns
    return df[colunas].astype({c: float for c in num}).round({c: 2 for c in num})


def calcular_custo_desligamento(
    movimentacoes: pd.DataFrame,
    snapshots: pd.DataFrame,
    colaboradores: pd.DataFrame,
    p: Params,
    areas: pd.DataFrame,
) -> pd.DataFrame:
    """Custo total de cada desligamento: rescisão + reposição.

    Este DataFrame é o que transforma o Projeto 1 (previsão de turnover) em
    conversa de diretoria. Probabilidade não sensibiliza CFO; R$ sim.
    """
    enc = taxa_encargos(p)
    resc = p["rescisao"]
    mult = resc["multiplo_reposicao"]

    desl = movimentacoes[movimentacoes["tipo_evento"] == "Desligamento"].copy()
    if desl.empty:
        return desl

    base = colaboradores.set_index("matricula")
    desl["tipo_desligamento"] = desl["matricula"].map(base["tipo_desligamento"])
    desl["data_admissao"] = desl["matricula"].map(base["data_admissao"])
    desl["salario"] = desl["salario_novo"]

    desl["meses_de_casa"] = (
        (desl["data_evento"] - desl["data_admissao"]).dt.days / 30.44
    ).clip(lower=0)

    # Verbas rescisórias (aproximação gerencial, não cálculo trabalhista).
    desl["aviso_previo"] = desl["salario"] * resc["aviso_previo_meses"]
    desl["ferias_proporcionais"] = desl["salario"] * (4 / 3) * (
        desl["meses_de_casa"].mod(12) / 12
    )
    desl["decimo_terceiro_prop"] = desl["salario"] * (
        desl["data_evento"].dt.month / 12
    )
    saldo_fgts = desl["salario"] * 0.08 * desl["meses_de_casa"]
    desl["multa_fgts"] = np.where(
        desl["tipo_desligamento"] == "Involuntário",
        saldo_fgts * resc["multa_fgts_involuntario"], 0.0,
    )
    desl["custo_rescisao"] = (
        (desl["aviso_previo"] + desl["ferias_proporcionais"]
         + desl["decimo_terceiro_prop"]) * (1 + enc)
        + desl["multa_fgts"]
    )

    # Custo de reposição: múltiplo do salário mensal, por criticidade da área.
    crit = areas.set_index("id_area")["criticidade"]
    desl["criticidade_area"] = desl["id_area"].map(crit)
    desl["multiplo_reposicao"] = desl["criticidade_area"].map(mult)
    desl["custo_reposicao"] = desl["salario"] * desl["multiplo_reposicao"]

    desl["custo_total_desligamento"] = (
        desl["custo_rescisao"] + desl["custo_reposicao"]
    )

    colunas = [
        "matricula", "data_evento", "tipo_desligamento", "detalhe", "id_area",
        "criticidade_area", "grade", "salario", "meses_de_casa",
        "aviso_previo", "ferias_proporcionais", "decimo_terceiro_prop",
        "multa_fgts", "custo_rescisao", "multiplo_reposicao",
        "custo_reposicao", "custo_total_desligamento",
    ]
    saida = desl[colunas].rename(columns={"detalhe": "motivo_desligamento"})
    num = saida.select_dtypes("number").columns
    return saida.round({c: 2 for c in num})
