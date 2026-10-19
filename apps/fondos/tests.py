import json
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.carrito.models import Carrito, CarritoItem
from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.pedidos.models import Pedido
from apps.productos.models import Producto, ProductoPresentacion
from apps.core.cifrado import huella

from .models import AfiliadoFondo, Finca, FondoEmpleado, HistorialSolicitud, SolicitudDescuentoNomina
from .services import importar_padron
from .verificacion import calcular_decision, normalizar_documento

S = SolicitudDescuentoNomina


class CalcularDecisionTest(TestCase):
    def test_reglas(self):
        cien = Decimal("100000")
        self.assertEqual(calcular_decision(cien, True, Decimal("150000")), (S.ESTADO_APROBADA, cien))
        self.assertEqual(calcular_decision(cien, True, cien), (S.ESTADO_APROBADA, cien))
        self.assertEqual(
            calcular_decision(cien, True, Decimal("40000")),
            (S.ESTADO_APROBADA_PARCIAL, Decimal("40000")),
        )
        self.assertEqual(calcular_decision(cien, True, Decimal("0")), (S.ESTADO_RECHAZADA, Decimal("0")))
        self.assertEqual(calcular_decision(cien, False, Decimal("999999")), (S.ESTADO_RECHAZADA, Decimal("0")))

    def test_normalizar_documento(self):
        self.assertEqual(normalizar_documento(" 1.020.304-5 "), "10203045")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BaseNominaTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cliente = User.objects.create_user(
            username="cliente", password="clave12345", email="cliente@example.com"
        )
        self.gestor = User.objects.create_user(
            username="gestor", password="clave12345", email="gestor@example.com"
        )

        unidad = UnidadMedida.objects.create(nombre="Gramo", abreviatura="g")
        presentacion = Presentacion.objects.create(nombre="500 g", cantidad=500, unidad=unidad)
        categoria = Categoria.objects.create(nombre="Prueba")
        marca = Marca.objects.create(nombre="Marca prueba")
        producto = Producto.objects.create(
            codigo="PR-001", nombre="Producto prueba", categoria=categoria, marca=marca
        )
        self.producto_presentacion = ProductoPresentacion.objects.create(
            producto=producto,
            codigo="PR-001-500",
            presentacion=presentacion,
            precio=Decimal("50000.00"),
        )
        self.fondo = FondoEmpleado.objects.create(nombre="Fondo prueba", correo="fondo@example.com")
        self.fondo.gestores.add(self.gestor)

    def comprar_por_nomina(self, documento="123456789", cantidad=2):
        """Carrito -> checkout -> formulario de nómina. Devuelve (pedido, solicitud, respuesta)."""
        self.client.force_login(self.cliente)
        carrito, _ = Carrito.objects.get_or_create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(
            carrito=carrito,
            presentacion=self.producto_presentacion,
            cantidad=cantidad,
            precio_unitario=Decimal("50000.00"),
        )
        self.client.post(
            reverse("pedidos:checkout"),
            {
                "direccion_entrega": "Calle 1 # 2-3",
                "ciudad": "Bogotá",
                "metodo_pago": Pedido.METODO_NOMINA,
            },
        )
        pedido = Pedido.objects.filter(usuario=self.cliente).latest("created_at")
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(
                reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]),
                {
                    "fondo": self.fondo.id,
                    "nombre_completo": "Cliente de Prueba",
                    "documento": documento,
                    "telefono": "3001234567",
                    "correo": "cliente@example.com",
                    "empresa": "Empresa prueba",
                    "autoriza_tratamiento": "on",
                },
            )
        solicitud = S.objects.get(pedido=pedido)
        pedido.refresh_from_db()
        return pedido, solicitud, respuesta


