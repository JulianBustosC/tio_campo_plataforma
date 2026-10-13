from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.carrito.views import obtener_carrito

from .models import Pedido
from .services import PedidoError, cancelar_pedido, crear_pedido_desde_carrito, definir_pago_saldo


@login_required
def checkout(request):
    carrito = obtener_carrito(request)
    items = (
        carrito.items
        .select_related(
            "presentacion",
            "presentacion__producto",
            "presentacion__presentacion",
            "combo",
        )
        .order_by("id")
    )

    if not items.exists():
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("carrito:detalle")

    if request.method == "POST":
        try:
            pedido = crear_pedido_desde_carrito(
                carrito=carrito,
                usuario=request.user,
                metodo_pago=request.POST.get("metodo_pago", "").strip(),
                direccion=request.POST.get("direccion_entrega", "").strip(),
                ciudad=request.POST.get("ciudad", "").strip(),
                observaciones=request.POST.get("observaciones", "").strip(),
            )
        except PedidoError as exc:
            messages.error(request, str(exc))
            return redirect("pedidos:checkout")

        if pedido.metodo_pago == Pedido.METODO_NOMINA:
            return redirect("fondos:solicitar_descuento_nomina", pedido_id=pedido.id)

        messages.success(request, f"Pedido {pedido.numero} creado correctamente.")
        return redirect("pedidos:confirmacion", pedido_id=pedido.id)

    return render(
        request,
        "pedidos/checkout.html",
        {"carrito": carrito, "items": items, "total": carrito.total},
    )


@login_required
def confirmacion(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related("items").select_related("solicitud_nomina"),
        id=pedido_id,
        usuario=request.user,
    )
    return render(
        request,
        "pedidos/confirmacion.html",
        {"pedido": pedido, "metodos_saldo": Pedido.METODOS_PAGO_SALDO},
    )


@login_required
@require_POST
def pagar_saldo(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)
    try:
        pedido = definir_pago_saldo(pedido, request.POST.get("metodo_pago_saldo", ""))
    except PedidoError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Listo. El saldo de ${pedido.saldo_pendiente:,.0f} quedó pendiente de pago "
            f"por {pedido.get_metodo_pago_saldo_display().lower()}.",
        )
    return redirect("pedidos:confirmacion", pedido_id=pedido.id)


@login_required
@require_POST
def cancelar(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)
    try:
        cancelar_pedido(pedido, usuario=request.user)
    except PedidoError as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, f"El pedido {pedido.numero} fue cancelado.")
    return redirect("pedidos:confirmacion", pedido_id=pedido.id)


@login_required
def mis_pedidos(request):
    pedidos = (
        Pedido.objects
        .filter(usuario=request.user)
        .order_by("-created_at")
    )
    return render(request, "pedidos/mis_pedidos.html", {"pedidos": pedidos})
