from django.contrib import admin

from .models import AfiliadoFondo, FondoEmpleado, HistorialSolicitud, SolicitudDescuentoNomina


@admin.register(FondoEmpleado)
class FondoEmpleadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit", "modo_verificacion", "decision_automatica", "correo", "activo")
    list_filter = ("activo", "modo_verificacion", "decision_automatica")
    search_fields = ("nombre", "nit", "responsable", "correo")
    filter_horizontal = ("gestores",)
    fieldsets = (
        (None, {"fields": ("nombre", "nit", "correo", "telefono", "responsable", "activo", "observaciones")}),
        ("Gestores", {"fields": ("gestores",)}),
        ("Verificación de vinculación", {
            "fields": ("modo_verificacion", "decision_automatica", "api_url", "api_token_env"),
        }),
    )


@admin.register(AfiliadoFondo)
class AfiliadoFondoAdmin(admin.ModelAdmin):
    list_display = ("documento", "nombre", "empresa", "fondo", "cupo_disponible", "activo", "updated_at")
    list_filter = ("fondo", "activo")
    search_fields = ("documento", "nombre", "empresa")
    list_select_related = ("fondo",)


class HistorialSolicitudInline(admin.TabularInline):
    model = HistorialSolicitud
    extra = 0
    can_delete = False
    readonly_fields = ("fecha", "evento", "estado", "usuario", "detalle")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SolicitudDescuentoNomina)
class SolicitudDescuentoNominaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nombre_completo",
        "documento",
        "fondo",
        "pedido",
        "valor_solicitado",
        "valor_aprobado",
        "estado",
        "origen_decision",
        "fecha_solicitud",
    )
    list_filter = ("estado", "origen_decision", "fondo", "fecha_solicitud")
    search_fields = (
        "nombre_completo",
        "documento",
        "correo",
        "fondo__nombre",
        "numero_afiliado",
        "pedido__numero",
    )
    list_select_related = ("fondo", "pedido")
    # Las decisiones se registran solo desde el portal del fondo (services.aplicar_decision),
    # que reserva cupo, actualiza el pedido y deja auditoría.
    readonly_fields = (
        "usuario",
        "pedido",
        "afiliado",
        "valor_solicitado",
        "estado",
        "vinculacion_validada",
        "valor_aprobado",
        "cupo_disponible_reportado",
        "cupo_reservado",
        "verificacion_mensaje",
        "origen_decision",
        "decidido_por",
        "fecha_solicitud",
        "fecha_respuesta",
    )
    inlines = [HistorialSolicitudInline]