class FlujoManualTest(BaseNominaTest):
    def test_flujo_completo_nomina_manual(self):
        pedido, solicitud, respuesta = self.comprar_por_nomina()
        self.assertRedirects(respuesta, reverse("fondos:solicitud_exitosa", args=[solicitud.id]))
        self.assertEqual(solicitud.valor_solicitado, Decimal("100000.00"))
        self.assertEqual(solicitud.estado, S.ESTADO_PENDIENTE)
        self.assertEqual(pedido.estado, Pedido.ESTADO_EN_REVISION_NOMINA)

        # Se notificó al fondo y al gestor.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].to), {"fondo@example.com", "gestor@example.com"})

        self.client.force_login(self.gestor)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(
                reverse("fondos:gestion_detalle", args=[solicitud.id]),
                {
                    "vinculacion_validada": "True",
                    "estado": S.ESTADO_APROBADA,
                    "cupo_disponible_reportado": "150000",
                    "valor_aprobado": "100000",
                    "referencia_fondo": "REF-001",
                    "respuesta_fondo": "Aprobado",
                },
            )
        self.assertRedirects(respuesta, reverse("fondos:gestion_detalle", args=[solicitud.id]))
        solicitud.refresh_from_db()
        pedido.refresh_from_db()
        self.assertTrue(solicitud.vinculacion_validada)
        self.assertEqual(solicitud.estado, S.ESTADO_APROBADA)
        self.assertEqual(solicitud.origen_decision, S.ORIGEN_GESTOR)
        self.assertEqual(solicitud.decidido_por, self.gestor)
        self.assertEqual(pedido.estado, Pedido.ESTADO_APROBADO_NOMINA)
        self.assertEqual(pedido.valor_nomina, Decimal("100000"))
        self.assertEqual(mail.outbox[-1].to, ["cliente@example.com"])
        self.assertTrue(
            solicitud.historial.filter(evento=HistorialSolicitud.EVENTO_DECISION).exists()
        )

    def test_gestor_aprueba_parcial(self):
        pedido, solicitud, _ = self.comprar_por_nomina()
        self.client.force_login(self.gestor)
        self.client.post(
            reverse("fondos:gestion_detalle", args=[solicitud.id]),
            {
                "vinculacion_validada": "True",
                "estado": S.ESTADO_APROBADA_PARCIAL,
                "cupo_disponible_reportado": "60000",
                "valor_aprobado": "60000",
            },
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.ESTADO_APROBADO_PARCIAL)
        self.assertEqual(pedido.saldo_pendiente, Decimal("40000"))

    def test_no_vinculado_no_puede_aprobarse(self):
        _, solicitud, _ = self.comprar_por_nomina()
        self.client.force_login(self.gestor)
        respuesta = self.client.post(
            reverse("fondos:gestion_detalle", args=[solicitud.id]),
            {
                "vinculacion_validada": "False",
                "estado": S.ESTADO_APROBADA,
                "cupo_disponible_reportado": "100000",
                "valor_aprobado": "100000",
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, S.ESTADO_PENDIENTE)

    def test_solicitud_decidida_no_se_puede_redecidir(self):
        _, solicitud, _ = self.comprar_por_nomina()
        self.client.force_login(self.gestor)
        datos = {"vinculacion_validada": "False", "estado": S.ESTADO_RECHAZADA}
        self.client.post(reverse("fondos:gestion_detalle", args=[solicitud.id]), datos)
        datos = {
            "vinculacion_validada": "True",
            "estado": S.ESTADO_APROBADA,
            "cupo_disponible_reportado": "100000",
            "valor_aprobado": "100000",
        }
        self.client.post(reverse("fondos:gestion_detalle", args=[solicitud.id]), datos)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, S.ESTADO_RECHAZADA)

    def test_gestor_de_otro_fondo_no_ve_la_solicitud(self):
        _, solicitud, _ = self.comprar_por_nomina()
        intruso = get_user_model().objects.create_user(username="otro", password="x")
        otro_fondo = FondoEmpleado.objects.create(nombre="Otro fondo")
        otro_fondo.gestores.add(intruso)
        self.client.force_login(intruso)
        respuesta = self.client.get(reverse("fondos:gestion_detalle", args=[solicitud.id]))
        self.assertEqual(respuesta.status_code, 404)


