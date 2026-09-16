"""Carregamento e validação dos parâmetros da simulação."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Params:
    """Wrapper fino sobre o YAML, com validação das premissas críticas."""

    bruto: dict[str, Any] = field(repr=False)

    @classmethod
    def from_yaml(cls, caminho: str | Path) -> "Params":
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = yaml.safe_load(f)
        p = cls(bruto=bruto)
        p.validar()
        return p

    def __getitem__(self, chave: str) -> Any:
        return self.bruto[chave]

    # -- atalhos mais usados -------------------------------------------------
    @property
    def seed(self) -> int:
        return int(self.bruto["seed"])

    @property
    def inicio(self) -> str:
        return self.bruto["periodo"]["inicio"]

    @property
    def fim(self) -> str:
        return self.bruto["periodo"]["fim"]

    def dissidio(self, ano: int) -> float:
        return float(self.bruto["remuneracao"]["dissidio_por_ano"].get(ano, 0.0))

    def choque_mercado(self, ano: int) -> float:
        return float(self.bruto["turnover"]["choque_mercado_por_ano"].get(ano, 0.0))

    def crescimento(self, ano: int) -> float:
        return float(self.bruto["headcount"]["crescimento_anual"].get(ano, 0.0))

    # -- validação -----------------------------------------------------------
    def validar(self) -> None:
        """Falha cedo e com mensagem clara. Premissa errada silenciosa é pior
        que exceção."""
        dist = self.bruto["performance"]["distribuicao"]
        soma = sum(dist.values())
        if abs(soma - 1.0) > 1e-6:
            raise ValueError(
                f"performance.distribuicao deve somar 1.0, somou {soma:.4f}"
            )

        if self.bruto["headcount"]["inicial"] < 100:
            raise ValueError(
                "headcount.inicial abaixo de 100 gera amostra instável para "
                "modelagem preditiva."
            )

        rem = self.bruto["remuneracao"]
        if rem["salto_promocao_min"] >= rem["salto_promocao_max"]:
            raise ValueError("salto_promocao_min deve ser menor que o max.")

        for r in self.bruto["turnover"]["reestruturacoes"]:
            if not 0 < r["percentual"] < 1:
                raise ValueError(
                    f"Percentual de reestruturação inválido: {r['percentual']}"
                )
