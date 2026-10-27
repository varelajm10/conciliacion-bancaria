"""Motor de conciliación bancaria: cruza movimientos del banco contra facturas abiertas.

Aplica reglas en cascada, de la más segura a la más flexible. Cada movimiento y cada
factura se usan una sola vez, y cada match queda documentado con la regla que lo
generó, un puntaje de confianza y la diferencia de importe.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz

COLUMNAS_BANCO = ["id_mov", "fecha", "descripcion", "importe"]
COLUMNAS_FACTURAS = ["nro_factura", "cliente", "cuit", "vencimiento", "importe"]


@dataclass
class Parametros:
    """Tolerancias del motor. Los valores por defecto sirven para la mayoría de las pymes."""

    tolerancia_importe: float = 1.0  # diferencia máxima en $ para considerar dos importes iguales
    ventana_dias: int = 45  # días máximos entre vencimiento y fecha de pago
    similitud_minima: int = 80  # 0-100, similitud mínima entre nombre de cliente y descripción
    max_facturas_agrupadas: int = 3  # cuántas facturas puede cubrir un solo pago
    permitir_parciales: bool = True


@dataclass
class Resultado:
    conciliados: pd.DataFrame
    sin_identificar: pd.DataFrame
    pendientes: pd.DataFrame
    resumen: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """Mayúsculas, sin acentos, sin signos y sin formas societarias (SA, SRL, etc.)."""
    if not isinstance(texto, str):
        return ""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9 ]", " ", texto.upper())
    texto = re.sub(r"\b(S ?A|S ?R ?L|SAS|SAU|SACI|LTDA|INC|LLC)\b", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def preparar_banco(df: pd.DataFrame) -> pd.DataFrame:
    faltan = set(COLUMNAS_BANCO) - set(df.columns)
    if faltan:
        raise ValueError(f"Al extracto bancario le faltan columnas: {sorted(faltan)}")
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"], dayfirst=True)
    df["importe"] = pd.to_numeric(df["importe"]).round(2)
    df = df[df["importe"] > 0]  # solo créditos (cobros)
    df["desc_norm"] = df["descripcion"].map(normalizar_texto)
    df["desc_digitos"] = df["descripcion"].map(solo_digitos)
    return df.reset_index(drop=True)


def preparar_facturas(df: pd.DataFrame) -> pd.DataFrame:
    faltan = set(COLUMNAS_FACTURAS) - set(df.columns)
    if faltan:
        raise ValueError(f"Al listado de facturas le faltan columnas: {sorted(faltan)}")
    df = df.copy()
    df["vencimiento"] = pd.to_datetime(df["vencimiento"], dayfirst=True)
    df["importe"] = pd.to_numeric(df["importe"]).round(2)
    df["cliente_norm"] = df["cliente"].map(normalizar_texto)
    df["cuit_digitos"] = df["cuit"].map(solo_digitos)
    df["nro_digitos"] = df["nro_factura"].map(solo_digitos)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

class Conciliador:
    def __init__(self, banco: pd.DataFrame, facturas: pd.DataFrame, params: Parametros | None = None):
        self.p = params or Parametros()
        self.banco = preparar_banco(banco)
        self.facturas = preparar_facturas(facturas)
        self.movs_usados: set[int] = set()
        self.facts_usadas: set[int] = set()
        self.matches: list[dict] = []

    # -- utilidades -----------------------------------------------------------
    def _importes_iguales(self, a: float, b: float) -> bool:
        return abs(a - b) <= self.p.tolerancia_importe

    def _en_ventana(self, fecha_pago, vencimiento) -> bool:
        return abs((fecha_pago - vencimiento).days) <= self.p.ventana_dias

    def _similitud(self, mov, fact) -> int:
        if not fact["cliente_norm"] or not mov["desc_norm"]:
            return 0
        return int(fuzz.partial_ratio(fact["cliente_norm"], mov["desc_norm"]))

    def _menciona_cuit(self, mov, fact) -> bool:
        return len(fact["cuit_digitos"]) >= 11 and fact["cuit_digitos"] in mov["desc_digitos"]

    def _menciona_factura(self, mov, fact) -> bool:
        nro = fact["nro_factura"].upper().replace(" ", "")
        desc = str(mov["descripcion"]).upper().replace(" ", "")
        if nro and nro in desc:
            return True
        # número sin ceros a la izquierda, p. ej. "FC 1523" para "A-0001-00001523"
        corto = solo_digitos(re.split(r"[-\s]", str(fact["nro_factura"]).strip())[-1]).lstrip("0")
        return len(corto) >= 4 and re.search(rf"(?<!\d){corto}(?!\d)", str(mov["descripcion"])) is not None

    def _libres(self):
        movs = self.banco[~self.banco.index.isin(self.movs_usados)]
        facts = self.facturas[~self.facturas.index.isin(self.facts_usadas)]
        return movs, facts

    def _registrar(self, i_mov: int, i_facts: list[int], regla: str, confianza: int):
        mov = self.banco.loc[i_mov]
        facts = self.facturas.loc[i_facts]
        total_facturas = round(float(facts["importe"].sum()), 2)
        for i_f in i_facts:
            f = self.facturas.loc[i_f]
            self.matches.append(
                {
                    "id_mov": mov["id_mov"],
                    "fecha_pago": mov["fecha"].date(),
                    "descripcion_banco": mov["descripcion"],
                    "importe_banco": mov["importe"],
                    "nro_factura": f["nro_factura"],
                    "cliente": f["cliente"],
                    "importe_factura": f["importe"],
                    "diferencia": round(float(mov["importe"]) - total_facturas, 2) if i_f == i_facts[0] else 0.0,
                    "regla": regla,
                    "confianza": confianza,
                }
            )
        self.movs_usados.add(i_mov)
        self.facts_usadas.update(i_facts)

    # -- reglas (de la más segura a la más flexible) ----------------------------
    def regla_referencia(self):
        """El banco menciona el número de factura y el importe coincide."""
        movs, facts = self._libres()
        for i_m, mov in movs.iterrows():
            for i_f, f in facts.iterrows():
                if i_f in self.facts_usadas:
                    continue
                if self._menciona_factura(mov, f) and self._importes_iguales(mov["importe"], f["importe"]):
                    self._registrar(i_m, [i_f], "Nº de factura + importe", 100)
                    break

    def regla_cuit(self):
        """El banco menciona el CUIT del cliente y el importe coincide con una sola factura."""
        movs, facts = self._libres()
        for i_m, mov in movs.iterrows():
            cands = [
                i_f for i_f, f in facts.iterrows()
                if i_f not in self.facts_usadas
                and self._menciona_cuit(mov, f)
                and self._importes_iguales(mov["importe"], f["importe"])
            ]
            if cands:
                # si hay varias, la de vencimiento más cercano al pago
                i_f = min(cands, key=lambda i: abs((mov["fecha"] - self.facturas.loc[i, "vencimiento"]).days))
                self._registrar(i_m, [i_f], "CUIT + importe", 95)

    def regla_nombre_importe(self):
        """Importe igual, nombre parecido y fecha razonable. Exige un único candidato."""
        movs, facts = self._libres()
        for i_m, mov in movs.iterrows():
            cands = []
            for i_f, f in facts.iterrows():
                if i_f in self.facts_usadas or not self._importes_iguales(mov["importe"], f["importe"]):
                    continue
                if not self._en_ventana(mov["fecha"], f["vencimiento"]):
                    continue
                sim = self._similitud(mov, f)
                if sim >= self.p.similitud_minima:
                    cands.append((i_f, sim))
            if len(cands) == 1:
                i_f, sim = cands[0]
                self._registrar(i_m, [i_f], "Nombre + importe (difuso)", min(90, 60 + sim // 4))

    def regla_pago_agrupado(self):
        """Un solo pago cancela varias facturas del mismo cliente."""
        movs, facts = self._libres()
        for i_m, mov in movs.iterrows():
            del_cliente = [
                i_f for i_f, f in facts.iterrows()
                if i_f not in self.facts_usadas
                and (self._menciona_cuit(mov, f) or self._similitud(mov, f) >= self.p.similitud_minima)
            ]
            hallado = None
            for n in range(2, self.p.max_facturas_agrupadas + 1):
                for combo in itertools.combinations(del_cliente, n):
                    total = self.facturas.loc[list(combo), "importe"].sum()
                    if self._importes_iguales(mov["importe"], total):
                        hallado = list(combo)
                        break
                if hallado:
                    break
            if hallado:
                self._registrar(i_m, hallado, f"Pago agrupado ({len(hallado)} facturas)", 85)

    def regla_parcial(self):
        """Pago menor a la factura, del mismo cliente: se marca como parcial para revisar."""
        if not self.p.permitir_parciales:
            return
        movs, facts = self._libres()
        for i_m, mov in movs.iterrows():
            cands = []
            for i_f, f in facts.iterrows():
                if i_f in self.facts_usadas or mov["importe"] >= f["importe"]:
                    continue
                identificado = self._menciona_cuit(mov, f) or self._menciona_factura(mov, f)
                sim = self._similitud(mov, f)
                if identificado or sim >= self.p.similitud_minima:
                    cands.append((i_f, 100 if identificado else sim))
            if cands:
                # mejor identificación primero; ante empate, la factura más vieja (criterio FIFO)
                i_f, _ = max(cands, key=lambda c: (c[1], -self.facturas.loc[c[0], "vencimiento"].value))
                self._registrar(i_m, [i_f], "Pago parcial (revisar)", 60)

    # -- ejecución ------------------------------------------------------------
    def ejecutar(self) -> Resultado:
        for regla in (
            self.regla_referencia,
            self.regla_cuit,
            self.regla_nombre_importe,
            self.regla_pago_agrupado,
            self.regla_parcial,
        ):
            regla()

        conciliados = pd.DataFrame(self.matches)
        sin_id = self.banco[~self.banco.index.isin(self.movs_usados)][COLUMNAS_BANCO].copy()
        sin_id["fecha"] = sin_id["fecha"].dt.date
        pendientes = self.facturas[~self.facturas.index.isin(self.facts_usadas)][COLUMNAS_FACTURAS].copy()
        pendientes["vencimiento"] = pendientes["vencimiento"].dt.date

        total_banco = float(self.banco["importe"].sum())
        imp_conc = float(self.banco.loc[list(self.movs_usados), "importe"].sum()) if self.movs_usados else 0.0
        resumen = {
            "movimientos_banco": len(self.banco),
            "movimientos_conciliados": len(self.movs_usados),
            "facturas_abiertas": len(self.facturas),
            "facturas_conciliadas": len(self.facts_usadas),
            "importe_banco": round(total_banco, 2),
            "importe_conciliado": round(imp_conc, 2),
            "importe_sin_identificar": round(float(sin_id["importe"].sum()), 2),
            "pct_conciliado": round(100 * imp_conc / total_banco, 1) if total_banco else 0.0,
            "a_revisar": int((conciliados["confianza"] < 80).sum()) if not conciliados.empty else 0,
        }
        if not conciliados.empty:
            resumen["por_regla"] = conciliados.drop_duplicates("id_mov")["regla"].value_counts().to_dict()
        return Resultado(conciliados, sin_id.reset_index(drop=True), pendientes.reset_index(drop=True), resumen)


def conciliar(banco: pd.DataFrame, facturas: pd.DataFrame, params: Parametros | None = None) -> Resultado:
    """Atajo: conciliar(banco_df, facturas_df) -> Resultado."""
    return Conciliador(banco, facturas, params).ejecutar()
