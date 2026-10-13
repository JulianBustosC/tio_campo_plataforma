from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.pedidos.models import Pedido
from .forms import CargaPadronForm, RespuestaFondoForm, SolicitudDescuentoNominaForm
from .models import FondoEmpleado, HistorialSolicitud, SolicitudDescuentoNomina
from .services import (
    DecisionInvalida,
    aplicar_decision,
    importar_padron,
    procesar_verificacion,
    registrar_historial,
)


@login_required
def solicitar_descuento_nomina(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related("items"),
        id=pedido_id,
        usuario=request.user,
        metodo_pago=Pedido.METODO_NOMINA,
    )

    if hasattr(pedido, "solicitud_nomina"):
        return redirect("fondos:detalle_solicitud", solicitud_id=pedido.solicitud_nomina.id)

    if pedido.estado != Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA:
        messages.warning(request, "Este pedido no admite una nueva solicitud de nómina.")
        return redirect("pedidos:confirmacion", pedido_id=pedido.id)

    initial = {
        "nombre_completo": request.user.get_full_name() or request.user.username,
        "correo": request.user.email,
    }

    if request.method == "POST":
        form = SolicitudDescuentoNominaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
                if SolicitudDescuentoNomina.objects.filter(pedido=pedido).exists():
                    messages.info(request, "Este pedido ya tiene una solicitud de nómina.")
                    return redirect("pedidos:confirmacion", pedido_id=pedido.id)

                solicitud = form.save(commit=False)
                solicitud.usuario = request.user
                solicitud.pedido = pedido
                solicitud.valor_solicitado = pedido.total
                solicitud.estado = SolicitudDescuentoNomina.ESTADO_PENDIENTE
                solicitud.save()
                registrar_historial(solicitud, HistorialSolicitud.EVENTO_CREADA, usuario=request.user)

                pedido.estado = Pedido.ESTADO_EN_REVISION_NOMINA
                pedido.save(update_fields=["estado", "updated_at"])

            # Fuera de la transacción: puede consultar un servicio externo del fondo.
            solicitud = procesar_verificacion(solicitud.id)

            if solicitud.esta_pendiente:
                messages.success(
                    request,
                    f"Solicitud #{solicitud.id} enviada al fondo. Quedó pendiente de aprobación.",
                )
            else:
                messages.info(
                    request,
                    f"El fondo respondió tu solicitud #{solicitud.id}: {solicitud.get_estado_display()}.",
                )
            return redirect("fondos:solicitud_exitosa", solicitud_id=solicitud.id)
    else:
        form = SolicitudDescuentoNominaForm(initial=initial)

    return render(
        request,
        "fondos/solicitud_nomina.html",
        {"form": form, "pedido": pedido, "total": pedido.total},
    )


@login_required
def solicitud_exitosa(request, solicitud_id):
    solicitud = get_object_or_404(
        SolicitudDescuentoNomina.objects.select_related("fondo", "pedido"),
        id=solicitud_id,
        usuario=request.user,
    )
    return render(request, "fondos/solicitud_exitosa.html", {"solicitud": solicitud})


@login_required
def mis_solicitudes(request):
    solicitudes = (
        SolicitudDescuentoNomina.objects
        .filter(usuario=request.user)
        .select_related("fondo", "pedido")
        .order_by("-fecha_solicitud")
    )
    return render(request, "fondos/mis_solicitudes.html", {"solicitudes": solicitudes})


@login_required
def detalle_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(
        SolicitudDescuentoNomina.objects
        .select_related("fondo", "pedido")
        .prefetch_related("pedido__items"),
        id=solicitud_id,
        usuario=request.user,
    )
    return render(request, "fondos/detalle_solicitud.html", {"solicitud": solicitud})


# =====================================================
# PORTAL DEL FONDO (GESTORES)
# =====================================================

def _fondos_gestionables(user):
    if user.is_superuser:
        return FondoEmpleado.objects.all()
    return user.fondos_gestionados.all()


def _solicitudes_gestionables(user):
    qs = SolicitudDescuentoNomina.objects.select_related("fondo", "pedido", "usuario")
    if user.is_superuser:
        return qs
    return qs.filter(fondo__in=user.fondos_gestionados.all())


@login_required
def gestion_solicitudes(request):
    solicitudes = _solicitudes_gestionables(request.user)

    estado = request.GET.get("estado", SolicitudDescuentoNomina.ESTADO_PENDIENTE)
    if estado in dict(SolicitudDescuentoNomina.ESTADOS):
        solicitudes = solicitudes.filter(estado=estado)
    else:
        estado = ""

    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        solicitudes = solicitudes.filter(documento__icontains=busqueda) | solicitudes.filter(
            nombre_completo__icontains=busqueda
        )

    pagina = Paginator(solicitudes.order_by("fecha_solicitud"), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "fondos/gestion_lista.html",
        {
            "solicitudes": pagina,
            "pagina": pagina,
            "estado": estado,
            "estados": SolicitudDescuentoNomina.ESTADOS,
            "busqueda": busqueda,
            "fondos": _fondos_gestionables(request.user),
        },
    )


@login_required
def gestion_detalle(request, solicitud_id):
    solicitud = get_object_or_404(
        _solicitudes_gestionables(request.user).prefetch_related(
            "pedido__items", "historial__usuario"
        ).select_related("afiliado", "decidido_por"),
        id=solicitud_id,
    )

    form = None
    if solicitud.esta_pendiente:
        form = RespuestaFondoForm(request.POST or None, solicitud=solicitud)
        if request.method == "POST" and form.is_valid():
            datos = form.cleaned_data
            try:
                aplicar_decision(
                    solicitud,
                    estado=datos["estado"],
                    valor_aprobado=datos["valor_aprobado"],
                    vinculado=datos["vinculacion_validada"],
                    cupo_reportado=datos["cupo_disponible_reportado"],
                    referencia=datos["referencia_fondo"],
                    respuesta=datos["respuesta_fondo"],
                    origen=SolicitudDescuentoNomina.ORIGEN_GESTOR,
                    usuario=request.user,
                )
            except DecisionInvalida as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Respuesta registrada correctamente.")
                return redirect("fondos:gestion_detalle", solicitud_id=solicitud.id)

    return render(
        request,
        "fondos/gestion_detalle.html",
        {"solicitud": solicitud, "form": form},
    )


@login_required
def gestion_padron(request, fondo_id):
    fondo = get_object_or_404(_fondos_gestionables(request.user), id=fondo_id)
    resultado = None

    form = CargaPadronForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        resultado = importar_padron(
            fondo,
            form.cleaned_data["archivo"].read(),
            desactivar_ausentes=form.cleaned_data["desactivar_ausentes"],
        )
        if resultado.creados or resultado.actualizados:
            messages.success(
                request,
                f"Padrón actualizado: {resultado.creados} nuevos, "
                f"{resultado.actualizados} actualizados, {resultado.desactivados} desactivados.",
            )
        form = CargaPadronForm()

    return render(
        request,
        "fondos/gestion_padron.html",
        {
            "fondo": fondo,
            "form": form,
            "resultado": resultado,
            "total_afiliados": fondo.afiliados.filter(activo=True).count(),
        },
    )
