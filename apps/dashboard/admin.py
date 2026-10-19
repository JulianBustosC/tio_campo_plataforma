from django.contrib import admin

from .models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("titulo", "orden", "activo", "fecha_inicio", "fecha_fin")
    list_editable = ("orden", "activo")
    list_filter = ("activo",)
    search_fields = ("titulo", "subtitulo")
