from django.core.management.base import BaseCommand, CommandError

from apps.fondos.models import FondoEmpleado
from apps.fondos.reportes import (
    ReporteError,
    cerrar_corte,
    enviar_corte_por_correo,
    periodo_desde_texto,
    periodo_por_defecto,
    resumen,
    solicitudes_del_periodo,
)


class Command(BaseCommand):
    help = (
        "Muestra, cierra y envía el corte mensual de descuentos por nómina de cada fondo. "
        "Programado el día 1 de cada mes con --cerrar --enviar, envía a cada fondo su archivo."
    )

    def add_arguments(self, parser):
        parser.add_argument("--mes", help="AAAA-MM (por defecto, el mes anterior).")
        parser.add_argument("--fondo", help="ID o nombre exacto del fondo (por defecto, todos los activos).")
        parser.add_argument("--cerrar", action="store_true", help="Cierra el corte (si no, solo muestra).")
        parser.add_argument("--enviar", action="store_true", help="Envía el Excel al correo del fondo al cerrar.")

    def handle(self, *args, mes=None, fondo=None, cerrar=False, enviar=False, **opciones):
        try:
            periodo = periodo_desde_texto(mes) if mes else periodo_por_defecto()
        except ReporteError as exc:
            raise CommandError(str(exc))

        fondos = FondoEmpleado.objects.filter(activo=True)
        if fondo:
            fondos = fondos.filter(pk=fondo) if fondo.isdigit() else fondos.filter(nombre=fondo)
            if not fondos.exists():
                raise CommandError(f"No existe el fondo activo '{fondo}'.")

        for f in fondos:
            corte, solicitudes = solicitudes_del_periodo(f, periodo)
            datos = resumen(solicitudes)
            estado = "cerrado" if corte else "abierto"
            self.stdout.write(f"{f} · {periodo:%Y-%m} ({estado}): {datos.cantidad} descuentos, ${datos.total:,.2f}")
            if cerrar and not corte and datos.cantidad:
                corte = cerrar_corte(f, periodo)
                self.stdout.write(self.style.SUCCESS(f"  Corte cerrado (#{corte.id})."))
                if enviar:
                    try:
                        enviar_corte_por_correo(corte)
                        self.stdout.write(self.style.SUCCESS("  Archivo enviado al fondo."))
                    except ReporteError as exc:
                        self.stderr.write(self.style.WARNING(f"  No se envió: {exc}"))
