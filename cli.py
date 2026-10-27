"""Uso:
    python cli.py --banco data/extracto_banco.csv --facturas data/facturas_abiertas.csv --salida conciliacion.xlsx
    python cli.py --demo        # genera datos de ejemplo y concilia
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from conciliador import Parametros, conciliar, exportar_excel
from conciliador.demo import guardar


def leer(ruta: str) -> pd.DataFrame:
    p = Path(ruta)
    return pd.read_excel(p) if p.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(p)


def main() -> None:
    ap = argparse.ArgumentParser(description="Conciliación bancaria automática de cuentas por cobrar")
    ap.add_argument("--banco", help="Extracto bancario (CSV o Excel)")
    ap.add_argument("--facturas", help="Facturas abiertas (CSV o Excel)")
    ap.add_argument("--salida", default="conciliacion.xlsx", help="Excel de salida")
    ap.add_argument("--tolerancia", type=float, default=1.0, help="Diferencia máxima de importe en $")
    ap.add_argument("--ventana", type=int, default=45, help="Días máximos entre vencimiento y pago")
    ap.add_argument("--demo", action="store_true", help="Usar datos de ejemplo")
    a = ap.parse_args()

    if a.demo:
        a.banco, a.facturas = map(str, guardar("data"))
    if not (a.banco and a.facturas):
        ap.error("Indicá --banco y --facturas, o usá --demo")

    res = conciliar(leer(a.banco), leer(a.facturas), Parametros(tolerancia_importe=a.tolerancia, ventana_dias=a.ventana))
    exportar_excel(res, a.salida)

    r = res.resumen
    print(f"\n  Conciliado: {r['pct_conciliado']}% del importe cobrado")
    print(f"  Movimientos: {r['movimientos_conciliados']}/{r['movimientos_banco']}  ·  Facturas: {r['facturas_conciliadas']}/{r['facturas_abiertas']}")
    print(f"  Sin identificar: $ {r['importe_sin_identificar']:,.2f}  ·  A revisar: {r['a_revisar']}")
    for regla, n in r.get("por_regla", {}).items():
        print(f"    - {regla}: {n}")
    print(f"\n  Reporte: {a.salida}\n")


if __name__ == "__main__":
    main()
