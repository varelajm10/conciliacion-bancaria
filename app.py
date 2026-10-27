"""Interfaz web: streamlit run app.py"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from conciliador import Parametros, conciliar, exportar_excel
from conciliador.demo import generar

st.set_page_config(page_title="Conciliación bancaria", page_icon="🏦", layout="wide")

st.title("🏦 Conciliación bancaria automática")
st.caption("Cruza tu extracto bancario contra las facturas abiertas y te dice qué se cobró, qué falta y qué revisar.")

with st.sidebar:
    st.header("Datos")
    usar_demo = st.toggle("Usar datos de ejemplo", value=True)
    f_banco = st.file_uploader("Extracto bancario (CSV/Excel)", type=["csv", "xlsx"], disabled=usar_demo)
    f_fact = st.file_uploader("Facturas abiertas (CSV/Excel)", type=["csv", "xlsx"], disabled=usar_demo)
    st.header("Tolerancias")
    tol = st.number_input("Diferencia máxima de importe ($)", 0.0, 1000.0, 1.0, 0.5)
    ventana = st.slider("Días entre vencimiento y pago", 5, 120, 45)
    similitud = st.slider("Similitud mínima de nombre (%)", 50, 100, 80)
    parciales = st.checkbox("Detectar pagos parciales", value=True)


def leer(archivo) -> pd.DataFrame:
    return pd.read_excel(archivo) if archivo.name.endswith("xlsx") else pd.read_csv(archivo)


if usar_demo:
    banco, facturas = generar()
elif f_banco and f_fact:
    banco, facturas = leer(f_banco), leer(f_fact)
else:
    st.info("Subí el extracto y las facturas, o activá los datos de ejemplo.")
    st.stop()

try:
    res = conciliar(banco, facturas, Parametros(tol, ventana, similitud, permitir_parciales=parciales))
except ValueError as e:
    st.error(str(e))
    st.stop()

r = res.resumen
c1, c2, c3, c4 = st.columns(4)
c1.metric("Conciliado", f"{r['pct_conciliado']}%", help="Porcentaje del importe cobrado que se pudo asignar a facturas")
c2.metric("Movimientos conciliados", f"{r['movimientos_conciliados']} / {r['movimientos_banco']}")
c3.metric("Sin identificar", f"$ {r['importe_sin_identificar']:,.0f}".replace(",", "."))
c4.metric("A revisar", r["a_revisar"], help="Matches con confianza menor a 80")

if r.get("por_regla"):
    st.subheader("Cómo se concilió")
    st.bar_chart(pd.Series(r["por_regla"], name="movimientos"), horizontal=True)

t1, t2, t3 = st.tabs(["✅ Conciliados", "❓ Banco sin identificar", "📄 Facturas pendientes"])
with t1:
    orden = ["regla", "confianza", "fecha_pago", "descripcion_banco", "importe_banco", "nro_factura", "cliente", "importe_factura", "diferencia"]
    st.dataframe(
        res.conciliados[orden].sort_values("confianza", kind="stable") if not res.conciliados.empty else res.conciliados,
        use_container_width=True,
        hide_index=True,
        column_config={
            "confianza": st.column_config.ProgressColumn("confianza", min_value=0, max_value=100, format="%d"),
            "importe_banco": st.column_config.NumberColumn(format="$ %.2f"),
            "importe_factura": st.column_config.NumberColumn(format="$ %.2f"),
            "diferencia": st.column_config.NumberColumn(format="$ %.2f"),
        },
    )
with t2:
    st.dataframe(res.sin_identificar, use_container_width=True, hide_index=True)
with t3:
    st.dataframe(res.pendientes, use_container_width=True, hide_index=True)

buf = io.BytesIO()
exportar_excel(res, buf)
st.download_button("⬇️ Descargar reporte en Excel", buf.getvalue(), "conciliacion.xlsx", type="primary")
