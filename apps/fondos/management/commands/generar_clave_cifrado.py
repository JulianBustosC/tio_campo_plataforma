import secrets

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.cifrado import clave_desarrollo, generar_clave


class Command(BaseCommand):
    help = "Genera claves nuevas para DATOS_CIFRADO_CLAVES y DATOS_HUELLA_CLAVE."

    def handle(self, *args, **opciones):
        nueva = generar_clave()
        anteriores = settings.DATOS_CIFRADO_CLAVES or clave_desarrollo()

        self.stdout.write("1) Copie estas líneas en su archivo .env (y guárdelas en un lugar seguro):\n")
        # La nueva va primero (cifra); la anterior queda después para poder leer lo ya guardado.
        self.stdout.write(f"DATOS_CIFRADO_CLAVES={nueva},{anteriores}")
        self.stdout.write(f"DATOS_HUELLA_CLAVE={secrets.token_urlsafe(48)}")
        self.stdout.write("\n2) Reinicie y ejecute:  python manage.py recifrar_datos")
        self.stdout.write("3) Después puede quitar la clave anterior (lo que va después de la coma).")
        self.stdout.write(self.style.WARNING(
            "\nSi pierde DATOS_CIFRADO_CLAVES no podrá leer los documentos y teléfonos guardados."
        ))
