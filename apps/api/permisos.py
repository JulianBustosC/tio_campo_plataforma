from rest_framework.permissions import BasePermission

from apps.fondos.models import FondoEmpleado, SolicitudDescuentoNomina


class EsGestorDeFondo(BasePermission):
    message = "Solo los gestores de un fondo de empleados pueden usar este recurso."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario and usuario.is_authenticated
            and (usuario.is_superuser or usuario.fondos_gestionados.exists())
        )


def fondos_del_gestor(usuario):
    if usuario.is_superuser:
        return FondoEmpleado.objects.all()
    return usuario.fondos_gestionados.all()


def solicitudes_del_gestor(usuario):
    return (
        SolicitudDescuentoNomina.objects
        .filter(fondo__in=fondos_del_gestor(usuario))
        .select_related("fondo", "pedido")
    )