class VerificacionPadronTest(BaseNominaTest):
    def setUp(self):
        super().setUp()
        self.fondo.modo_verificacion = FondoEmpleado.MODO_PADRON
        self.fondo.decision_automatica = True
        self.fondo.save()

    def afiliar(self, documento="123456789", cupo="500000", activo=True):
        return AfiliadoFondo.objects.create(
            fondo=self.fondo, documento=documento, nombre="Cliente", cupo_disponible=Decimal(cupo), activo=activo
        )

    def test_aprobacion_total_automatica_y_reserva_cupo(self):
        afiliado = self.afiliar(cupo="500000")
        pedido, solicitud, _ = self.comprar_por_nomina(documento="123.456.789")
        self.assertEqual(solicitud.estado, S.ESTADO_APROBADA)
        self.assertEqual(solicitud.origen_decision, S.ORIGEN_AUTOMATICO)
        self.assertEqual(solicitud.valor_aprobado, Decimal("100000"))
        self.assertEqual(pedido.estado, Pedido.ESTADO_APROBADO_NOMINA)
        afiliado.refresh_from_db()
        self.assertEqual(afiliado.cupo_disponible, Decimal("400000"))
        # Decisión automática: no se molesta al gestor, sí se avisa al comprador.
        self.assertEqual([m.to for m in mail.outbox], [["cliente@example.com"]])

    def test_aprobacion_parcial_automatica(self):
        afiliado = self.afiliar(cupo="30000")
        pedido, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_APROBADA_PARCIAL)
        self.assertEqual(solicitud.valor_aprobado, Decimal("30000"))
        self.assertEqual(pedido.estado, Pedido.ESTADO_APROBADO_PARCIAL)
        self.assertEqual(pedido.saldo_pendiente, Decimal("70000"))
        afiliado.refresh_from_db()
        self.assertEqual(afiliado.cupo_disponible, Decimal("0"))

    def test_rechazo_si_no_esta_en_padron(self):
        pedido, solicitud, _ = self.comprar_por_nomina(documento="999")
        self.assertEqual(solicitud.estado, S.ESTADO_RECHAZADA)
        self.assertFalse(solicitud.vinculacion_validada)
        self.assertEqual(pedido.estado, Pedido.ESTADO_RECHAZADO_NOMINA)

    def test_rechazo_si_afiliado_inactivo(self):
        self.afiliar(activo=False)
        _, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_RECHAZADA)

    def test_cupo_se_consume_entre_compras(self):
        self.afiliar(cupo="150000")
        _, primera, _ = self.comprar_por_nomina()
        _, segunda, _ = self.comprar_por_nomina()
        self.assertEqual(primera.estado, S.ESTADO_APROBADA)
        self.assertEqual(segunda.estado, S.ESTADO_APROBADA_PARCIAL)
        self.assertEqual(segunda.valor_aprobado, Decimal("50000"))

    def test_sin_decision_automatica_queda_para_gestor_con_sugerencia(self):
        self.fondo.decision_automatica = False
        self.fondo.save()
        self.afiliar(cupo="80000")
        _, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_PENDIENTE)
        self.assertTrue(solicitud.vinculacion_validada)
        self.assertEqual(solicitud.cupo_disponible_reportado, Decimal("80000"))

        # El gestor no puede aprobar más que el cupo vigente en el padrón.
        self.client.force_login(self.gestor)
        self.client.post(
            reverse("fondos:gestion_detalle", args=[solicitud.id]),
            {
                "vinculacion_validada": "True",
                "estado": S.ESTADO_APROBADA,
                "cupo_disponible_reportado": "100000",
                "valor_aprobado": "100000",
            },
        )
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, S.ESTADO_PENDIENTE)

    def test_cancelar_pedido_devuelve_cupo(self):
        afiliado = self.afiliar(cupo="30000")
        pedido, _, _ = self.comprar_por_nomina()
        self.client.post(reverse("pedidos:cancelar", args=[pedido.id]))
        pedido.refresh_from_db()
        afiliado.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.ESTADO_CANCELADO)
        self.assertEqual(afiliado.cupo_disponible, Decimal("30000"))

    def test_pagar_saldo_tras_aprobacion_parcial(self):
        self.afiliar(cupo="30000")
        pedido, _, _ = self.comprar_por_nomina()
        self.client.post(
            reverse("pedidos:pagar_saldo", args=[pedido.id]),
            {"metodo_pago_saldo": Pedido.METODO_ELECTRONICO},
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.ESTADO_PENDIENTE_PAGO)
        self.assertEqual(pedido.metodo_pago_saldo, Pedido.METODO_ELECTRONICO)
        self.assertEqual(pedido.valor_nomina, Decimal("30000"))


