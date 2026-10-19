from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from apps.catalogos.models import Categoria
from .consultas import ORDENES, buscar, productos_para_tarjetas
from .models import Producto

POR_PAGINA = 24


def _catalogo(request, categoria=None):
    productos = productos_para_tarjetas()
    if categoria is not None:
        productos = productos.filter(categoria=categoria)

    busqueda = request.GET.get("q", "").strip()
    productos = buscar(productos, busqueda)

    orden = request.GET.get("orden", "relevancia")
    if orden not in ORDENES:
        orden = "relevancia"
    productos = productos.order_by(*ORDENES[orden])

    pagina = Paginator(productos, POR_PAGINA).get_page(request.GET.get("page"))

    return render(
        request,
        "productos/catalogo.html",
        {
            "categoria": categoria,
            "categorias": Categoria.objects.filter(activo=True).order_by("orden", "nombre"),
            "productos": pagina,
            "pagina": pagina,
            "busqueda": busqueda,
            "orden": orden,
            "ordenes": [
                ("relevancia", "Relevancia"),
                ("precio_asc", "Menor precio"),
                ("precio_desc", "Mayor precio"),
                ("nombre", "Nombre A-Z"),
            ],
        },
    )


def lista_productos(request):
    return _catalogo(request)


def productos_por_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id, activo=True)
    return _catalogo(request, categoria)


def detalle_producto(request, pk):
    producto = get_object_or_404(
        Producto.objects
        .select_related(
            "categoria",
            "marca",
        )
        .prefetch_related(
            "presentaciones__presentacion__unidad",
        ),
        pk=pk,
        activo=True,
    )

    presentaciones = producto.presentaciones.filter(
        activo=True
    )

    return render(
        request,
        "productos/detalle.html",
        {
            "producto": producto,
            "presentaciones": presentaciones,
        },
    )
