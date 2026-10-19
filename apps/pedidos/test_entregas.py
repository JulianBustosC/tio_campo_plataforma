import base64
import io
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from apps.fondos.models import Finca, FondoEmpleado, SolicitudDescuentoNomina
from .models import Entrega, Pedido


def firma_png(en_blanco=False):
    imagen = Image.new("RGBA", (400, 150), (0, 0, 0, 0))
    if not en_blanco:
        ImageDraw.Draw(imagen).line([(20, 100), (120, 40), (220, 110), (380, 30)], fill=(11, 59, 35, 255), width=4)
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return "data:image/png;base64," + base64.b64encode(salida.getvalue()).decode()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EntregasTest(TestCase):
    def setUp(self):
        # Las firmas de prueba van a una carpeta temporal.
        self.carpeta = tempfile.mkdtemp()
        self.campo_firma = Entrega._meta.get_field("firma")
        self.almacen_original = self.campo_firma.storage
        self.campo_firma.storage = FileSystemStorage(location=self.carpeta)

        User = get_user_model()
        self.repartidor = User.objects.create_user(username="repartidor", password="x")
        self.repartidor.groups.add(Group.objects.get(name="Repartidores"))
        self.cliente = User.objects.create_user(username="ana", password="x", email="ana@example.com", first_name="Ana")
        self.gestor = User.objects.create_user(username="gestor", password="x")
        self.extrano = User.objects.create_user(username="extrano", password="x")

        self.fondo = FondoEmpleado.objects.create(nombre="Fondo Flores")
        self.fondo.gestores.add(self.gestor)
        self.finca = Finca.objects.create(fondo=self.fondo, nombre="La Esperanza", municipio="Madrid")

    def tearDown(self):
        self.campo_firma.storage = self.almacen_original
        shutil.rmtree(self.carpeta, ignore_errors=True)

    def pedido(self, metodo, estado, **extra):
        return Pedido.objects.create(
            usuario=self.cliente, metodo_pago=metodo, estado=estado,
            subtotal=Decimal("50000"), total=Decimal("50000"),
            direccion_entrega="Calle 1", ciudad="Bogotá", **extra,
        )

    def pedido_nomina(self):
        pedido = self.pedido(Pedido.METODO_NOMINA, Pedido.ESTADO_APROBADO_NOMINA, valor_nomina=Decimal("50000"))
        SolicitudDescuentoNomina.objects.create(
            usuario=self.cliente, fondo=self.fondo, finca=self.finca, pedido=pedido,
            nombre_completo="Ana Pérez", documento="123", empresa="Flores SAS",
            valor_solicitado=Decimal("50000"), valor_aprobado=Decimal("50000"),
            estado=SolicitudDescuentoNomina.ESTADO_APROBADA,
        )
        return pedido

    # ------------------------------------------------------------ permisos y lista

    def test_solo_repartidores_ven_las_entregas(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("pedidos:entregas")).status_code, 403)

        listo = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PAGADO)
        contra_entrega = self.pedido(Pedido.METODO_OTRO, Pedido.ESTADO_PENDIENTE_PAGO)
        sin_pagar = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PENDIENTE_PAGO)
        nomina = self.pedido_nomina()

        self.client.force_login(self.repartidor)
        respuesta = self.client.get(reverse("pedidos:entregas"))
        for pedido in (listo, contra_entrega, nomina):
            self.assertContains(respuesta, pedido.numero)
        self.assertNotContains(respuesta, sin_pagar.numero)
        self.assertContains(respuesta, "La Esperanza")
        self.assertContains(respuesta, "Cobrar $50.000")

    # ------------------------------------------------------------ entrega sin firma

    def test_entrega_normal_sin_firma(self):
        pedido = self.pedido(Pedido.METODO_OTRO, Pedido.ESTADO_PENDIENTE_PAGO)
        self.client.force_login(self.repartidor)
        respuesta = self.client.get(reverse("pedidos:entrega_registrar", args=[pedido.id]))
        self.assertNotContains(respuesta, "tc-firma-lienzo")           # sin espacio de firma

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("pedidos:entrega_registrar", args=[pedido.id]), {"recibido_por": "Ana Pérez"})
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.ESTADO_ENTREGADO)
        self.assertEqual(pedido.entrega.entregado_por, self.repartidor)
        self.assertIn("fue entregado", mail.outbox[0].subject)

        # No se puede entregar dos veces.
        respuesta = self.client.get(reverse("pedidos:entrega_registrar", args=[pedido.id]))
        self.assertRedirects(respuesta, reverse("pedidos:entrega_constancia", args=[pedido.id]))

    def test_no_se_entrega_un_pedido_sin_pagar(self):
        pedido = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PENDIENTE_PAGO)
        self.client.force_login(self.repartidor)
        respuesta = self.client.post(reverse("pedidos:entrega_registrar", args=[pedido.id]), {"recibido_por": "Ana"})
        self.assertContains(respuesta, "no se puede entregar")
        self.assertFalse(Entrega.objects.exists())

    # ------------------------------------------------------------ nómina con firma

    def test_nomina_exige_firma(self):
        pedido = self.pedido_nomina()
        self.client.force_login(self.repartidor)
        url = reverse("pedidos:entrega_registrar", args=[pedido.id])
        self.assertContains(self.client.get(url), "tc-firma-lienzo")

        self.assertContains(self.client.post(url, {"recibido_por": "Ana Pérez"}), "debe firmar")
        self.assertContains(
            self.client.post(url, {"recibido_por": "Ana Pérez", "firma": firma_png(en_blanco=True)}), "debe firmar"
        )
        self.assertContains(
            self.client.post(url, {"recibido_por": "Ana Pérez", "firma": "data:image/png;base64,no-es-imagen"}),
            "formato válido",
        )
        self.assertFalse(Entrega.objects.exists())

        self.client.post(url, {"recibido_por": "Ana Pérez", "firma": firma_png()})
        entrega = Entrega.objects.get()
        self.assertTrue(entrega.firma)
        # La firma queda fuera de la carpeta pública /media/.
        self.assertFalse(Path(entrega.firma.path).is_relative_to(Path(settings.MEDIA_ROOT)))

    def test_quien_puede_ver_la_firma(self):
        pedido = self.pedido_nomina()
        self.client.force_login(self.repartidor)
        self.client.post(reverse("pedidos:entrega_registrar", args=[pedido.id]),
                         {"recibido_por": "Ana Pérez", "firma": firma_png()})
        url = reverse("pedidos:entrega_firma", args=[pedido.id])

        for usuario, esperado in ((self.repartidor, 200), (self.cliente, 200), (self.gestor, 200), (self.extrano, 404)):
            self.client.force_login(usuario)
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, esperado, usuario.username)
            if esperado == 200:
                self.assertEqual(respuesta["Content-Type"], "image/png")

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 404)

        # El gestor ve la entrega en su portal y el cliente en su pedido.
        self.client.force_login(self.gestor)
        detalle = self.client.get(reverse("fondos:gestion_detalle", args=[pedido.solicitud_nomina.id]))
        self.assertContains(detalle, "Ver constancia de entrega")
        self.client.force_login(self.cliente)
        self.assertContains(self.client.get(reverse("pedidos:confirmacion", args=[pedido.id])), "Ver constancia")
        constancia = self.client.get(reverse("pedidos:entrega_constancia", args=[pedido.id]))
        self.assertContains(constancia, "Firma de quien recibe")

    def test_reporte_incluye_fecha_de_entrega(self):
        from apps.fondos.reportes import COLUMNAS, filas, periodo_desde_texto

        pedido = self.pedido_nomina()
        self.client.force_login(self.repartidor)
        self.client.post(reverse("pedidos:entrega_registrar", args=[pedido.id]),
                         {"recibido_por": "Ana Pérez", "firma": firma_png()})
        self.assertIn(("fecha_entrega", "Fecha de entrega"), COLUMNAS)
        fila = next(filas(SolicitudDescuentoNomina.objects.all(), periodo_desde_texto("2026-10")))
        self.assertTrue(fila["fecha_entrega"])

    def test_anonimizar_borra_la_firma(self):
        from datetime import timedelta
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        pedido = self.pedido_nomina()
        self.client.force_login(self.repartidor)
        self.client.post(reverse("pedidos:entrega_registrar", args=[pedido.id]),
                         {"recibido_por": "Ana Pérez", "firma": firma_png()})
        ruta = Path(Entrega.objects.get().firma.path)
        self.assertTrue(ruta.exists())
        Pedido.objects.filter(pk=pedido.pk).update(created_at=timezone.now() - timedelta(days=400))
        call_command("anonimizar_datos", dias=30, stdout=StringIO())
        entrega = Entrega.objects.get()
        self.assertFalse(entrega.firma)
        self.assertFalse(ruta.exists())
        self.assertEqual(entrega.recibido_por, "Titular anonimizado")


    # ------------------------------------------------------------ menú y pestañas

    def test_menu_muestra_entregas_solo_con_permiso(self):
        self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PAGADO)
        self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PAGADO)

        self.client.force_login(self.cliente)
        self.assertNotContains(self.client.get(reverse("dashboard")), "tc-catbar__entregas")

        self.client.force_login(self.repartidor)
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "tc-catbar__entregas")
        self.assertContains(respuesta, '<span class="tc-catbar__pendientes" title="Pedidos por entregar">2</span>', html=True)

    def test_pestanas_por_entregar_y_entregados(self):
        pendiente = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PAGADO)
        entregado = self.pedido(Pedido.METODO_OTRO, Pedido.ESTADO_PENDIENTE_PAGO)
        self.client.force_login(self.repartidor)
        self.client.post(reverse("pedidos:entrega_registrar", args=[entregado.id]), {"recibido_por": "Luis Gómez"}, follow=True)

        por_entregar = self.client.get(reverse("pedidos:entregas"))
        self.assertContains(por_entregar, pendiente.numero)
        self.assertNotContains(por_entregar, entregado.numero)

        entregados = self.client.get(reverse("pedidos:entregas"), {"vista": "entregados"})
        self.assertContains(entregados, entregado.numero)
        self.assertContains(entregados, "Luis Gómez")
        self.assertNotContains(entregados, pendiente.numero)
        self.assertContains(entregados, reverse("pedidos:entrega_constancia", args=[entregado.id]))

        # Búsqueda por quien recibió y filtro de fechas.
        self.assertContains(self.client.get(reverse("pedidos:entregas"), {"vista": "entregados", "q": "Luis"}), entregado.numero)
        self.assertNotContains(
            self.client.get(reverse("pedidos:entregas"), {"vista": "entregados", "desde": "2099-01-01"}), entregado.numero
        )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AvisoEntregaTest(TestCase):
    """El aviso del fondo solo aparece cuando el pago es por nómina."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="ana", password="x", email="ana@example.com")
        self.client.force_login(self.usuario)

    def crear(self, metodo):
        return Pedido.objects.create(
            usuario=self.usuario, metodo_pago=metodo, estado=Pedido.ESTADO_PENDIENTE_PAGO,
            subtotal=Decimal("1000"), total=Decimal("1000"), direccion_entrega="Calle 1", ciudad="Bogotá",
        )

    def test_confirmacion(self):
        otro = self.crear(Pedido.METODO_OTRO)
        respuesta = self.client.get(reverse("pedidos:confirmacion", args=[otro.id]))
        self.assertNotContains(respuesta, "se acuerda con el fondo")
        self.assertContains(respuesta, "Te contactaremos para coordinar la entrega")

        nomina = self.crear(Pedido.METODO_NOMINA)
        self.assertContains(self.client.get(reverse("pedidos:confirmacion", args=[nomina.id])),
                            "La fecha de entrega se acuerda con el fondo de empleados")

    def test_paginas_generales_sin_aviso_del_fondo(self):
        for url in (reverse("dashboard"), reverse("productos:lista")):
            self.assertNotContains(self.client.get(url), "se acuerda con")

    def test_correo(self):
        from .services import notificar_pedido_creado

        notificar_pedido_creado(self.crear(Pedido.METODO_OTRO))
        notificar_pedido_creado(self.crear(Pedido.METODO_NOMINA))
        self.assertNotIn("fondo de empleados", mail.outbox[0].body)
        self.assertIn("se acuerda con tu fondo de empleados", mail.outbox[1].body)
