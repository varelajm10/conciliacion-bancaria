import pandas as pd
import pytest

from conciliador import Parametros, conciliar, exportar_excel
from conciliador.core import normalizar_texto
from conciliador.demo import generar


def facturas(*filas):
    return pd.DataFrame(filas, columns=["nro_factura", "cliente", "cuit", "vencimiento", "importe"])


def banco(*filas):
    return pd.DataFrame(filas, columns=["id_mov", "fecha", "descripcion", "importe"])


def test_normalizar_quita_acentos_y_forma_societaria():
    assert normalizar_texto("Lácteos La Pradera S.A.") == "LACTEOS LA PRADERA"
    assert normalizar_texto("Logística Rápida S.R.L.") == "LOGISTICA RAPIDA"


def test_match_por_numero_de_factura():
    f = facturas(("A-0001-00001523", "Acme S.A.", "30-11111111-1", "01/10/2026", 1000))
    b = banco(("M1", "05/10/2026", "TRANSF REF FC 1523", 1000))
    r = conciliar(b, f)
    assert r.conciliados.iloc[0]["regla"] == "Nº de factura + importe"
    assert r.resumen["pct_conciliado"] == 100.0


def test_match_por_cuit_elige_vencimiento_mas_cercano():
    f = facturas(
        ("F1", "Acme", "30-11111111-1", "01/08/2026", 500),
        ("F2", "Acme", "30-11111111-1", "01/10/2026", 500),
    )
    b = banco(("M1", "03/10/2026", "CRED TRANSF CUIT 30111111111", 500))
    r = conciliar(b, f)
    assert r.conciliados.iloc[0]["nro_factura"] == "F2"
    assert r.conciliados.iloc[0]["regla"] == "CUIT + importe"


def test_match_difuso_por_nombre_respeta_tolerancia():
    f = facturas(("F1", "Ferretería El Tornillo", "20-1", "01/10/2026", 999.5))
    b = banco(("M1", "10/10/2026", "DEPOSITO FERRETERIA EL TORNILLO", 1000))
    assert conciliar(b, f, Parametros(tolerancia_importe=1)).conciliados.iloc[0]["regla"].startswith("Nombre")
    assert conciliar(b, f, Parametros(tolerancia_importe=0.1, permitir_parciales=False)).conciliados.empty


def test_difuso_no_matchea_si_hay_ambiguedad():
    f = facturas(
        ("F1", "Acme", "", "01/10/2026", 1000),
        ("F2", "Acme", "", "05/10/2026", 1000),
    )
    b = banco(("M1", "10/10/2026", "DEPOSITO ACME", 1000))
    r = conciliar(b, f, Parametros(permitir_parciales=False))
    assert r.conciliados.empty  # dos candidatos idénticos: mejor no adivinar


def test_pago_agrupado():
    f = facturas(
        ("F1", "Acme", "30-11111111-1", "01/10/2026", 300),
        ("F2", "Acme", "30-11111111-1", "05/10/2026", 700),
        ("F3", "Otro", "30-22222222-2", "05/10/2026", 700),
    )
    b = banco(("M1", "10/10/2026", "TRANSF CUIT 30111111111", 1000))
    r = conciliar(b, f)
    assert set(r.conciliados["nro_factura"]) == {"F1", "F2"}
    assert len(r.pendientes) == 1


def test_pago_parcial_queda_marcado_para_revisar():
    f = facturas(("F1", "Acme", "30-11111111-1", "01/10/2026", 1000))
    b = banco(("M1", "10/10/2026", "PAGO A CUENTA ACME", 400))
    fila = conciliar(b, f).conciliados.iloc[0]
    assert fila["regla"] == "Pago parcial (revisar)"
    assert fila["diferencia"] == -600
    assert fila["confianza"] < 80


def test_ignora_debitos_y_reporta_no_identificados():
    f = facturas(("F1", "Acme", "", "01/10/2026", 1000))
    b = banco(("M1", "10/10/2026", "DEBITO IMPUESTO", -50), ("M2", "10/10/2026", "INTERESES", 20))
    r = conciliar(b, f)
    assert r.resumen["movimientos_banco"] == 1
    assert r.sin_identificar.iloc[0]["id_mov"] == "M2"


def test_columnas_faltantes_dan_error_claro():
    with pytest.raises(ValueError, match="faltan columnas"):
        conciliar(pd.DataFrame({"fecha": []}), facturas())


def test_dataset_demo_concilia_mas_del_90_por_ciento(tmp_path):
    b, f = generar()
    r = conciliar(b, f)
    assert r.resumen["pct_conciliado"] > 90
    # cada factura y cada movimiento se usan una sola vez
    assert not r.conciliados.duplicated(["nro_factura"]).any()
    salida = exportar_excel(r, tmp_path / "out.xlsx")
    hojas = pd.ExcelFile(salida).sheet_names
    assert hojas == ["Resumen", "Conciliados", "Banco sin identificar", "Facturas pendientes"]


def test_exporta_a_buffer_en_memoria():
    import io

    b, f = generar()
    buf = io.BytesIO()
    exportar_excel(conciliar(b, f), buf)
    assert buf.getvalue()[:2] == b"PK"  # un .xlsx es un zip
