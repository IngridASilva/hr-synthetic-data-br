"""
Motor de simulação longitudinal.

A base é construída mês a mês, aplicando eventos na ordem em que eles
acontecem no calendário de RH:

    dissídio -> ciclo de performance -> mérito -> promoção
    -> desligamento voluntário -> desligamento involuntário
    -> reestruturação -> admissões -> foto do mês

Essa ordem importa. Se você sortear desligamento antes do reajuste, a base
fica com gente desligada recebendo dissídio, e o forecast de folha do
Projeto 2 não fecha com a realidade.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import catalogs as cat
from .config import Params
from .hazard import hazard_involuntario, hazard_voluntario
from .people import gerar_colaborador, sortear_genero, sortear_raca


class Simulacao:
    def __init__(self, params: Params):
        self.p = params
        self.rng = np.random.default_rng(params.seed)
        self.meses = pd.date_range(
            start=f"{params.inicio}-01", end=f"{params.fim}-01", freq="MS"
        )
        self.colaboradores: dict[int, dict] = {}
        self.proxima_matricula = 100_001
        self.efeito_gestor: dict[int, float] = {}

        self.snapshots: list[dict] = []
        self.movimentacoes: list[dict] = []
        self.avaliacoes: list[dict] = []

        self._pesos_area = np.array([a.peso for a in cat.AREAS], dtype=float)
        self._pesos_area /= self._pesos_area.sum()

    # ----------------------------------------------------------------- setup
    def _sortear_area(self, genero: str | None = None,
                      raca: str | None = None) -> cat.Area:
        """Sorteia a área, opcionalmente com segregação ocupacional.

        Este é o mecanismo que gera gap salarial EXPLICADO: mulheres acabam
        sub-representadas em Tecnologia e Comercial, que pagam mais, e
        sobre-representadas em RH e Atendimento, que pagam menos. Nenhuma
        pessoa recebe menos pelo mesmo trabalho — e ainda assim o salário
        médio das mulheres fica abaixo. Distinguir isso de discriminação
        direta é a tarefa central da análise de equidade.
        """
        eq = self.p.bruto.get("equidade", {})
        if not eq.get("ativo") or genero is None:
            idx = int(self.rng.choice(len(cat.AREAS), p=self._pesos_area))
            return cat.AREAS[idx]

        seg = eq.get("segregacao_ocupacional", {})
        pesos = self._pesos_area.copy()
        for i, area in enumerate(cat.AREAS):
            regra = seg.get(area.familia, {})
            pesos[i] *= float(regra.get(genero, 1.0)) * float(regra.get(raca, 1.0))
        pesos /= pesos.sum()
        return cat.AREAS[int(self.rng.choice(len(cat.AREAS), p=pesos))]

    def _sortear_grade(self, area: cat.Area) -> int:
        grades = [g for g in cat.PIRAMIDE_PADRAO if g <= area.grade_max]
        pesos = np.array([cat.PIRAMIDE_PADRAO[g] for g in grades], dtype=float)
        pesos /= pesos.sum()
        return int(self.rng.choice(grades, p=pesos))

    def _salario_entrada(self, familia: str, grade: int,
                         genero: str | None = None,
                         raca: str | None = None) -> float:
        """Salário de entrada, com penalidade opcional no MESMO cargo.

        Este mecanismo gera gap NÃO EXPLICADO: duas pessoas no mesmo cargo,
        mesma família, mesmo grade, com salários diferentes. É o que a
        decomposição de Oaxaca-Blinder deve isolar.
        """
        rem = self.p["remuneracao"]
        compa = self.rng.normal(rem["entrada_media_compa"], rem["entrada_sd_compa"])
        compa = float(np.clip(compa, 0.70, 1.25))

        eq = self.p.bruto.get("equidade", {})
        if eq.get("ativo"):
            pen = eq.get("penalidade_entrada_compa", {})
            compa *= (1 - float(pen.get(genero, 0.0))) * (1 - float(pen.get(raca, 0.0)))

        return cat.mediana_salarial(familia, grade) * compa

    def _admitir(self, data: pd.Timestamp, area: cat.Area | None = None,
                 grade: int | None = None) -> dict:
        # Gênero e raça/cor são sorteados ANTES da área, porque a segregação
        # ocupacional é justamente o efeito do grupo sobre o destino.
        genero = sortear_genero(self.rng)
        raca = sortear_raca(self.rng)

        area = area or self._sortear_area(genero, raca)
        grade = grade if grade is not None else self._sortear_grade(area)
        matricula = self.proxima_matricula
        self.proxima_matricula += 1

        col = gerar_colaborador(
            self.rng,
            matricula=matricula,
            area=area,
            grade=grade,
            data_admissao=data,
            salario=self._salario_entrada(area.familia, grade, genero, raca),
            genero=genero,
            raca_cor=raca,
        )
        self.colaboradores[matricula] = col
        return col

    def _popular_inicial(self) -> None:
        """Cria o quadro existente no primeiro mês, com tempo de casa passado.

        Tempo de casa segue uma exponencial, o que reproduz a pirâmide real de
        uma empresa madura: muita gente nova, cauda longa de veteranos.
        """
        inicio = self.meses[0]
        n = int(self.p["headcount"]["inicial"])
        for _ in range(n):
            meses_casa = int(np.clip(self.rng.exponential(38), 0, 300))
            data_adm = inicio - pd.DateOffset(months=meses_casa)
            col = self._admitir(data_adm)
            # Reconstrói progressão passada de forma simplificada.
            promocoes = int(self.rng.binomial(meses_casa // 24, 0.55)) if meses_casa >= 24 else 0
            for _ in range(promocoes):
                if col["grade"] < cat.AREA_POR_ID[col["id_area"]].grade_max:
                    col["grade"] += 1
                    col["salario"] *= 1.0 + self.rng.uniform(0.08, 0.18)
                    col["num_promocoes"] += 1
            meses_desde_ult_promo = int(self.rng.uniform(0, min(meses_casa, 60) + 1))
            col["data_ultima_promocao"] = inicio - pd.DateOffset(
                months=meses_desde_ult_promo
            )
            # Correção inflacionária acumulada aproximada do período pregresso.
            col["salario"] *= (1.045) ** (meses_casa / 12.0)
            col["performance"] = int(
                self.rng.choice(
                    list(self.p["performance"]["distribuicao"].keys()),
                    p=list(self.p["performance"]["distribuicao"].values()),
                )
            )
        self._atribuir_gestores()

    # ------------------------------------------------------------- hierarquia
    def _atribuir_gestores(self) -> None:
        """Liga cada colaborador ao gestor da sua área (maior grade ativo)."""
        for area in cat.AREAS:
            membros = [
                c for c in self.colaboradores.values()
                if c["ativo"] and c["id_area"] == area.id_area
            ]
            if not membros:
                continue
            gestores = sorted(membros, key=lambda c: -c["grade"])
            lideres = gestores[: max(1, len(membros) // 12)]
            for lider in lideres:
                if lider["matricula"] not in self.efeito_gestor:
                    self.efeito_gestor[lider["matricula"]] = float(
                        self.rng.normal(0, 0.40)
                    )
            for c in membros:
                if c in lideres:
                    c["id_gestor"] = lideres[0]["matricula"]
                else:
                    c["id_gestor"] = int(
                        lideres[int(self.rng.integers(0, len(lideres)))]["matricula"]
                    )

    # ----------------------------------------------------------------- eventos
    def _aplicar_dissidio(self, data: pd.Timestamp) -> None:
        taxa = self.p.dissidio(data.year)
        if taxa == 0:
            return
        for col in self._ativos():
            area = cat.AREA_POR_ID[col["id_area"]]
            info = cat.SINDICATOS[area.diretoria]
            if info["mes_data_base"] != data.month:
                continue
            antigo = col["salario"]
            col["salario"] = round(antigo * (1 + taxa), 2)
            self._registrar_mov(
                col, data, "Dissídio", antigo, col["salario"],
                detalhe=info["sindicato"],
            )

    def _ciclo_performance(self, data: pd.Timestamp) -> None:
        dist = self.p["performance"]["distribuicao"]
        persist = float(self.p["performance"]["persistencia"])
        ratings = np.array(list(dist.keys()), dtype=int)
        probs = np.array(list(dist.values()), dtype=float)

        for col in self._ativos():
            if (data - col["data_admissao"]).days < 180:
                continue
            sorteio = self.rng.choice(ratings, p=probs)
            novo = persist * col["performance"] + (1 - persist) * sorteio
            col["performance"] = int(np.clip(round(novo), 1, 5))
            self.avaliacoes.append({
                "matricula": col["matricula"],
                "ciclo": data.year,
                "data_avaliacao": data.normalize(),
                "rating_performance": col["performance"],
                "rating_potencial": int(np.clip(
                    round(self.rng.normal(col["performance"], 0.9)), 1, 5
                )),
            })

    def _aplicar_merito(self, data: pd.Timestamp) -> None:
        tabela = self.p["remuneracao"]["merito_por_performance"]
        for col in self._ativos():
            if (data - col["data_admissao"]).days < 365:
                continue
            pct = float(tabela.get(col["performance"], 0.0))
            if pct <= 0:
                continue
            # Quem já está acima do teto da faixa recebe mérito reduzido.
            compa = self._compa_ratio(col, data)
            if compa > 1.15:
                pct *= 0.4
            antigo = col["salario"]
            col["salario"] = round(antigo * (1 + pct), 2)
            col["data_ultimo_merito"] = data.normalize()
            self._registrar_mov(col, data, "Mérito", antigo, col["salario"],
                                detalhe=f"rating {col['performance']}")

    def _aplicar_promocoes(self, data: pd.Timestamp) -> None:
        regra = self.p["promocao"]
        rem = self.p["remuneracao"]
        for col in self._ativos():
            area = cat.AREA_POR_ID[col["id_area"]]
            if col["grade"] >= area.grade_max:
                continue
            meses_cargo = self._meses_entre(col["data_ultima_promocao"], data)
            if meses_cargo < regra["meses_minimos_no_cargo"]:
                continue
            if col["performance"] < regra["performance_minima"]:
                continue
            prob = cat.NIVEL_POR_GRADE[col["grade"]].prob_promocao_mes
            eq = self.p.bruto.get("equidade", {})
            if eq.get("ativo"):
                # Teto de vidro: a penalidade é pequena no mês e enorme na
                # carreira. Uma taxa 22% menor por 10 anos vira diferença
                # estrutural de senioridade.
                mult = eq.get("multiplicador_promocao", {})
                prob *= float(mult.get(col["genero"], 1.0)) \
                    * float(mult.get(col["raca_cor"], 1.0))
            if self.rng.random() > prob:
                continue

            antigo_grade = col["grade"]
            antigo_sal = col["salario"]
            col["grade"] += 1
            col["salario"] = round(
                antigo_sal * (1 + self.rng.uniform(
                    rem["salto_promocao_min"], rem["salto_promocao_max"]
                )), 2
            )
            col["data_ultima_promocao"] = data.normalize()
            col["num_promocoes"] += 1
            self._registrar_mov(
                col, data, "Promoção", antigo_sal, col["salario"],
                detalhe=f"grade {antigo_grade} -> {col['grade']}",
            )

    def _aplicar_desligamentos(self, data: pd.Timestamp) -> None:
        choque = self.p.choque_mercado(data.year)
        for col in list(self._ativos()):
            meses_casa = self._meses_entre(col["data_admissao"], data)
            idade = self._meses_entre(col["data_nascimento"], data) / 12.0
            he = col["horas_extras_base"] * float(np.clip(self.rng.normal(1, 0.3), 0, 3))

            p_vol = hazard_voluntario(
                meses_casa=meses_casa,
                meses_sem_promocao=self._meses_entre(col["data_ultima_promocao"], data),
                compa_ratio=self._compa_ratio(col, data),
                idade=idade,
                performance=col["performance"],
                modelo_trabalho=col["modelo_trabalho"],
                distancia_km=col["distancia_km"],
                horas_extras=he,
                grade=col["grade"],
                efeito_gestor=self.efeito_gestor.get(col["id_gestor"], 0.0),
                mes=data.month,
                choque_externo=choque,
            )
            if self.rng.random() < p_vol:
                self._desligar(col, data, voluntario=True)
                continue

            p_inv = hazard_involuntario(
                performance=col["performance"],
                meses_casa=meses_casa,
                grade=col["grade"],
            )
            if self.rng.random() < p_inv:
                self._desligar(col, data, voluntario=False)

    def _aplicar_reestruturacao(self, data: pd.Timestamp) -> None:
        for evento in self.p["turnover"]["reestruturacoes"]:
            if pd.Timestamp(evento["mes"] + "-01") != data:
                continue
            alvo = [c for c in self._ativos() if c["id_area"] == evento["id_area"]]
            n = int(len(alvo) * float(evento["percentual"]))
            if n == 0:
                continue
            # O corte não é aleatório: pondera desempenho baixo.
            pesos = np.array([1.0 / max(c["performance"], 1) for c in alvo])
            pesos /= pesos.sum()
            escolhidos = self.rng.choice(len(alvo), size=n, replace=False, p=pesos)
            for i in escolhidos:
                self._desligar(
                    alvo[int(i)], data, voluntario=False,
                    motivo="Dispensa sem justa causa - reestruturação",
                )

    def _aplicar_admissoes(self, data: pd.Timestamp) -> None:
        alvo = self._headcount_alvo(data)
        atual = len(list(self._ativos()))
        vagas = alvo - atual
        if vagas <= 0:
            return
        # Contrata em lotes, com ruído de time-to-fill.
        contratar = int(np.clip(self.rng.binomial(vagas, 0.55), 0, vagas))
        for _ in range(contratar):
            self._admitir(data)
        if contratar:
            self._atribuir_gestores()

    # ----------------------------------------------------------------- helpers
    def _ativos(self):
        return (c for c in self.colaboradores.values() if c["ativo"])

    @staticmethod
    def _meses_entre(inicio: pd.Timestamp, fim: pd.Timestamp) -> float:
        return max(0.0, (fim - inicio).days / 30.44)

    def indice_mercado(self, data: pd.Timestamp) -> float:
        """Correção acumulada das faixas de mercado desde o início da série.

        Sem isso o compa-ratio da base inteira derivaria para cima ano após
        ano, porque salário sobe com dissídio e mérito enquanto a faixa
        ficaria congelada. Empresa real que não atualiza tabela salarial tem
        exatamente esse problema - aqui ele é explícito e configurável.
        """
        fator = 1.0
        for ano in range(self.meses[0].year, data.year):
            fator *= 1 + self.p.dissidio(ano)
        return fator

    def _compa_ratio(self, col: dict, data: pd.Timestamp) -> float:
        mediana = cat.mediana_salarial(col["familia_cargo"], col["grade"])
        return col["salario"] / (mediana * self.indice_mercado(data))

    def _headcount_alvo(self, data: pd.Timestamp) -> int:
        base = int(self.p["headcount"]["inicial"])
        fator = 1.0
        for ano in range(self.meses[0].year, data.year):
            fator *= 1 + self.p.crescimento(ano)
        fator *= (1 + self.p.crescimento(data.year)) ** ((data.month - 1) / 12.0)
        return int(base * fator)

    def _desligar(self, col: dict, data: pd.Timestamp, *, voluntario: bool,
                  motivo: str | None = None) -> None:
        col["ativo"] = False
        col["data_desligamento"] = data.normalize()
        col["tipo_desligamento"] = "Voluntário" if voluntario else "Involuntário"
        if motivo is None:
            pool = cat.MOTIVOS_VOLUNTARIO if voluntario else cat.MOTIVOS_INVOLUNTARIO
            motivo = str(self.rng.choice(pool))
        col["motivo_desligamento"] = motivo
        self._registrar_mov(col, data, "Desligamento", col["salario"],
                            col["salario"], detalhe=motivo)

    def _registrar_mov(self, col: dict, data: pd.Timestamp, tipo: str,
                       sal_antigo: float, sal_novo: float, detalhe: str = "") -> None:
        self.movimentacoes.append({
            "matricula": col["matricula"],
            "data_evento": data.normalize(),
            "tipo_evento": tipo,
            "id_area": col["id_area"],
            "grade": col["grade"],
            "salario_anterior": round(sal_antigo, 2),
            "salario_novo": round(sal_novo, 2),
            "variacao_pct": round(sal_novo / sal_antigo - 1, 6) if sal_antigo else 0.0,
            "detalhe": detalhe,
        })

    def _tirar_foto(self, data: pd.Timestamp) -> None:
        """Snapshot mensal: a granularidade que alimenta o fato do Power BI."""
        for col in self._ativos():
            self.snapshots.append({
                "id_mes": int(data.strftime("%Y%m")),
                "data_referencia": data.normalize(),
                "matricula": col["matricula"],
                "id_area": col["id_area"],
                "grade": col["grade"],
                "familia_cargo": col["familia_cargo"],
                "id_gestor": col["id_gestor"],
                "modelo_trabalho": col["modelo_trabalho"],
                "salario": round(col["salario"], 2),
                "compa_ratio": round(self._compa_ratio(col, data), 4),
                "performance": col["performance"],
                "meses_de_casa": round(self._meses_entre(col["data_admissao"], data), 1),
                "meses_sem_promocao": round(
                    self._meses_entre(col["data_ultima_promocao"], data), 1
                ),
                "num_promocoes": col["num_promocoes"],
                "idade": int(self._meses_entre(col["data_nascimento"], data) // 12),
                "horas_extras": round(
                    col["horas_extras_base"]
                    * float(np.clip(self.rng.normal(1, 0.3), 0, 3)), 1
                ),
            })

    # -------------------------------------------------------------------- run
    def executar(self) -> "Simulacao":
        self._popular_inicial()
        for data in self.meses:
            if data.month == self.p["performance"]["mes_ciclo"]:
                self._ciclo_performance(data)
            self._aplicar_dissidio(data)
            if data.month == self.p["remuneracao"]["mes_ciclo_merito"]:
                self._aplicar_merito(data)
            self._aplicar_promocoes(data)
            self._aplicar_desligamentos(data)
            self._aplicar_reestruturacao(data)
            self._aplicar_admissoes(data)
            self._tirar_foto(data)
        return self
