"""
Integración con Wompi (Bancolombia) usando Web Checkout + eventos (webhook).
Documentación: https://docs.wompi.co
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlencode

from django.conf import settings

from ..models import TransaccionPago
from . import registrar
from .base import EventoPago, FirmaInvalida, Pasarela

logger = logging.getLogger(__name__)

ESTADOS_WOMPI = {
    "APPROVED": TransaccionPago.ESTADO_APROBADA,
    "DECLINED": TransaccionPago.ESTADO_RECHAZADA,
    "VOIDED": TransaccionPago.ESTADO_ANULADA,
    "ERROR": TransaccionPago.ESTADO_ERROR,
    "PENDING": TransaccionPago.ESTADO_PENDIENTE,
}


def firma_integridad(referencia, monto_centavos, moneda, secreto):
    cadena = f"{referencia}{monto_centavos}{moneda}{secreto}"
    return hashlib.sha256(cadena.encode()).hexdigest()


def _valor_por_ruta(datos, ruta):
    """'transaction.amount_in_cents' -> datos['transaction']['amount_in_cents']"""
    valor = datos
    for parte in ruta.split("."):
        valor = valor[parte]
    return valor


@registrar("wompi")
class Wompi(Pasarela):

    def url_checkout(self, transaccion, url_retorno, correo=""):
        parametros = {
            "public-key": settings.WOMPI_PUBLIC_KEY,
            "currency": transaccion.moneda,
            "amount-in-cents": transaccion.monto_centavos,
            "reference": transaccion.referencia,
            "signature:integrity": firma_integridad(
                transaccion.referencia,
                transaccion.monto_centavos,
                transaccion.moneda,
                settings.WOMPI_INTEGRITY_SECRET,
            ),
            "redirect-url": url_retorno,
        }
        if correo:
            parametros["customer-data:email"] = correo
        return settings.WOMPI_CHECKOUT_URL + "?" + urlencode(parametros)

    def leer_evento(self, cuerpo):
        try:
            evento = json.loads(cuerpo)
            firma = evento["signature"]
            cadena = "".join(
                str(_valor_por_ruta(evento["data"], propiedad))
                for propiedad in firma["properties"]
            )
            cadena += f"{evento['timestamp']}{settings.WOMPI_EVENTS_SECRET}"
        except (ValueError, KeyError, TypeError) as exc:
            raise FirmaInvalida(f"Evento mal formado: {exc}")

        calculada = hashlib.sha256(cadena.encode()).hexdigest()
        if not hmac.compare_digest(calculada, str(firma.get("checksum", "")).lower()):
            raise FirmaInvalida("Checksum no coincide.")

        if evento.get("event") != "transaction.updated":
            return None
        return self._a_evento(evento["data"]["transaction"])

    def consultar(self, id_externo):
        url = f"{settings.WOMPI_API_URL.rstrip('/')}/transactions/{id_externo}"
        peticion = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=settings.PAGOS_API_TIMEOUT) as respuesta:
                datos = json.loads(respuesta.read().decode())
            return self._a_evento(datos["data"])
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.warning("No se pudo consultar la transacción Wompi %s: %s", id_externo, exc)
            return None

    @staticmethod
    def _a_evento(transaccion):
        return EventoPago(
            referencia=transaccion["reference"],
            id_externo=str(transaccion["id"]),
            estado=ESTADOS_WOMPI.get(transaccion.get("status"), TransaccionPago.ESTADO_ERROR),
            monto_centavos=int(transaccion["amount_in_cents"]),
            metodo=transaccion.get("payment_method_type") or "",
            datos=transaccion,
        )