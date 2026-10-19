"""
Registro de pasarelas de pago. Para agregar otra (PayU, Mercado Pago...):
crear un módulo con una subclase de `Pasarela` decorada con @registrar("codigo")
e importarlo al final de este archivo.
"""

from django.conf import settings

_REGISTRO = {}


def registrar(codigo):
    def decorador(cls):
        cls.codigo = codigo
        _REGISTRO[codigo] = cls
        return cls

    return decorador


def obtener_pasarela(codigo=None):
    codigo = codigo or settings.PASARELA_PAGOS
    try:
        return _REGISTRO[codigo]()
    except KeyError:
        raise LookupError(f"Pasarela de pagos '{codigo}' no registrada.")


from . import wompi  # noqa: E402,F401  (registra la pasarela)