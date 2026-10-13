from django.core.management.base import BaseCommand, CommandError

from apps.fondos.models import FondoEmpleado
from apps.fondos.services import importar_padron


class Command(BaseCommand):
    help = "Carga o actualiza el padrón de afiliados de un fondo desde un CSV."

    def add_arguments(self, parser):
        parser.add_argument("fondo", help="ID o nombre exacto del fondo.")
        parser.add_argument("archivo", help="Ruta del CSV (documento, cupo_disponible, nombre, empresa, activo).")
        parser.add_argument(
            "--desactivar-ausentes",
            action="store_true",
            help="Desactiva los afiliados que no aparezcan en el archivo.",
        )

    def handle(self, *args, **opciones):
        identificador = opciones["fondo"]
        filtro = {"pk": identificador} if identificador.isdigit() else {"nombre": identificador}
        try:
            fondo = FondoEmpleado.objects.get(**filtro)
        except FondoEmpleado.DoesNotExist:
            raise CommandError(f"No existe el fondo '{identificador}'.")

        with open(opciones["archivo"], "rb") as archivo:
            resultado = importar_padron(
                fondo, archivo.read(), desactivar_ausentes=opciones["desactivar_ausentes"]
            )

        for error in resultado.errores:
            self.stderr.write(self.style.WARNING(error))
        self.stdout.write(self.style.SUCCESS(
            f"{fondo}: {resultado.creados} creados, {resultado.actualizados} actualizados, "
            f"{resultado.desactivados} desactivados, {len(resultado.errores)} errores."
        ))
