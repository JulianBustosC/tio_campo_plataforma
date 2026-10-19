"""
Quién puede ver o actuar sobre un pedido:
- El usuario dueño del pedido.
- Un invitado, desde el mismo navegador donde compró (el pedido queda en su sesión)
  o desde el enlace con el código secreto que recibe por correo.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Pedido

SESSION_PEDIDOS = "pedidos_invitado"
MAXIMO_EN_SESION = 20


def recordar_pedido(request, pedido):
    ids = [i for i in request.session.get(SESSION_PEDIDOS, []) if i != pedido.id]
    ids.append(pedido.id)
    request.session[SESSION_PEDIDOS] = ids[-MAXIMO_EN_SESION:]


def filtro_pedidos_accesibles(request):
    en_sesion = Q(id__in=request.session.get(SESSION_PEDIDOS, []), usuario__isnull=True)
    if request.user.is_authenticated:
        return Q(usuario=request.user) | en_sesion
    return en_sesion


def pedido_accesible(request, pedido_id, queryset=None):
    queryset = Pedido.objects.all() if queryset is None else queryset
    return get_object_or_404(queryset.filter(filtro_pedidos_accesibles(request)), id=pedido_id)
