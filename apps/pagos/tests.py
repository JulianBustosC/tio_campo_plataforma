import hashlib
import json
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.pedidos.models import Pedido

from .models import TransaccionPago
from .pasarelas.wompi import firma_integridad

LLAVES = dict(
    PASARELA_PAGOS="wompi",
    WOMPI_PUBLIC_KEY="pub_test_abc",
    WOMPI_INTEGRITY_SECRET="test_integrity_secreto",
    WOMPI_EVENTS_SECRET="test_events_secreto",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


def evento_wompi(referencia, monto_centavos, estado="APPROVED", secreto="test_events_secreto", id_tx="1234-1610641025-49201"):
    """Construye un evento como los que envía Wompi, firmado con el secreto dado."""
    transaccion = {
        "id": id_tx,
        "amount_in_cents": monto_centavos,
        "reference": referencia,
        "currency": "COP",
        "payment_method_type": "CARD",
        "status": estado,
    }
    timestamp = 1530291411
    propiedades = ["transaction.id", "transaction.status", "transaction.amount_in_cents"]
    cadena = f"{id_tx}{estado}{monto_centavos}{timestamp}{secreto}"
    return {
        "event": "transaction.updated",
        "data": {"transaction": transaccion},
        "environment": "test",
        "signature": {
            "properties": propiedades,
            "checksum": hashlib.sha256(cadena.encode()).hexdigest().upper(),
        },
        "timestamp": timestamp,
        "sent_at": "2018-07-20T16:45:05.000Z",
    }


@override_settings(**LLAVES)
class PagosTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user(username="ana", password="x", email="ana@example.com")
        self.otro = User.objects.create_user(username="otro", password="x")
        self.pedido = Pedido.objects.create(
            usuario=self.usuario,
            metodo_pago=Pedido.METODO_ELECTRONICO,
            estado=Pedido.ESTADO_PENDIENTE_PAGO,
            subtotal=Decimal("85000"),
            total=Decimal("85000"),
            direccion_entrega="Calle 1",
            ciudad="Bogotá",
        )
        self.client.force_login(self.usuario)

    def iniciar(self):
        respuesta = self.client.post(reverse("pagos:pagar", args=[self.pedido.id]))
        return respuesta, TransaccionPago.objects.filter(pedido=self.pedido).latest("id")

    def webhook(self, datos):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("pagos:webhook", args=["wompi"]),
                data=json.dumps(datos),
                content_type="application/json",
            )

    def test_firma_integridad(self):
        # Ejemplo: referencia + monto en centavos + moneda + secreto de integridad
        esperado = hashlib.sha256(b"sk8-438k4-xmxm392-sn2m22490000000COPtest_integrity_abc").hexdigest()
        self.assertEqual(firma_integridad("sk8-438k4-xmxm392-sn2m2", 2490000000, "COP", "test_integrity_abc"), esperado)

    def test_iniciar_pago_redirige_a_wompi_con_firma(self):
        respuesta, tx = self.iniciar()
        self.assertEqual(tx.monto_centavos, 8500000)
        self.assertEqual(tx.referencia, f"{self.pedido.numero}-1")
        url = urlparse(respuesta["Location"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "https://checkout.wompi.co/p/")
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(params["public-key"], "pub_test_abc")
        self.assertEqual(params["amount-in-cents"], "8500000")
        self.assertEqual(
            params["signature:integrity"],
            firma_integridad(tx.referencia, 8500000, "COP", "test_integrity_secreto"),
        )

    def test_webhook_aprobado_marca_pedido_pagado_una_sola_vez(self):
        _, tx = self.iniciar()
        datos = evento_wompi(tx.referencia, tx.monto_centavos)
        self.assertEqual(self.webhook(datos).status_code, 200)
        self.assertEqual(self.webhook(datos).status_code, 200)  # reintento de Wompi

        tx.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(tx.estado, TransaccionPago.ESTADO_APROBADA)
        self.assertEqual(tx.metodo, "CARD")
        self.assertEqual(self.pedido.estado, Pedido.ESTADO_PAGADO)
        self.assertEqual(len(mail.outbox), 1)

    def test_webhook_con_firma_invalida_se_rechaza(self):
        _, tx = self.iniciar()
        datos = evento_wompi(tx.referencia, tx.monto_centavos, secreto="secreto_falso")
        self.assertEqual(self.webhook(datos).status_code, 400)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.ESTADO_PENDIENTE_PAGO)

    def test_webhook_con_monto_distinto_no_aprueba(self):
        _, tx = self.iniciar()
        self.webhook(evento_wompi(tx.referencia, 100))
        tx.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(tx.estado, TransaccionPago.ESTADO_ERROR)
        self.assertEqual(self.pedido.estado, Pedido.ESTADO_PENDIENTE_PAGO)

    def test_rechazo_permite_reintentar(self):
        _, tx = self.iniciar()
        self.webhook(evento_wompi(tx.referencia, tx.monto_centavos, estado="DECLINED"))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.ESTADO_PENDIENTE_PAGO)
        _, segundo = self.iniciar()
        self.assertEqual(segundo.referencia, f"{self.pedido.numero}-2")

    def test_pago_del_saldo_tras_nomina_parcial(self):
        self.pedido.metodo_pago = Pedido.METODO_NOMINA
        self.pedido.metodo_pago_saldo = Pedido.METODO_ELECTRONICO
        self.pedido.valor_nomina = Decimal("60000")
        self.pedido.save()
        _, tx = self.iniciar()
        self.assertEqual(tx.monto_centavos, 2500000)

    def test_no_se_puede_pagar_pedido_ajeno(self):
        self.client.force_login(self.otro)
        respuesta = self.client.post(reverse("pagos:pagar", args=[self.pedido.id]))
        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(TransaccionPago.objects.exists())

    def test_pedido_pagado_no_genera_nuevo_cobro(self):
        self.pedido.estado = Pedido.ESTADO_PAGADO
        self.pedido.save()
        self.client.post(reverse("pagos:pagar", args=[self.pedido.id]))
        self.assertFalse(TransaccionPago.objects.exists())

    @mock.patch("apps.pagos.pasarelas.wompi.urllib.request.urlopen")
    def test_retorno_consulta_a_wompi(self, urlopen):
        _, tx = self.iniciar()
        respuesta_api = mock.MagicMock()
        respuesta_api.read.return_value = json.dumps({
            "data": evento_wompi(tx.referencia, tx.monto_centavos)["data"]["transaction"]
        }).encode()
        respuesta_api.__enter__.return_value = respuesta_api
        urlopen.return_value = respuesta_api

        respuesta = self.client.get(reverse("pagos:retorno") + "?id=1234-1610641025-49201&env=test")
        self.assertContains(respuesta, "Pago aprobado")
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.ESTADO_PAGADO)

    def test_boton_pagar_en_pedido(self):
        respuesta = self.client.get(reverse("pedidos:confirmacion", args=[self.pedido.id]))
        self.assertContains(respuesta, "en línea")