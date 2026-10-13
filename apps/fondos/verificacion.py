"""
Verificación de vinculación del comprador con el fondo de empleados.

Diseño extensible (patrón estrategia + registro): cada fondo elige un modo
(`FondoEmpleado.modo_verificacion`) y aquí se registra la clase que lo resuelve.
Para conectar un nuevo tipo de integración (SOAP, SFTP, otro proveedor) basta con
crear una subclase de `Verificador` y decorarla con `@registrar("<MODO>")`.

Un verificador NUNCA decide el estado de la solicitud: solo informa
vinculación y cupo. La decisión la toma `calcular_decision`, que es una
función pura y fácil de probar.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings

from .models import AfiliadoFondo, FondoEmpleado, SolicitudDescuentoNomina

logger = logging.getLogger(__name__)


def normalizar_documento(documento):
    return re.sub(r"[^0-9A-Za-z]", "", documento or "").upper()


@dataclass(frozen=True)
class ResultadoVerificacion:
    # True: es empleado/afiliado · False: no lo es · None: no concluyente (revisión manual)
    vinculado: bool | None
    cupo_disponible: Decimal | None = None
    afiliado: AfiliadoFondo | None = None
    referencia: str = ""
    mensaje: str = ""

    @property
    def concluyente(self):
        if self.vinculado is None:
            return False
        return self.vinculado is False or self.cupo_disponible is not None


def calcular_decision(valor_solicitado, vinculado, cupo_disponible):
    """
    Regla de negocio de aprobación:
    - No vinculado o sin cupo           -> RECHAZADA, aprobado 0
    - Cupo >= valor solicitado          -> APROBADA (total)
    - 0 < cupo < valor solicitado       -> APROBADA_PARCIAL por el cupo disponible
    """
    S = SolicitudDescuentoNomina
    if not vinculado or cupo_disponible is None or cupo_disponible <= 0:
        return S.ESTADO_RECHAZADA, Decimal("0")
    if cupo_disponible >= valor_solicitado:
        return S.ESTADO_APROBADA, valor_solicitado
    return S.ESTADO_APROBADA_PARCIAL, cupo_disponible


_REGISTRO = {}


def registrar(modo):
    def decorador(cls):
        _REGISTRO[modo] = cls
        return cls

    return decorador


def obtener_verificador(fondo):
    cls = _REGISTRO.get(fondo.modo_verificacion, VerificadorManual)
    return cls(fondo)


class Verificador(ABC):
    def __init__(self, fondo):
        self.fondo = fondo

    @abstractmethod
    def verificar(self, solicitud) -> ResultadoVerificacion:
        raise NotImplementedError


@registrar(FondoEmpleado.MODO_MANUAL)
class VerificadorManual(Verificador):
    def verificar(self, solicitud):
        return ResultadoVerificacion(
            vinculado=None,
            mensaje="Pendiente de revisión manual por el gestor del fondo.",
        )


@registrar(FondoEmpleado.MODO_PADRON)
class VerificadorPadron(Verificador):
    def verificar(self, solicitud):
        documento = normalizar_documento(solicitud.documento)
        afiliado = (
            AfiliadoFondo.objects
            .filter(fondo=self.fondo, documento=documento)
            .first()
        )
        if afiliado is None:
            return ResultadoVerificacion(
                vinculado=False,
                mensaje="El documento no aparece en el padrón de afiliados del fondo.",
            )
        if not afiliado.activo:
            return ResultadoVerificacion(
                vinculado=False,
                afiliado=afiliado,
                mensaje="El afiliado figura inactivo en el padrón del fondo.",
            )
        return ResultadoVerificacion(
            vinculado=True,
            cupo_disponible=afiliado.cupo_disponible,
            afiliado=afiliado,
            mensaje="Afiliado activo encontrado en el padrón.",
        )


@registrar(FondoEmpleado.MODO_API)
class VerificadorApi(Verificador):
    """
    Contrato esperado con el servicio del fondo:

    POST <api_url>   Authorization: Bearer <token>
    {"documento": "...", "nombre": "...", "empresa": "...", "numero_afiliado": "...",
     "valor_solicitado": "100000.00", "referencia_pedido": "PED-..."}

    Respuesta 200:
    {"vinculado": true, "cupo_disponible": 80000, "referencia": "ABC-1", "mensaje": "..."}
    """

    def verificar(self, solicitud):
        if not self.fondo.api_url:
            return ResultadoVerificacion(None, mensaje="El fondo no tiene URL de API configurada.")

        payload = json.dumps({
            "documento": normalizar_documento(solicitud.documento),
            "nombre": solicitud.nombre_completo,
            "empresa": solicitud.empresa,
            "numero_afiliado": solicitud.numero_afiliado,
            "valor_solicitado": str(solicitud.valor_solicitado),
            "referencia_pedido": solicitud.pedido.numero if solicitud.pedido_id else "",
        }).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = os.getenv(self.fondo.api_token_env) if self.fondo.api_token_env else None
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(self.fondo.api_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=settings.FONDOS_API_TIMEOUT) as respuesta:
                datos = json.loads(respuesta.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("Fallo verificando solicitud %s con %s: %s", solicitud.pk, self.fondo, exc)
            return ResultadoVerificacion(
                vinculado=None,
                mensaje="El servicio del fondo no respondió; queda para revisión manual.",
            )

        vinculado = datos.get("vinculado")
        if not isinstance(vinculado, bool):
            return ResultadoVerificacion(None, mensaje="Respuesta del fondo sin campo 'vinculado' válido.")

        cupo = None
        if datos.get("cupo_disponible") is not None:
            try:
                cupo = max(Decimal(str(datos["cupo_disponible"])), Decimal("0"))
            except InvalidOperation:
                return ResultadoVerificacion(None, mensaje="Respuesta del fondo con cupo inválido.")

        return ResultadoVerificacion(
            vinculado=vinculado,
            cupo_disponible=cupo,
            referencia=str(datos.get("referencia", ""))[:100],
            mensaje=str(datos.get("mensaje", ""))[:500] or "Verificado por el servicio del fondo.",
        )
