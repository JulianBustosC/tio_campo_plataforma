import logging

from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.pedidos.acceso import filtro_pedidos_accesibles, pedido_accesible
from apps.pedidos.models import Pedido

from .models import TransaccionPago
from .pasarelas import obtener_pasarela
from .pasarelas.base import FirmaInvalida
from .services import PagoError, aplicar_evento, iniciar_pago

logger = logging.getLogger(__name__)


@require_POST
def pagar(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        _, url = iniciar_pago(pedido, correo=pedido.correo_notificacion)
    except PagoError as exc:
        messages.error(request, str(exc))
        return redirect("pedidos:confirmacion", pedido_id=pedido.id)
    return redirect(url)


def retorno(request):
    """
    La pasarela devuelve al comprador aquí con ?id=<id de la transacción>.
    No se confía en los parámetros del navegador: se consulta a la pasarela
    servidor-a-servidor y se aplica ese resultado.
    """
    id_externo = request.GET.get("id", "")
    transaccion = None

    if id_externo:
        evento = obtener_pasarela().consultar(id_externo)
        if evento is not None:
            propia = TransaccionPago.objects.filter(
                referencia=evento.referencia,
                pedido__in=Pedido.objects.filter(filtro_pedidos_accesibles(request)),
            ).exists()
            if propia:
                transaccion = aplicar_evento(evento)

    if transaccion is None:
        messages.info(request, "Estamos confirmando tu pago. Te avisaremos por correo.")
        return redirect("pedidos:mis_pedidos" if request.user.is_authenticated else "dashboard")

    return render(request, "pagos/retorno.html", {"transaccion": transaccion, "pedido": transaccion.pedido})


@csrf_exempt
@require_POST
def webhook(request, proveedor):
    try:
        pasarela = obtener_pasarela(proveedor)
    except LookupError:
        return HttpResponseBadRequest("Proveedor desconocido")

    try:
        evento = pasarela.leer_evento(request.body)
    except FirmaInvalida as exc:
        logger.warning("Webhook %s rechazado: %s", proveedor, exc)
        return HttpResponseBadRequest("Firma inválida")

    if evento is not None:
        aplicar_evento(evento)
    return HttpResponse("ok")