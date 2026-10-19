"""
Registro de entregas. Con descuento por nómina, quien recibe firma en pantalla:
esa firma es el soporte de que el empleado recibió lo que se le descontará.
"""

import base64
import binascii
import io
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from .models import Entrega, Pedido

logger = logging.getLogger(__name__)

PREFIJO_PNG = "data:image/png;base64,"
TAMANO_MAXIMO_FIRMA = 400 * 1024          # bytes
DIMENSION_MAXIMA_FIRMA = 3000             # píxeles


class EntregaError(Exception):
    pass


def pedidos_por_entregar():
    """Pagados, aprobados por nómina o con "otro medio de pago" (se cobra al entregar), sin entrega."""
    return (
        Pedido.objects
        .filter(
            Q(estado__in=Pedido.ESTADOS_ENTREGABLES)
            | Q(estado=Pedido.ESTADO_PENDIENTE_PAGO, metodo_pago=Pedido.METODO_OTRO)
            | Q(estado=Pedido.ESTADO_PENDIENTE_PAGO, metodo_pago_saldo=Pedido.METODO_OTRO)
        )
        .filter(entrega__isnull=True)
    )


def decodificar_firma(data_url):
    """
    Convierte el trazo del lienzo (data URL PNG) en bytes PNG validados.
    Devuelve b"" si no hay firma; lanza EntregaError si es inválida o está en blanco.
    """
    data_url = (data_url or "").strip()
    if not data_url:
        return b""
    if not data_url.startswith(PREFIJO_PNG):
        raise EntregaError("La firma no tiene un formato válido.")
    try:
        contenido = base64.b64decode(data_url[len(PREFIJO_PNG):], validate=True)
    except (binascii.Error, ValueError):
        raise EntregaError("La firma no tiene un formato válido.")
    if len(contenido) > TAMANO_MAXIMO_FIRMA:
        raise EntregaError("La firma es demasiado grande.")

    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.verify()
        imagen = Image.open(io.BytesIO(contenido))
    except (UnidentifiedImageError, OSError):
        raise EntregaError("La firma no es una imagen válida.")
    if imagen.format != "PNG" or max(imagen.size) > DIMENSION_MAXIMA_FIRMA:
        raise EntregaError("La firma no es una imagen válida.")

    # El lienzo es transparente: si no hay ningún píxel visible, la firma está en blanco.
    if imagen.convert("RGBA").getchannel("A").getbbox() is None:
        return b""
    return contenido


def registrar_entrega(pedido, *, recibido_por, firma_png=b"", observaciones="", usuario=None):
    recibido_por = " ".join((recibido_por or "").split())[:150]
    if len(recibido_por) < 3:
        raise EntregaError("Escribe el nombre de quien recibe.")

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if Entrega.objects.filter(pedido=pedido).exists():
            raise EntregaError("Este pedido ya fue entregado.")
        if not pedido.puede_entregarse:
            raise EntregaError(f"El pedido está en estado «{pedido.get_estado_display()}» y no se puede entregar.")
        if pedido.requiere_firma and not firma_png:
            raise EntregaError("Con descuento por nómina, quien recibe debe firmar.")

        entrega = Entrega(
            pedido=pedido,
            entregado_por=usuario,
            recibido_por=recibido_por,
            observaciones=(observaciones or "").strip(),
        )
        if firma_png:
            entrega.firma.save(f"{pedido.numero}.png", ContentFile(firma_png), save=False)
        entrega.save()

        pedido.estado = Pedido.ESTADO_ENTREGADO
        pedido.save(update_fields=["estado", "updated_at"])
        transaction.on_commit(lambda: notificar_entrega(entrega))
    return entrega


def notificar_entrega(entrega):
    pedido = entrega.pedido
    correo = pedido.correo_notificacion
    if not correo:
        return
    enlace = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("pedidos:seguimiento", args=[pedido.codigo_acceso])
    send_mail(
        f"Tu pedido {pedido.numero} fue entregado",
        (
            f"Hola {pedido.nombre_cliente},\n\n"
            f"Tu pedido {pedido.numero} fue entregado el "
            f"{timezone.localtime(entrega.entregado_en):%d/%m/%Y a las %H:%M} "
            f"y lo recibió {entrega.recibido_por}.\n\n"
            f"Consulta la constancia de entrega aquí: {enlace}\n\n"
            "Gracias por comprar en Tío Campo."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [correo],
        fail_silently=True,
    )


def puede_ver_entrega(usuario, pedido):
    """Firma y constancia: repartidores, el dueño del pedido y los gestores de su fondo."""
    if not usuario.is_authenticated:
        return False
    if usuario.has_perm("pedidos.registrar_entrega") or usuario == pedido.usuario:
        return True
    solicitud = getattr(pedido, "solicitud_nomina", None)
    return bool(solicitud and usuario.fondos_gestionados.filter(pk=solicitud.fondo_id).exists())
