"""
Montagem do esquema estrela e escrita em disco.

O modelo entregue já está desenhado para o Power BI: dimensões pequenas com
chave única, fatos no grão mensal, e nenhuma relação muitos-para-muitos.
Nada de tabela larga única - isso mata a compressão do VertiPaq e engessa o
DAX.

    dim_calendario (grão dia)
    dim_colaborador
    dim_area
    dim_cargo
    fato_headcount_mensal     grão: matrícula x mês
    fato_folha_mensal         grão: matrícula x mês
    fato_movimentacao         grão: evento
    fato_desligamento_custo   grão: desligamento
    dim_avaliacao             grão: matrícula x ciclo
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import catalogs as cat
from .config import Params
from .hazard import exportar_coeficientes
from .payroll import calcular_custo_desligamento, calcular_folha
from .simulation import Simulacao


def dim_area() -> pd.DataFrame:
    return pd.DataFrame([{
        "id_area": a.id_area,
        "diretoria": a.diretoria,
        "gerencia": a.gerencia,
        "familia_cargo": a.familia,
        "centro_custo": a.centro_custo,
        "criticidade": a.criticidade,
        "sindicato": cat.SINDICATOS[a.diretoria]["sindicato"],
        "mes_data_base": cat.SINDICATOS[a.diretoria]["mes_data_base"],
    } for a in cat.AREAS])


def dim_cargo() -> pd.DataFrame:
    linhas = []
    for familia, mult in cat.FAMILIAS.items():
        for nivel in cat.NIVEIS:
            mediana = cat.mediana_salarial(familia, nivel.grade)
            linhas.append({
                "id_cargo": f"{familia[:3].upper()}-{nivel.grade}",
                "familia_cargo": familia,
                "grade": nivel.grade,
                "nivel": nivel.nome,
                "cargo": f"{nivel.nome} de {familia}",
                "faixa_minima": round(mediana * (1 - nivel.amplitude), 2),
                "faixa_mediana": round(mediana, 2),
                "faixa_maxima": round(mediana * (1 + nivel.amplitude), 2),
                "multiplicador_familia": mult,
            })
    return pd.DataFrame(linhas)


def dim_faixa_salarial(p: Params, indice_por_ano: dict[int, float]) -> pd.DataFrame:
    """Faixa salarial vigente por ano. Referência para compa-ratio e para a
    análise de equidade do Projeto 3."""
    linhas = []
    for ano, indice in indice_por_ano.items():
        for familia in cat.FAMILIAS:
            for nivel in cat.NIVEIS:
                med = cat.mediana_salarial(familia, nivel.grade) * indice
                linhas.append({
                    "id_cargo": f"{familia[:3].upper()}-{nivel.grade}",
                    "ano": ano,
                    "faixa_minima": round(med * (1 - nivel.amplitude), 2),
                    "faixa_mediana": round(med, 2),
                    "faixa_maxima": round(med * (1 + nivel.amplitude), 2),
                })
    return pd.DataFrame(linhas)


def dim_calendario(inicio: str, fim: str) -> pd.DataFrame:
    datas = pd.date_range(f"{inicio}-01", pd.Timestamp(f"{fim}-01")
                          + pd.offsets.MonthEnd(0), freq="D")
    meses_pt = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    df = pd.DataFrame({"data": datas})
    df["id_data"] = df["data"].dt.strftime("%Y%m%d").astype(int)
    df["id_mes"] = df["data"].dt.strftime("%Y%m").astype(int)
    df["ano"] = df["data"].dt.year
    df["mes"] = df["data"].dt.month
    df["nome_mes"] = df["mes"].map(lambda m: meses_pt[m - 1])
    df["ano_mes"] = df["nome_mes"] + "/" + df["ano"].astype(str).str[-2:]
    df["trimestre"] = "T" + df["data"].dt.quarter.astype(str)
    df["semestre"] = "S" + ((df["data"].dt.quarter > 2).astype(int) + 1).astype(str)
    df["dia_semana"] = df["data"].dt.dayofweek
    df["eh_dia_util"] = df["dia_semana"] < 5
    df["ultimo_dia_mes"] = df["data"].dt.is_month_end
    return df


def dim_colaborador(sim: Simulacao) -> pd.DataFrame:
    campos = [
        "matricula", "nome", "hash_documento", "data_nascimento", "genero",
        "raca_cor", "escolaridade", "estado_civil", "num_dependentes", "uf",
        "cidade", "distancia_km", "data_admissao", "data_desligamento",
        "tipo_desligamento", "motivo_desligamento", "ativo",
    ]
    df = pd.DataFrame([{k: c[k] for k in campos} for c in sim.colaboradores.values()])
    df["status"] = df["ativo"].map({True: "Ativo", False: "Desligado"})
    return df.drop(columns=["ativo"])


def construir(sim: Simulacao, p: Params) -> dict[str, pd.DataFrame]:
    snaps = pd.DataFrame(sim.snapshots)
    movs = pd.DataFrame(sim.movimentacoes)
    colabs = dim_colaborador(sim)
    areas = dim_area()
    cargos = dim_cargo()

    # Chave para a dimensão cargo (relação por grade + família).
    snaps["id_cargo"] = (
        snaps["familia_cargo"].str[:3].str.upper() + "-" + snaps["grade"].astype(str)
    )

    folha = calcular_folha(snaps, p)
    custo_desl = calcular_custo_desligamento(movs, snaps, colabs, p, areas)

    return {
        "dim_calendario": dim_calendario(p.inicio, p.fim),
        "dim_colaborador": colabs,
        "dim_area": areas,
        "dim_cargo": cargos,
        "dim_faixa_salarial": dim_faixa_salarial(
            p,
            {ano: sim.indice_mercado(pd.Timestamp(f"{ano}-01-01"))
             for ano in range(sim.meses[0].year, sim.meses[-1].year + 1)},
        ),
        "fato_headcount_mensal": snaps,
        "fato_folha_mensal": folha,
        "fato_movimentacao": movs,
        "fato_desligamento_custo": custo_desl,
        "dim_avaliacao": pd.DataFrame(sim.avaliacoes),
        # Verdade-base do efeito de liderança. NÃO é feature: é gabarito.
        # Fica fora do fato de propósito, para você não treinar com vazamento.
        "ground_truth_efeito_gestor": pd.DataFrame(
            [{"id_gestor": k, "efeito_latente_log_odds": round(v, 4)}
             for k, v in sim.efeito_gestor.items()]
        ),
    }


def escrever(tabelas: dict[str, pd.DataFrame], p: Params) -> Path:
    destino = Path(p["saida"]["diretorio"])
    destino.mkdir(parents=True, exist_ok=True)
    formatos = p["saida"]["formatos"]

    for nome, df in tabelas.items():
        if "parquet" in formatos:
            df.to_parquet(destino / f"{nome}.parquet", index=False)
        if "csv" in formatos:
            df.to_csv(destino / f"{nome}.csv", index=False, encoding="utf-8-sig")

    with open(destino / "ground_truth_coeficientes.json", "w", encoding="utf-8") as f:
        json.dump(exportar_coeficientes(), f, ensure_ascii=False, indent=2)

    return destino
