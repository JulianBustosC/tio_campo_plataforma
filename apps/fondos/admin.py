from django.contrib import admin

from apps.core.cifrado import huella

from .models import AfiliadoFondo, CorteNomina, Finca, FondoEmpleado, HistorialSolicitud, SolicitudDescuentoNomina


class FincaInline(admin.TabularInline):
    model = Finca
    extra = 1
    fields = ("nombre", "municipio", "indicaciones", "activo", "orden")


@admin.register(Finca)
class FincaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "municipio", "fondo", "activo", "orden")
    list_filter = ("fondo", "activo")
    list_editable = ("activo", "orden")
    search_fields = ("nombre", "municipio")


@admin.register(FondoEmpleado)
class FondoEmpleadoAdmin(admin.ModelAdmin):
    inlines = [FincaInline]
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
    list_display = ("nombre", "empresa", "fondo", "cupo_disponible", "activo", "updated_at")
    list_filter = ("fondo", "activo")
    search_fields = ("nombre", "empresa")
    search_help_text = "Busca por nombre o empresa, o por número de documento exacto."
    list_select_related = ("fondo",)
    readonly_fields = ("documento_huella",)

    def get_search_results(self, request, queryset, search_term):
        resultado, duplicados = super().get_search_results(request, queryset, search_term)
        if search_term:
            resultado |= queryset.filter(documento_huella=huella(search_term))
        return resultado, duplicados


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
        "documento_enmascarado",
        "fondo",
        "pedido",
        "valor_solicitado",
        "valor_aprobado",
        "estado",
        "origen_decision",
        "fecha_solicitud",
    )
    list_filter = ("estado", "origen_decision", "fondo", "finca", "fecha_solicitud")
    search_help_text = "Busca por nombre, correo, fondo, afiliado o pedido, o por número de documento exacto."
    search_fields = (
        "nombre_completo",
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
        "autorizacion_datos",
        "autorizacion_fecha",
        "autorizacion_version",
        "anonimizada_en",
        "corte",
        "origen_decision",
        "decidido_por",
        "fecha_solicitud",
        "fecha_respuesta",
    )
    inlines = [HistorialSolicitudInline]

    def get_search_results(self, request, queryset, search_term):
        resultado, duplicados = super().get_search_results(request, queryset, search_term)
        if search_term:
            resultado |= queryset.filter(documento_huella=huella(search_term))
        return resultado, duplicados


@admin.register(CorteNomina)
class CorteNominaAdmin(admin.ModelAdmin):
    list_display = ("fondo", "periodo", "cantidad", "total", "generado_en", "generado_por", "enviado_en")
    list_filter = ("fondo",)
    date_hierarchy = "periodo"
    readonly_fields = ("fondo", "periodo", "cantidad", "total", "generado_en", "generado_por", "enviado_en")

    def has_add_permission(self, request):
        return False
