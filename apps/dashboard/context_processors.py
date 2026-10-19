from apps.carrito.models import CarritoItem
from apps.catalogos.models import Categoria


def navegacion(request):
    """
    Datos comunes del menú y del carrito. No crea carritos ni sesiones:
    solo consulta, para no generar filas por cada visitante o bot.
    """
    filtro = None
    if request.user.is_authenticated:
        filtro = {"carrito__usuario": request.user}
    elif request.session.get("carrito_id"):
        filtro = {"carrito_id": request.session["carrito_id"], "carrito__usuario__isnull": True}

    # {"p12": 2, "c3": 1} -> cantidades por presentación (p) y combo (c),
    # para que las tarjetas muestren el selector de cantidad correcto.
    cantidades = {}
    total = 0
    if filtro:
        items = CarritoItem.objects.filter(carrito__activo=True, **filtro).values_list(
            "presentacion_id", "combo_id", "cantidad", "precio_unitario"
        )
        for presentacion_id, combo_id, cantidad, precio in items:
            clave = f"p{presentacion_id}" if presentacion_id else f"c{combo_id}"
            cantidades[clave] = cantidad
            total += cantidad * precio

    pendientes_entrega = None
    if request.user.is_authenticated and request.user.has_perm("pedidos.registrar_entrega"):
        from apps.pedidos.entregas import pedidos_por_entregar

        pendientes_entrega = pedidos_por_entregar().count()

    return {
        "pendientes_entrega": pendientes_entrega,
        "categorias_menu": Categoria.objects.filter(activo=True).order_by("orden", "nombre")[:12],
        "cantidad_carrito": sum(cantidades.values()),
        "total_carrito": total,
        "cantidades_carrito": cantidades,
    }
