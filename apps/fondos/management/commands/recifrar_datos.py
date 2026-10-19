from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.cifrado import cifrar, huella
from apps.fondos.models import AfiliadoFondo, SolicitudDescuentoNomina
from apps.pedidos.models import Pedido


class Command(BaseCommand):
    help = (
        "Vuelve a cifrar documentos y teléfonos con la clave principal y recalcula las "
        "huellas de búsqueda. Úselo después de cambiar o rotar las claves."
    )

    def handle(self, *args, **opciones):
        totales = {}
        with transaction.atomic():
            n = 0
            for afiliado in AfiliadoFondo.objects.all().iterator():
                AfiliadoFondo.objects.filter(pk=afiliado.pk).update(
                    documento=cifrar(afiliado.documento), documento_huella=huella(afiliado.documento)
                )
                n += 1
            totales["afiliados"] = n

            n = 0
            for solicitud in SolicitudDescuentoNomina.objects.all().iterator():
                SolicitudDescuentoNomina.objects.filter(pk=solicitud.pk).update(
                    documento=cifrar(solicitud.documento),
                    telefono=cifrar(solicitud.telefono),
                    documento_huella=huella(solicitud.documento),
                )
                n += 1
            totales["solicitudes"] = n

            n = 0
            for pedido in Pedido.objects.exclude(telefono_contacto="").iterator():
                Pedido.objects.filter(pk=pedido.pk).update(telefono_contacto=cifrar(pedido.telefono_contacto))
                n += 1
            totales["pedidos"] = n

        self.stdout.write(self.style.SUCCESS(
            "Datos recifrados: " + ", ".join(f"{v} {k}" for k, v in totales.items())
        ))
