from django.conf import settings


def datos_personales(request):
    return {
        "POLITICA_DATOS_VERSION": settings.POLITICA_DATOS_VERSION,
        "RETENCION_DATOS_DIAS": settings.RETENCION_DATOS_DIAS,
        "RESPONSABLE_DATOS": settings.RESPONSABLE_DATOS,
    }
