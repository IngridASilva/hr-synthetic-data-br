"""CLI: gera a base e imprime um relatório de sanidade.

O relatório existe porque base sintética sem conferência é ficção. Se o
turnover anual sair em 45% ou o fator de custo sobre salário em 1,1, os
parâmetros estão errados e o Projeto 2 vai nascer torto.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from .config import Params
from .export import construir, escrever
from .simulation import Simulacao


FAIXAS_ESPERADAS = {
    "turnover_total_anual": (0.12, 0.30),
    "turnover_voluntario_anual": (0.08, 0.22),
    "fator_custo_sobre_salario": (1.60, 2.10),
    "compa_ratio_medio": (0.90, 1.08),  # piso menor quando `equidade.ativo`
}


def relatorio_sanidade(tabelas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    snaps = tabelas["fato_headcount_mensal"]
    colabs = tabelas["dim_colaborador"]
    folha = tabelas["fato_folha_mensal"]

    hc = snaps.groupby("data_referencia")["matricula"].count()
    desl = colabs.dropna(subset=["data_desligamento"]).copy()
    desl["ano"] = desl["data_desligamento"].dt.year

    hc_medio_ano = snaps.assign(ano=snaps["data_referencia"].dt.year) \
        .groupby(["ano", "data_referencia"])["matricula"].count() \
        .groupby("ano").mean()

    por_ano = desl.groupby("ano").size() / hc_medio_ano
    vol = desl[desl["tipo_desligamento"] == "Voluntário"].groupby("ano").size() \
        / hc_medio_ano

    linhas = [
        ("meses_simulados", len(hc), ""),
        ("headcount_inicial", int(hc.iloc[0]), ""),
        ("headcount_final", int(hc.iloc[-1]), ""),
        ("colaboradores_unicos", len(colabs), ""),
        ("turnover_total_anual", round(por_ano.mean(), 4), "média dos anos"),
        ("turnover_voluntario_anual", round(vol.mean(), 4), "média dos anos"),
        ("pct_desligados_na_base", round((colabs["status"] == "Desligado").mean(), 4), ""),
        ("salario_mediano_final", round(
            snaps[snaps["data_referencia"] == snaps["data_referencia"].max()]
            ["salario"].median(), 2), ""),
        ("compa_ratio_medio", round(snaps["compa_ratio"].mean(), 4), "alvo ~0.95-1.05"),
        ("fator_custo_sobre_salario", round(
            folha["fator_custo_sobre_salario"].mean(), 4), "custo total / salário"),
        ("custo_folha_ultimo_mes", round(
            folha[folha["id_mes"] == folha["id_mes"].max()]["custo_total"].sum(), 2), ""),
    ]
    df = pd.DataFrame(linhas, columns=["metrica", "valor", "observacao"])
    df["status"] = df.apply(_avaliar, axis=1)
    return df


def _avaliar(linha) -> str:
    faixa = FAIXAS_ESPERADAS.get(linha["metrica"])
    if faixa is None:
        return "-"
    return "OK" if faixa[0] <= linha["valor"] <= faixa[1] else "FORA DA FAIXA"


def main() -> None:
    ap = argparse.ArgumentParser(description="Gerador de base sintética de RH (BR)")
    ap.add_argument("--config", default="config/params.yaml")
    ap.add_argument("--csv", action="store_true", help="exporta também em CSV")
    ap.add_argument("--seed", type=int, default=None, help="sobrescreve a seed")
    args = ap.parse_args()

    p = Params.from_yaml(args.config)
    if args.seed is not None:
        p.bruto["seed"] = args.seed
    if args.csv and "csv" not in p["saida"]["formatos"]:
        p.bruto["saida"]["formatos"].append("csv")

    t0 = time.perf_counter()
    sim = Simulacao(p).executar()
    tabelas = construir(sim, p)
    destino = escrever(tabelas, p)
    dur = time.perf_counter() - t0

    print(f"\nBase gerada em {destino.resolve()} ({dur:.1f}s)\n")
    print("Tabelas:")
    for nome, df in tabelas.items():
        print(f"  {nome:<28} {len(df):>9,} linhas  x {df.shape[1]:>2} colunas")

    print("\nRelatório de sanidade:")
    print(relatorio_sanidade(tabelas).to_string(index=False))


if __name__ == "__main__":
    main()
