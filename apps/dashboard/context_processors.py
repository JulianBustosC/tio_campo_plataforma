from django.db.models import Sum

from apps.carrito.models import Carrito
from apps.catalogos.models import Categoria


def navegacion(request):
    """
    Datos comunes del menú. No crea carritos ni sesiones: solo consulta,
    para no generar filas por cada visitante o bot.
    """
    filtro = None
    if request.user.is_authenticated:
        filtro = {"usuario": request.user}
    elif request.session.get("carrito_id"):
        filtro = {"id": request.session["carrito_id"], "usuario__isnull": True}

    cantidad = 0
    if filtro:
        cantidad = (
            Carrito.objects
            .filter(activo=True, **filtro)
            .aggregate(total=Sum("items__cantidad"))["total"]
            or 0
        )

    return {
        "categorias_menu": Categoria.objects.filter(activo=True).order_by("orden", "nombre")[:8],
        "cantidad_carrito": cantidad,
    }
