"""Exporta el resultado de la conciliación a un Excel listo para el cierre."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .core import Resultado

AZUL = PatternFill("solid", fgColor="1F3A5F")
VERDE = PatternFill("solid", fgColor="E3F4E8")
AMARILLO = PatternFill("solid", fgColor="FFF4D6")
ROJO = PatternFill("solid", fgColor="FDE4E1")
BLANCO_NEGRITA = Font(bold=True, color="FFFFFF")


def _formatear_hoja(ws, columnas_moneda: tuple[str, ...] = ()):
    for celda in ws[1]:
        celda.fill = AZUL
        celda.font = BLANCO_NEGRITA
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    encabezados = [c.value for c in ws[1]]
    for idx, nombre in enumerate(encabezados, start=1):
        letra = get_column_letter(idx)
        largo = max([len(str(nombre))] + [len(str(c.value or "")) for c in ws[letra][1:200]])
        ws.column_dimensions[letra].width = min(max(12, largo + 2), 55)
        if nombre in columnas_moneda:
            for c in ws[letra][1:]:
                c.number_format = '"$" #,##0.00'
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions


def exportar_excel(res: Resultado, ruta):
    """Escribe el Excel en una ruta o en un buffer (BytesIO). Devuelve lo mismo que recibe."""
    if isinstance(ruta, str):
        ruta = Path(ruta)
    r = res.resumen
    resumen = pd.DataFrame(
        [
            ("Movimientos del banco", r["movimientos_banco"]),
            ("Movimientos conciliados", r["movimientos_conciliados"]),
            ("Facturas abiertas", r["facturas_abiertas"]),
            ("Facturas conciliadas", r["facturas_conciliadas"]),
            ("Importe cobrado en banco", r["importe_banco"]),
            ("Importe conciliado", r["importe_conciliado"]),
            ("Importe sin identificar", r["importe_sin_identificar"]),
            ("% conciliado (por importe)", r["pct_conciliado"] / 100),
            ("Matches a revisar (confianza < 80)", r["a_revisar"]),
        ],
        columns=["Indicador", "Valor"],
    )

    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        resumen.to_excel(xw, sheet_name="Resumen", index=False)
        res.conciliados.to_excel(xw, sheet_name="Conciliados", index=False)
        res.sin_identificar.to_excel(xw, sheet_name="Banco sin identificar", index=False)
        res.pendientes.to_excel(xw, sheet_name="Facturas pendientes", index=False)

        ws = xw.sheets["Resumen"]
        _formatear_hoja(ws)
        for fila in ws.iter_rows(min_row=2):
            ind, val = fila
            if "Importe" in str(ind.value):
                val.number_format = '"$" #,##0.00'
            elif "%" in str(ind.value):
                val.number_format = "0.0%"

        ws = xw.sheets["Conciliados"]
        _formatear_hoja(ws, ("importe_banco", "importe_factura", "diferencia"))
        if ws.max_row > 1:
            col_conf = [c.value for c in ws[1]].index("confianza") + 1
            for fila in ws.iter_rows(min_row=2):
                conf = fila[col_conf - 1].value or 0
                color = VERDE if conf >= 90 else AMARILLO if conf >= 80 else ROJO
                for c in fila:
                    c.fill = color

        _formatear_hoja(xw.sheets["Banco sin identificar"], ("importe",))
        _formatear_hoja(xw.sheets["Facturas pendientes"], ("importe",))
    return ruta
