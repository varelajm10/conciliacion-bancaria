"""Conciliación bancaria automática para cuentas por cobrar."""

from .core import Conciliador, Parametros, Resultado, conciliar
from .reporte import exportar_excel

__all__ = ["Conciliador", "Parametros", "Resultado", "conciliar", "exportar_excel"]
__version__ = "1.0.0"
