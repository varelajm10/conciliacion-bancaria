"""Genera datos de ejemplo realistas (y 100% inventados) para probar el conciliador."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

CLIENTES = [
    ("Distribuidora del Sur S.A.", "30-71234567-8"),
    ("Constructora Andes S.R.L.", "30-70987654-1"),
    ("Ferretería El Tornillo", "20-28765432-5"),
    ("Lácteos La Pradera S.A.", "30-71555222-9"),
    ("Agro Pampa SAS", "30-71888111-3"),
    ("Supermercados Norte S.A.", "30-70111222-4"),
    ("Logística Rápida S.R.L.", "30-71444333-7"),
    ("Panadería San Martín", "27-31222333-0"),
    ("Maquinarias del Litoral S.A.", "30-70666555-2"),
    ("Farmacia Central", "27-29888777-6"),
]


def generar(n_facturas: int = 60, semilla: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    rnd = random.Random(semilla)
    hoy = date(2026, 10, 31)
    facturas = []
    for i in range(1, n_facturas + 1):
        cliente, cuit = rnd.choice(CLIENTES)
        emision = hoy - timedelta(days=rnd.randint(10, 90))
        facturas.append(
            {
                "nro_factura": f"A-0001-{i + 1500:08d}",
                "cliente": cliente,
                "cuit": cuit,
                "fecha_emision": emision.strftime("%d/%m/%Y"),
                "vencimiento": (emision + timedelta(days=30)).strftime("%d/%m/%Y"),
                "importe": round(rnd.uniform(40_000, 1_200_000), 2),
            }
        )
    df_f = pd.DataFrame(facturas)

    movs = []

    def mov(fecha, desc, importe):
        movs.append({"id_mov": f"MOV-{len(movs) + 1:04d}", "fecha": fecha, "descripcion": desc, "importe": importe})

    idx = list(range(len(df_f)))
    rnd.shuffle(idx)
    pagadas = idx[: int(len(idx) * 0.75)]
    # 3 pagos agrupados: pares de facturas del mismo cliente
    grupos: list[int] = []
    for cuit in df_f.loc[pagadas, "cuit"].unique():
        del_cliente = [i for i in pagadas if df_f.loc[i, "cuit"] == cuit]
        if len(del_cliente) >= 2 and len(grupos) < 6:
            grupos += del_cliente[:2]
    resto = [i for i in pagadas if i not in grupos]

    for k, i in enumerate(resto):
        f = df_f.loc[i]
        venc = pd.to_datetime(f["vencimiento"], dayfirst=True).date()
        fecha = min(venc + timedelta(days=rnd.randint(-5, 20)), hoy).strftime("%d/%m/%Y")
        nombre_corto = f["cliente"].split(" S.")[0].upper()
        tipo = k % 5
        if tipo == 0:
            mov(fecha, f"TRANSF RECIBIDA {nombre_corto} REF FC {f['nro_factura'][-4:]}", f["importe"])
        elif tipo == 1:
            mov(fecha, f"CRED TRANSF CUIT {f['cuit'].replace('-', '')} VARIOS", f["importe"])
        elif tipo == 2:
            mov(fecha, f"DEPOSITO {nombre_corto}", f["importe"])
        elif tipo == 3:
            mov(fecha, f"TRANSFERENCIA {f['nro_factura']}", round(f["importe"] - rnd.choice([0, 0.5]), 2))
        else:
            parcial = round(f["importe"] * rnd.choice([0.3, 0.5]), 2)
            mov(fecha, f"PAGO A CUENTA {nombre_corto}", parcial)

    # pagos agrupados: una transferencia por dos facturas del mismo cliente
    por_cliente: dict[str, list[int]] = {}
    for i in grupos:
        por_cliente.setdefault(df_f.loc[i, "cuit"], []).append(i)
    for cuit, ids in por_cliente.items():
        for par in [ids[j : j + 2] for j in range(0, len(ids), 2)]:
            total = round(float(df_f.loc[par, "importe"].sum()), 2)
            fecha = min(pd.to_datetime(df_f.loc[par[0], "vencimiento"], dayfirst=True).date(), hoy).strftime("%d/%m/%Y")
            mov(fecha, f"TRANSF CUIT {cuit.replace('-', '')} PAGO FACTURAS", total)

    # ruido: movimientos que no corresponden a ninguna factura
    for desc in ["INTERESES PLAZO FIJO", "DEVOLUCION COMISION", "TRANSF RECIBIDA CLIENTE NUEVO", "ACREDITACION MERCADO PAGO"]:
        mov(hoy.strftime("%d/%m/%Y"), desc, round(rnd.uniform(5_000, 300_000), 2))
    # débitos (el motor los ignora)
    mov(hoy.strftime("%d/%m/%Y"), "DEBITO IMPUESTO LEY 25413", -12_345.67)

    df_b = pd.DataFrame(movs).sample(frac=1, random_state=semilla).reset_index(drop=True)
    return df_b, df_f


def guardar(carpeta: str | Path = "data") -> tuple[Path, Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    banco, facturas = generar()
    rb, rf = carpeta / "extracto_banco.csv", carpeta / "facturas_abiertas.csv"
    banco.to_csv(rb, index=False)
    facturas.to_csv(rf, index=False)
    return rb, rf


if __name__ == "__main__":
    print(guardar())
