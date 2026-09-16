"""
Testes de invariantes.

A pergunta que estes testes respondem não é "o código roda", e sim "a base
faz sentido como base de RH". São as mesmas checagens que você faria ao
receber um extract do HRIS de um cliente.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hrsynth.config import Params
from hrsynth.export import construir
from hrsynth.hazard import hazard_voluntario
from hrsynth.simulation import Simulacao


@pytest.fixture(scope="module")
def base():
    p = Params.from_yaml("config/params.yaml")
    p.bruto["headcount"]["inicial"] = 400        # amostra menor, CI rápida
    p.bruto["periodo"]["fim"] = "2022-12"
    sim = Simulacao(p).executar()
    return construir(sim, p), p


# --------------------------------------------------------------- integridade
def test_chaves_dos_fatos_existem_nas_dimensoes(base):
    t, _ = base
    assert set(t["fato_headcount_mensal"]["matricula"]) <= set(
        t["dim_colaborador"]["matricula"]
    )
    assert set(t["fato_headcount_mensal"]["id_area"]) <= set(t["dim_area"]["id_area"])
    assert set(t["fato_headcount_mensal"]["id_cargo"]) <= set(t["dim_cargo"]["id_cargo"])


def test_grao_do_fato_e_unico(base):
    t, _ = base
    f = t["fato_headcount_mensal"]
    assert not f.duplicated(subset=["matricula", "id_mes"]).any()
    assert len(t["fato_folha_mensal"]) == len(f)


def test_calendario_cobre_todo_o_periodo(base):
    t, _ = base
    assert set(t["fato_headcount_mensal"]["id_mes"]) <= set(t["dim_calendario"]["id_mes"])


# ------------------------------------------------------------------ coerência
def test_colaborador_nao_aparece_apos_desligamento(base):
    t, _ = base
    f = t["fato_headcount_mensal"]
    d = t["dim_colaborador"].dropna(subset=["data_desligamento"])
    m = f.merge(d[["matricula", "data_desligamento"]], on="matricula")
    assert (m["data_referencia"] <= m["data_desligamento"]).all()


def test_admissao_anterior_ao_desligamento(base):
    t, _ = base
    d = t["dim_colaborador"].dropna(subset=["data_desligamento"])
    assert (d["data_admissao"] <= d["data_desligamento"]).all()


def test_nenhum_menor_de_idade(base):
    t, _ = base
    assert t["fato_headcount_mensal"]["idade"].min() >= 18


def test_salario_positivo_e_sem_nulos(base):
    t, _ = base
    f = t["fato_headcount_mensal"]
    assert f["salario"].gt(0).all()
    assert not f[["salario", "compa_ratio", "grade"]].isna().any().any()


def test_grade_nunca_regride(base):
    """Promoção sobe, nunca desce. Rebaixamento não está modelado."""
    t, _ = base
    f = t["fato_headcount_mensal"].sort_values(["matricula", "id_mes"])
    delta = f.groupby("matricula")["grade"].diff().dropna()
    assert delta.min() >= 0


def test_promocao_registra_variacao_positiva(base):
    t, _ = base
    m = t["fato_movimentacao"]
    promo = m[m["tipo_evento"] == "Promoção"]
    assert promo["variacao_pct"].gt(0).all()


# ------------------------------------------------------------------ financeiro
def test_custo_total_maior_que_salario(base):
    t, _ = base
    f = t["fato_folha_mensal"]
    assert (f["custo_total"] > f["salario"]).all()
    # Faixa larga de propósito: benefício é valor fixo, então o custo total
    # sobre salário é regressivo. Assistente custa proporcionalmente mais que
    # gerente. Isso é real e aparece no dashboard de folha.
    assert f["fator_custo_sobre_salario"].between(1.4, 3.4).all()
    assert f["fator_custo_sobre_salario"].median() < 2.2


def test_multa_fgts_apenas_em_involuntario(base):
    t, _ = base
    d = t["fato_desligamento_custo"]
    if d.empty:
        pytest.skip("sem desligamentos na janela curta de teste")
    assert d.loc[d["tipo_desligamento"] == "Voluntário", "multa_fgts"].eq(0).all()


# --------------------------------------------------------- realismo estatístico
def test_turnover_em_faixa_plausivel(base):
    t, _ = base
    f = t["fato_headcount_mensal"]
    d = t["dim_colaborador"].dropna(subset=["data_desligamento"])
    hc_medio = f.groupby("id_mes")["matricula"].count().mean()
    meses = f["id_mes"].nunique()
    turnover_anual = len(d) / hc_medio / (meses / 12)
    assert 0.08 <= turnover_anual <= 0.35, f"turnover anual = {turnover_anual:.3f}"


def test_hazard_responde_ao_compa_ratio():
    """Quem ganha abaixo da faixa tem que ter risco maior. Se este teste
    quebrar, o sinal que o modelo do Projeto 1 deveria aprender sumiu."""
    comum = dict(
        meses_casa=24, meses_sem_promocao=24, idade=33, performance=4,
        modelo_trabalho="Híbrido", distancia_km=15, horas_extras=8,
        grade=3, efeito_gestor=0.0, mes=6,
    )
    baixo = hazard_voluntario(compa_ratio=0.80, **comum)
    alto = hazard_voluntario(compa_ratio=1.15, **comum)
    assert baixo > alto * 1.5


def test_hazard_responde_a_estagnacao():
    comum = dict(
        meses_casa=48, compa_ratio=1.0, idade=33, performance=4,
        modelo_trabalho="Híbrido", distancia_km=15, horas_extras=8,
        grade=3, efeito_gestor=0.0, mes=6,
    )
    assert hazard_voluntario(meses_sem_promocao=48, **comum) > \
        hazard_voluntario(meses_sem_promocao=6, **comum)


def test_reprodutibilidade():
    """Mesma seed, mesma base. Sem isso o portfólio não é auditável."""
    p = Params.from_yaml("config/params.yaml")
    p.bruto["headcount"]["inicial"] = 200
    p.bruto["periodo"]["fim"] = "2021-12"
    a = pd.DataFrame(Simulacao(p).executar().snapshots)
    b = pd.DataFrame(Simulacao(p).executar().snapshots)
    pd.testing.assert_frame_equal(a, b)
