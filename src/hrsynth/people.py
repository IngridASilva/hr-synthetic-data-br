"""
Geração dos atributos cadastrais de um colaborador.

Regra de ouro: nada aqui é independente. Idade correlaciona com grade,
escolaridade correlaciona com grade, modelo de trabalho correlaciona com a
família de cargo. Base sintética com colunas independentes não serve para
testar modelo preditivo, porque o mundo real é cheio de confundimento.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from . import catalogs as cat

# Probabilidade de modelo de trabalho por família de cargo.
MODELO_POR_FAMILIA: dict[str, list[float]] = {
    # ordem: Presencial, Híbrido, Remoto
    "Tecnologia": [0.10, 0.45, 0.45],
    "Jurídico": [0.30, 0.55, 0.15],
    "Financeiro": [0.35, 0.55, 0.10],
    "Comercial": [0.45, 0.45, 0.10],
    "Marketing": [0.25, 0.55, 0.20],
    "Recursos Humanos": [0.40, 0.50, 0.10],
    "Operações": [0.90, 0.09, 0.01],
    "Atendimento": [0.50, 0.30, 0.20],
}

# Escolaridade condicionada ao grade (índices de cat.ESCOLARIDADES).
ESCOLARIDADE_POR_GRADE: dict[int, list[float]] = {
    1: [0.45, 0.30, 0.20, 0.04, 0.01],
    2: [0.15, 0.30, 0.45, 0.09, 0.01],
    3: [0.05, 0.15, 0.55, 0.23, 0.02],
    4: [0.02, 0.08, 0.53, 0.33, 0.04],
    5: [0.01, 0.04, 0.45, 0.42, 0.08],
    6: [0.01, 0.04, 0.45, 0.44, 0.06],
    7: [0.00, 0.02, 0.38, 0.52, 0.08],
    8: [0.00, 0.00, 0.28, 0.58, 0.14],
}

UFS = [
    ("SP", "São Paulo", 0.42),
    ("SP", "Campinas", 0.08),
    ("RJ", "Rio de Janeiro", 0.12),
    ("MG", "Belo Horizonte", 0.10),
    ("PR", "Curitiba", 0.07),
    ("RS", "Porto Alegre", 0.06),
    ("PE", "Recife", 0.05),
    ("BA", "Salvador", 0.05),
    ("SC", "Florianópolis", 0.05),
]


def _pseudonimo(rng: np.random.Generator) -> str:
    """Hash irreversível no lugar do documento.

    Na base sintética o CPF simplesmente não existe. Isso é intencional:
    o pipeline demonstra pseudonimização por padrão, que é o comportamento
    esperado quando a mesma arquitetura for apontada para dados reais.
    """
    semente = int(rng.integers(0, 2**62)).to_bytes(8, "big")
    return hashlib.sha256(semente).hexdigest()[:16]


def sortear_genero(rng: np.random.Generator) -> str:
    return str(rng.choice(cat.GENEROS, p=[0.47, 0.52, 0.01]))


def sortear_raca(rng: np.random.Generator) -> str:
    return str(rng.choice(cat.RACA_COR, p=[0.44, 0.33, 0.14, 0.03, 0.01, 0.05]))


def gerar_colaborador(
    rng: np.random.Generator,
    *,
    matricula: int,
    area: cat.Area,
    grade: int,
    data_admissao: pd.Timestamp,
    salario: float,
    genero: str | None = None,
    raca_cor: str | None = None,
) -> dict:
    genero = genero or sortear_genero(rng)
    if genero == "Feminino":
        nome = f"{rng.choice(cat.NOMES_F)} {rng.choice(cat.SOBRENOMES)}"
    elif genero == "Masculino":
        nome = f"{rng.choice(cat.NOMES_M)} {rng.choice(cat.SOBRENOMES)}"
    else:
        nome = f"{rng.choice(cat.NOMES_F + cat.NOMES_M)} {rng.choice(cat.SOBRENOMES)}"

    # Idade sobe com a senioridade, com ruído. Piso de 18 anos.
    idade = int(np.clip(rng.normal(23 + 3.4 * grade, 6.0), 18, 66))
    data_nascimento = data_admissao - pd.DateOffset(years=idade) - pd.Timedelta(
        days=int(rng.integers(0, 365))
    )

    escol = rng.choice(cat.ESCOLARIDADES, p=ESCOLARIDADE_POR_GRADE[grade])
    modelo = rng.choice(cat.MODELOS_TRABALHO, p=MODELO_POR_FAMILIA[area.familia])

    idx_local = rng.choice(len(UFS), p=[u[2] for u in UFS])
    uf, cidade, _ = UFS[idx_local]

    # Quem é remoto tende a morar mais longe do escritório.
    base_dist = 34.0 if modelo == "Remoto" else 14.0
    distancia = float(np.clip(rng.gamma(2.0, base_dist / 2.0), 0.5, 160.0))

    return {
        "matricula": matricula,
        "nome": nome,
        "hash_documento": _pseudonimo(rng),
        "data_nascimento": data_nascimento.normalize(),
        "genero": genero,
        # O sorteio fica NESTA posição, e não junto com o gênero, porque a
        # ordem de consumo do gerador aleatório define toda a série. Mover uma
        # linha daqui muda a base inteira mesmo consumindo a mesma quantidade
        # de números.
        "raca_cor": raca_cor or sortear_raca(rng),
        "escolaridade": escol,
        "estado_civil": rng.choice(cat.ESTADO_CIVIL, p=[0.44, 0.44, 0.10, 0.02]),
        "num_dependentes": int(rng.poisson(0.8)),
        "uf": uf,
        "cidade": cidade,
        "distancia_km": round(distancia, 1),
        "modelo_trabalho": modelo,
        "id_area": area.id_area,
        "familia_cargo": area.familia,
        "grade": grade,
        "salario": round(salario, 2),
        "data_admissao": data_admissao.normalize(),
        "data_ultima_promocao": data_admissao.normalize(),
        "data_ultimo_merito": data_admissao.normalize(),
        "performance": 3,
        "horas_extras_base": float(np.clip(rng.gamma(1.5, 5.0), 0, 60)),
        "ativo": True,
        "data_desligamento": pd.NaT,
        "motivo_desligamento": None,
        "tipo_desligamento": None,
        "id_gestor": None,
        "num_promocoes": 0,
    }


def faixa_etaria(idade: int) -> str:
    if idade <= 29:
        return "ate_29"
    if idade <= 39:
        return "30_39"
    if idade <= 49:
        return "40_49"
    return "50_mais"