class VerificacionApiTest(BaseNominaTest):
    def setUp(self):
        super().setUp()
        self.fondo.modo_verificacion = FondoEmpleado.MODO_API
        self.fondo.decision_automatica = True
        self.fondo.api_url = "https://fondo.example.com/verificar"
        self.fondo.api_token_env = "TOKEN_FONDO_PRUEBA"
        self.fondo.save()

    def respuesta_api(self, datos):
        respuesta = mock.MagicMock()
        respuesta.read.return_value = json.dumps(datos).encode()
        respuesta.__enter__.return_value = respuesta
        return respuesta

    @mock.patch.dict("os.environ", {"TOKEN_FONDO_PRUEBA": "secreto"})
    @mock.patch("apps.fondos.verificacion.urllib.request.urlopen")
    def test_api_aprueba_parcial(self, urlopen):
        urlopen.return_value = self.respuesta_api(
            {"vinculado": True, "cupo_disponible": 25000, "referencia": "API-9"}
        )
        pedido, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_APROBADA_PARCIAL)
        self.assertEqual(solicitud.valor_aprobado, Decimal("25000"))
        self.assertEqual(solicitud.referencia_fondo, "API-9")
        peticion = urlopen.call_args.args[0]
        self.assertEqual(peticion.get_header("Authorization"), "Bearer secreto")

    @mock.patch("apps.fondos.verificacion.urllib.request.urlopen")
    def test_api_no_vinculado_rechaza(self, urlopen):
        urlopen.return_value = self.respuesta_api({"vinculado": False, "mensaje": "No es empleado"})
        _, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_RECHAZADA)
        self.assertEqual(solicitud.respuesta_fondo, "No es empleado")

    @mock.patch("apps.fondos.verificacion.urllib.request.urlopen")
    def test_api_caida_queda_para_revision_manual(self, urlopen):
        import urllib.error

        urlopen.side_effect = urllib.error.URLError("timeout")
        pedido, solicitud, _ = self.comprar_por_nomina()
        self.assertEqual(solicitud.estado, S.ESTADO_PENDIENTE)
        self.assertEqual(pedido.estado, Pedido.ESTADO_EN_REVISION_NOMINA)
        self.assertIn("revisión manual", solicitud.verificacion_mensaje)


