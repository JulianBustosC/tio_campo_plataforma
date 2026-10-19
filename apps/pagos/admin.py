from django.contrib import admin

from .models import TransaccionPago


@admin.register(TransaccionPago)
class TransaccionPagoAdmin(admin.ModelAdmin):
    list_display = ("referencia", "pedido", "proveedor", "monto", "estado", "metodo", "created_at")
    list_filter = ("estado", "proveedor", "metodo", "created_at")
    search_fields = ("referencia", "id_externo", "pedido__numero", "pedido__usuario__email")
    list_select_related = ("pedido",)
    readonly_fields = [f.name for f in TransaccionPago._meta.fields]

    def has_add_permission(self, request):
        return False