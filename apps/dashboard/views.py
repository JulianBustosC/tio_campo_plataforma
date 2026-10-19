from django.shortcuts import render

from apps.catalogos.models import Categoria
from apps.productos.consultas import productos_para_tarjetas
from apps.promociones.models import Combo

from .models import Banner

MAX_POR_FRANJA = 12


def dashboard(request):
    productos = productos_para_tarjetas()

    destacados = list(productos.filter(destacado=True).order_by("orden", "nombre")[:MAX_POR_FRANJA])
    novedades = list(productos.order_by("-created_at")[:MAX_POR_FRANJA])

    combos = list(
        Combo.objects
        .filter(activo=True, stock__gt=0)
        .order_by("-destacado", "orden", "nombre")[:MAX_POR_FRANJA]
    )

    # Una franja por categoría con productos (máximo 4 categorías en la portada).
    franjas_categoria = []
    for categoria in Categoria.objects.filter(activo=True).order_by("orden", "nombre"):
        items = list(productos.filter(categoria=categoria).order_by("orden", "nombre")[:MAX_POR_FRANJA])
        if items:
            franjas_categoria.append((categoria, items))
        if len(franjas_categoria) == 4:
            break

    return render(
        request,
        "home/index.html",
        {
            "banners": Banner.objects.vigentes()[:6],
            "destacados": destacados,
            "novedades": novedades,
            "combos": combos,
            "franjas_categoria": franjas_categoria,
        },
    )