class ImportarPadronTest(BaseNominaTest):
    def test_importa_y_actualiza(self):
        AfiliadoFondo.objects.create(fondo=self.fondo, documento="111", cupo_disponible=1)
        AfiliadoFondo.objects.create(fondo=self.fondo, documento="333", cupo_disponible=1)
        csv_texto = (
            "documento;nombre;empresa;cupo_disponible;activo\n"
            "1.11;Ana;Tío Campo;1.500.000;si\n"
            "222;Luis;Tío Campo;250000,50;si\n"
            ";Sin documento;;100;si\n"
            "444;Malo;;abc;si\n"
        )
        resultado = importar_padron(self.fondo, csv_texto.encode(), desactivar_ausentes=True)
        self.assertEqual((resultado.creados, resultado.actualizados, resultado.desactivados), (1, 1, 1))
        self.assertEqual(len(resultado.errores), 2)
        self.assertEqual(
            AfiliadoFondo.objects.get(documento_huella=huella("111")).cupo_disponible, Decimal("1500000")
        )
        self.assertEqual(
            AfiliadoFondo.objects.get(documento_huella=huella("222")).cupo_disponible, Decimal("250000.50")
        )
        self.assertFalse(AfiliadoFondo.objects.get(documento_huella=huella("333")).activo)

    def test_columnas_obligatorias(self):
        resultado = importar_padron(self.fondo, b"cedula,cupo\n1,2\n")
        self.assertTrue(resultado.errores)
        self.assertFalse(AfiliadoFondo.objects.exists())

    def test_carga_desde_portal_del_gestor(self):
        self.client.force_login(self.gestor)
        archivo = SimpleUploadedFile("padron.csv", b"documento,cupo_disponible\n555,90000\n", "text/csv")
        respuesta = self.client.post(
            reverse("fondos:gestion_padron", args=[self.fondo.id]), {"archivo": archivo}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(AfiliadoFondo.objects.filter(fondo=self.fondo, documento_huella=huella("555")).exists())

    def test_cliente_no_puede_cargar_padron(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.get(reverse("fondos:gestion_padron", args=[self.fondo.id]))
        self.assertEqual(respuesta.status_code, 404)


class PaginasRenderizanTest(BaseNominaTest):
    """Humo: cada pantalla del flujo responde 200 y muestra lo esencial."""

    def test_pantallas_del_flujo(self):
        self.fondo.modo_verificacion = FondoEmpleado.MODO_PADRON
        self.fondo.decision_automatica = True
        self.fondo.save()
        AfiliadoFondo.objects.create(fondo=self.fondo, documento="123456789", cupo_disponible=Decimal("30000"))
        pedido, solicitud, _ = self.comprar_por_nomina()

        for url, texto in [
            (reverse("dashboard"), "Tío Campo"),
            (reverse("pedidos:confirmacion", args=[pedido.id]), "Pagar saldo"),
            (reverse("pedidos:mis_pedidos"), pedido.numero),
            (reverse("fondos:mis_solicitudes"), ""),
            (reverse("fondos:detalle_solicitud", args=[solicitud.id]), "Aprobada parcialmente"),
            (reverse("fondos:solicitud_exitosa", args=[solicitud.id]), "pagar la diferencia"),
        ]:
            respuesta = self.client.get(url)
            self.assertContains(respuesta, texto, msg_prefix=url)

        self.client.force_login(self.gestor)
        for url, texto in [
            (reverse("fondos:gestion_solicitudes") + "?estado=todas", "Padrón Fondo prueba"),
            (reverse("fondos:gestion_detalle", args=[solicitud.id]), "Decisión registrada"),
            (reverse("fondos:gestion_padron", args=[self.fondo.id]), "Formato del archivo"),
        ]:
            respuesta = self.client.get(url)
            self.assertContains(respuesta, texto, msg_prefix=url)

        self.client.logout()
        for nombre in ("login", "registro"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)


class ProteccionDatosTest(BaseNominaTest):
    """Ley 1581 de 2012: cifrado en reposo, autorización y retención."""

    def valor_en_bd(self, tabla, columna, pk):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {columna} FROM {tabla} WHERE id = %s", [pk])
            return cursor.fetchone()[0]

    def test_documento_y_telefono_se_guardan_cifrados(self):
        _, solicitud, _ = self.comprar_por_nomina(documento="1.020.304.050")
        crudo = self.valor_en_bd("fondos_solicituddescuentonomina", "documento", solicitud.id)
        self.assertTrue(crudo.startswith("enc1:"))
        self.assertNotIn("1020304050", crudo)
        self.assertNotIn("3001234567", self.valor_en_bd("fondos_solicituddescuentonomina", "telefono", solicitud.id))

        solicitud.refresh_from_db()
        self.assertEqual(solicitud.documento, "1.020.304.050")      # se lee en claro
        self.assertEqual(solicitud.telefono, "3001234567")
        self.assertEqual(solicitud.documento_enmascarado, "••••••4050")


    def test_padron_cifrado_sigue_verificando(self):
        self.fondo.modo_verificacion = FondoEmpleado.MODO_PADRON
        self.fondo.decision_automatica = True
        self.fondo.save()
        importar_padron(self.fondo, b"documento,cupo_disponible\n1020304050,500000\n")
        afiliado = AfiliadoFondo.objects.get()
        self.assertNotIn("1020304050", self.valor_en_bd("fondos_afiliadofondo", "documento", afiliado.id))

        _, solicitud, _ = self.comprar_por_nomina(documento="1.020.304.050")
        self.assertEqual(solicitud.estado, S.ESTADO_APROBADA)
        self.assertEqual(solicitud.afiliado, afiliado)

        # Reimportar actualiza (no duplica) aunque el documento esté cifrado.
        resultado = importar_padron(self.fondo, b"documento,cupo_disponible\n1020304050,90000\n")
        self.assertEqual((resultado.creados, resultado.actualizados), (0, 1))

    def test_gestor_busca_por_documento_exacto(self):
        _, solicitud, _ = self.comprar_por_nomina(documento="123456789")
        self.client.force_login(self.gestor)
        url = reverse("fondos:gestion_solicitudes")
        self.assertContains(self.client.get(url, {"estado": "todas", "q": "123.456.789"}), f"#{solicitud.id}")
        self.assertNotContains(self.client.get(url, {"estado": "todas", "q": "999"}), f"#{solicitud.id}")
        self.assertNotContains(self.client.get(url, {"estado": "todas"}), "123456789")   # listado enmascarado

    def test_autorizacion_obligatoria_y_registrada(self):
        self.client.force_login(self.cliente)
        carrito, _ = Carrito.objects.get_or_create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(
            carrito=carrito, presentacion=self.producto_presentacion, cantidad=1, precio_unitario=Decimal("50000")
        )
        self.client.post(reverse("pedidos:checkout"), {
            "direccion_entrega": "Calle 1", "ciudad": "Bogotá", "metodo_pago": Pedido.METODO_NOMINA,
        })
        pedido = Pedido.objects.get(usuario=self.cliente)
        datos = {
            "fondo": self.fondo.id, "nombre_completo": "Cliente de Prueba", "documento": "123",
            "empresa": "Empresa prueba",
        }
        respuesta = self.client.post(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]), datos)
        self.assertContains(respuesta, "debes autorizar el tratamiento")
        self.assertFalse(S.objects.exists())

        datos["autoriza_tratamiento"] = "on"
        self.client.post(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]), datos)
        solicitud = S.objects.get()
        self.assertTrue(solicitud.autorizacion_datos)
        self.assertIsNotNone(solicitud.autorizacion_fecha)
        self.assertEqual(solicitud.autorizacion_version, settings.POLITICA_DATOS_VERSION)

    def test_politica_publica(self):
        respuesta = self.client.get(reverse("politica_datos"))
        self.assertContains(respuesta, "Derechos del titular")
        self.assertContains(respuesta, settings.POLITICA_DATOS_VERSION)

    def test_anonimizar_datos_vencidos(self):
        from datetime import timedelta
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        pedido, solicitud, _ = self.comprar_por_nomina()
        self.client.force_login(self.gestor)
        self.client.post(reverse("fondos:gestion_detalle", args=[solicitud.id]), {
            "vinculacion_validada": "False", "estado": S.ESTADO_RECHAZADA,
        })
        Pedido.objects.filter(pk=pedido.pk).update(estado=Pedido.ESTADO_CANCELADO)

        # Dentro del plazo: no se toca.
        call_command("anonimizar_datos", dias=30, stdout=StringIO())
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.anonimizada_en)

        # Vencido: se borran los datos personales, se conservan valores y estado.
        hace_un_anio = timezone.now() - timedelta(days=365)
        S.objects.filter(pk=solicitud.pk).update(fecha_respuesta=hace_un_anio)
        Pedido.objects.filter(pk=pedido.pk).update(created_at=hace_un_anio)
        call_command("anonimizar_datos", dias=30, stdout=StringIO())

        solicitud.refresh_from_db()
        pedido.refresh_from_db()
        self.assertEqual(solicitud.nombre_completo, "Titular anonimizado")
        self.assertEqual((solicitud.documento, solicitud.telefono, solicitud.correo), ("", "", ""))
        self.assertEqual(solicitud.valor_solicitado, Decimal("100000"))
        self.assertEqual(solicitud.estado, S.ESTADO_RECHAZADA)
        self.assertIsNotNone(solicitud.anonimizada_en)
        self.assertEqual(pedido.direccion_entrega, "Anonimizada")
        self.assertEqual(pedido.total, Decimal("100000"))

    def test_rotacion_de_claves(self):
        from io import StringIO

        from cryptography.fernet import Fernet
        from django.core.management import call_command

        from apps.core.cifrado import clave_desarrollo, reiniciar_cache

        _, solicitud, _ = self.comprar_por_nomina(documento="777")
        nueva = Fernet.generate_key().decode()
        try:
            with override_settings(DATOS_CIFRADO_CLAVES=f"{nueva},{clave_desarrollo()}"):
                reiniciar_cache()
                call_command("recifrar_datos", stdout=StringIO())
            # Después de recifrar, basta la clave nueva para leer todo.
            with override_settings(DATOS_CIFRADO_CLAVES=nueva):
                reiniciar_cache()
                self.assertEqual(S.objects.get(pk=solicitud.pk).documento, "777")
        finally:
            reiniciar_cache()


