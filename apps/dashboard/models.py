from django.db import models
from django.db.models import Q
from django.utils import timezone


class BannerQuerySet(models.QuerySet):
    def vigentes(self):
        ahora = timezone.now()
        return (
            self.filter(activo=True)
            .filter(Q(fecha_inicio__isnull=True) | Q(fecha_inicio__lte=ahora))
            .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=ahora))
            .order_by("orden", "-id")
        )


class Banner(models.Model):
    """Imágenes del carrusel principal de la tienda, administrables desde el admin."""

    titulo = models.CharField(max_length=120)
    subtitulo = models.CharField(max_length=200, blank=True)
    imagen = models.ImageField(
        upload_to="banners/",
        help_text="Escritorio: 1600 x 500 px (proporción 16:5).",
    )
    imagen_movil = models.ImageField(
        upload_to="banners/",
        blank=True,
        null=True,
        help_text="Opcional. Celular: 1080 x 608 px (proporción 16:9).",
    )
    url = models.CharField(
        max_length=300,
        blank=True,
        help_text="A dónde lleva al hacer clic, por ejemplo /combos/ o /productos/categoria/1/.",
    )
    texto_boton = models.CharField(max_length=40, blank=True, default="Ver más")
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    fecha_inicio = models.DateTimeField(blank=True, null=True)
    fecha_fin = models.DateTimeField(blank=True, null=True)

    objects = BannerQuerySet.as_manager()

    class Meta:
        verbose_name = "Banner"
        verbose_name_plural = "Banners"
        ordering = ["orden", "-id"]

    def __str__(self):
        return self.titulo
