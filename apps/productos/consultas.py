"""
Consultas reutilizables del catálogo. Todas las vistas que muestran tarjetas
de producto usan `productos_para_tarjetas()` para no repetir lógica ni
disparar consultas por cada producto (N+1).
"""

from django.db.models import Min, Prefetch, Q

from .models import Producto, ProductoPresentacion


def productos_para_tarjetas():
    presentaciones_activas = (
        ProductoPresentacion.objects
        .filter(activo=True)
        .select_related("presentacion")
        .order_by("precio")
    )
    return (
        Producto.objects
        .filter(activo=True, presentaciones__activo=True)
        .distinct()
        .select_related("categoria", "marca")
        .prefetch_related(
            Prefetch("presentaciones", queryset=presentaciones_activas, to_attr="presentaciones_activas")
        )
        .annotate(precio_desde=Min("presentaciones__precio", filter=Q(presentaciones__activo=True)))
    )


def buscar(queryset, texto):
    texto = (texto or "").strip()
    if not texto:
        return queryset
    filtro = Q()
    for palabra in texto.split()[:5]:
        filtro &= (
            Q(nombre__icontains=palabra)
            | Q(codigo__icontains=palabra)
            | Q(marca__nombre__icontains=palabra)
            | Q(categoria__nombre__icontains=palabra)
            | Q(presentaciones__codigo__icontains=palabra)
        )
    return queryset.filter(filtro).distinct()


ORDENES = {
    "relevancia": ("orden", "nombre"),
    "precio_asc": ("precio_desde", "nombre"),
    "precio_desc": ("-precio_desde", "nombre"),
    "nombre": ("nombre",),
}