class FincasTest(BaseNominaTest):
    """Con descuento por nómina se entrega en la finca que elige el comprador."""

    def setUp(self):
        super().setUp()
        self.finca = Finca.objects.create(
            fondo=self.fondo, nombre="La Esperanza", municipio="Madrid",
            indicaciones="Portería principal, recibe el jefe de bodega.",
        )
        otro = FondoEmpleado.objects.create(nombre="Otro fondo")
        self.finca_ajena = Finca.objects.create(fondo=otro, nombre="El Rosal")

    def pedido_nomina_sin_direccion(self):
        self.client.force_login(self.cliente)
        carrito, _ = Carrito.objects.get_or_create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(
            carrito=carrito, presentacion=self.producto_presentacion, cantidad=1, precio_unitario=Decimal("50000")
        )
        respuesta = self.client.post(reverse("pedidos:checkout"), {"metodo_pago": Pedido.METODO_NOMINA})
        pedido = Pedido.objects.get(usuario=self.cliente)
        self.assertRedirects(respuesta, reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]))
        return pedido

    def datos(self, **extra):
        datos = {
            "fondo": self.fondo.id, "nombre_completo": "Cliente de Prueba", "documento": "123",
            "empresa": "Flores SAS", "autoriza_tratamiento": "on",
        }
        datos.update(extra)
        return datos

    def test_checkout_nomina_no_pide_direccion_pero_otros_medios_si(self):
        self.pedido_nomina_sin_direccion()
        carrito, _ = Carrito.objects.get_or_create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(
            carrito=carrito, presentacion=self.producto_presentacion, cantidad=1, precio_unitario=Decimal("50000")
        )
        respuesta = self.client.post(reverse("pedidos:checkout"), {"metodo_pago": Pedido.METODO_OTRO})
        self.assertContains(respuesta, "Escribe la dirección de entrega")
        self.assertEqual(Pedido.objects.count(), 1)

    def test_finca_obligatoria_si_el_fondo_tiene_fincas(self):
        pedido = self.pedido_nomina_sin_direccion()
        url = reverse("fondos:solicitar_descuento_nomina", args=[pedido.id])
        self.assertContains(self.client.post(url, self.datos()), "Selecciona la finca donde trabajas")
        self.assertContains(self.client.post(url, self.datos(finca=self.finca_ajena.id)), "no pertenece al fondo")
        self.assertFalse(SolicitudDescuentoNomina.objects.exists())

    def test_la_finca_queda_como_punto_de_entrega(self):
        pedido = self.pedido_nomina_sin_direccion()
        self.client.post(
            reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]), self.datos(finca=self.finca.id)
        )
        solicitud = SolicitudDescuentoNomina.objects.get()
        pedido.refresh_from_db()
        self.assertEqual(solicitud.finca, self.finca)
        self.assertEqual((pedido.direccion_entrega, pedido.ciudad), ("Finca La Esperanza", "Madrid"))

        # El gestor ve la finca y sus indicaciones.
        self.client.force_login(self.gestor)
        respuesta = self.client.get(reverse("fondos:gestion_detalle", args=[solicitud.id]))
        self.assertContains(respuesta, "La Esperanza (Madrid)")
        self.assertContains(respuesta, "Portería principal")

    def test_fondo_sin_fincas_no_la_exige(self):
        self.finca.delete()
        pedido = self.pedido_nomina_sin_direccion()
        self.client.post(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]), self.datos())
        self.assertTrue(SolicitudDescuentoNomina.objects.exists())

    def test_formulario_filtra_fincas_por_fondo(self):
        pedido = self.pedido_nomina_sin_direccion()
        contenido = self.client.get(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id])).content.decode()
        self.assertIn(f'data-fondo="{self.fondo.id}"', contenido)
        self.assertIn("Finca donde trabajas", contenido)
