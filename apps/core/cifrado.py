"""
Protección de datos personales en reposo (Ley 1581 de 2012).

- `cifrar` / `descifrar`: cifrado simétrico autenticado (Fernet = AES-128-CBC + HMAC-SHA256).
  La base de datos solo guarda texto cifrado; sin la clave no se puede leer.
- `huella`: HMAC-SHA256 del dato normalizado. Permite buscar por igualdad
  (p. ej. "¿existe este documento en el padrón?") sin guardar el dato en claro.

Claves (variables de entorno):
- DATOS_CIFRADO_CLAVES: una o varias claves Fernet separadas por coma. La PRIMERA
  cifra; todas sirven para descifrar (rotación de claves sin perder datos).
- DATOS_HUELLA_CLAVE: secreto para las huellas de búsqueda.

En desarrollo y pruebas, sin claves, se derivan de SECRET_KEY para que el
proyecto funcione sin configuración. En producción (DEBUG=0) settings.py
no deja arrancar sin ellas.
"""

import base64
import hashlib
import hmac
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIJO = "enc1:"


def _derivar(contexto):
    return hashlib.sha256(f"{settings.SECRET_KEY}|{contexto}".encode()).digest()


def clave_desarrollo():
    """Clave que se usa en desarrollo cuando no hay DATOS_CIFRADO_CLAVES."""
    return base64.urlsafe_b64encode(_derivar("cifrado-datos")).decode()


@lru_cache(maxsize=1)
def _fernet():
    claves = [c.strip() for c in (settings.DATOS_CIFRADO_CLAVES or "").split(",") if c.strip()]
    if not claves:
        # settings.py exige las claves cuando DEBUG=0; aquí solo llega en desarrollo y pruebas.
        claves = [clave_desarrollo()]
    return MultiFernet([Fernet(c.encode()) for c in claves])


@lru_cache(maxsize=1)
def _clave_huella():
    if settings.DATOS_HUELLA_CLAVE:
        return settings.DATOS_HUELLA_CLAVE.encode()
    return _derivar("huella-datos")


def cifrar(texto):
    if texto in (None, ""):
        return texto
    if str(texto).startswith(PREFIJO):
        return texto
    return PREFIJO + _fernet().encrypt(str(texto).encode()).decode()


def descifrar(valor):
    """Devuelve el texto en claro. Valores antiguos sin cifrar se devuelven tal cual."""
    if not valor or not str(valor).startswith(PREFIJO):
        return valor
    try:
        return _fernet().decrypt(valor[len(PREFIJO):].encode()).decode()
    except InvalidToken:
        raise ImproperlyConfigured(
            "No se pudo descifrar un dato personal: la clave DATOS_CIFRADO_CLAVES no corresponde."
        )


def normalizar_documento(documento):
    return re.sub(r"[^0-9A-Za-z]", "", documento or "").upper()


def huella(texto, normalizar=normalizar_documento):
    valor = normalizar(texto)
    if not valor:
        return ""
    return hmac.new(_clave_huella(), valor.encode(), hashlib.sha256).hexdigest()


def enmascarar(texto, visibles=4):
    """'1020304050' -> '••••••4050' (para listados)."""
    texto = texto or ""
    if len(texto) <= visibles:
        return "•" * len(texto)
    return "•" * (len(texto) - visibles) + texto[-visibles:]


def generar_clave():
    return Fernet.generate_key().decode()


def reiniciar_cache():
    """Tras cambiar las claves en tiempo de ejecución (pruebas)."""
    _fernet.cache_clear()
    _clave_huella.cache_clear()
