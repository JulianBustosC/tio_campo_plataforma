from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.productos.models import ProductoPresentacion
from apps.promociones.models import Combo

from .models import CarritoItem

CANTIDAD_MAXIMA_ITEM = 99


class CarritoError(Exception):
    pass


def fijar_cantidad(carrito, tipo, objeto_id, cantidad):
    """
    Fija la cantidad de una presentación (tipo "p") o un combo (tipo "c").
    0 lo elimina. Devuelve (cantidad_final, mensaje). Lanza Http404 si no existe.
    """
    try:
        cantidad = max(int(cantidad), 0)
    except (TypeError, ValueError):
        raise CarritoError("Cantidad inválida.")
    cantidad = min(cantidad, CANTIDAD_MAXIMA_ITEM)
    mensaje = ""

    if tipo == "p":
        objeto = get_object_or_404(
            ProductoPresentacion, id=objeto_id, activo=True, producto__activo=True
        )
        filtro, defaults = {"presentacion": objeto}, {"combo": None}
    elif tipo == "c":
        objeto = get_object_or_404(Combo, id=objeto_id, activo=True)
        if cantidad > objeto.stock:
            cantidad = objeto.stock
            mensaje = f"Solo hay {objeto.stock} unidad(es) disponibles."
        filtro, defaults = {"combo": objeto}, {"presentacion": None}
    else:
        raise CarritoError("Tipo inválido: use 'p' (presentación) o 'c' (combo).")

    with transaction.atomic():
        if cantidad == 0:
            CarritoItem.objects.filter(carrito=carrito, **filtro).delete()
        else:
            CarritoItem.objects.update_or_create(
                carrito=carrito,
                **filtro,
                defaults={**defaults, "cantidad": cantidad, "precio_unitario": objeto.precio},
            )
    return cantidad, mensaje


def resumen_carrito(carrito):
    items = list(carrito.items.all())
    return sum(i.cantidad for i in items), sum((i.subtotal for i in items), 0)
