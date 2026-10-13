from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.carrito.models import Carrito, CarritoItem
from apps.promociones.models import Combo
from .models import Pedido


class StockCombosTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="comprador", password="x")
        self.combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("20000"), stock=3)
        self.client.force_login(self.usuario)

    def comprar(self, cantidad, metodo=Pedido.METODO_OTRO):
        carrito, _ = Carrito.objects.get_or_create(usuario=self.usuario, activo=True)
        CarritoItem.objects.create(
            carrito=carrito, combo=self.combo, cantidad=cantidad, precio_unitario=self.combo.precio
        )
        return self.client.post(
            reverse("pedidos:checkout"),
            {"direccion_entrega": "Calle 1", "ciudad": "Bogotá", "metodo_pago": metodo},
        )

    def test_checkout_descuenta_stock_y_cancelar_lo_devuelve(self):
        self.comprar(2)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)

        pedido = Pedido.objects.get(usuario=self.usuario)
        self.assertEqual(pedido.items.get().producto_nombre, "Combo")
        self.client.post(reverse("pedidos:cancelar", args=[pedido.id]))
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 3)

    def test_no_permite_sobreventa(self):
        self.comprar(2)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)
        self.comprar(2)
        self.assertEqual(Pedido.objects.count(), 1)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)

    def test_metodo_invalido(self):
        self.comprar(1, metodo="BITCOIN")
        self.assertFalse(Pedido.objects.exists())


class RegistroTest(TestCase):
    def test_registro_inicia_sesion(self):
        respuesta = self.client.post(
            reverse("registro"),
            {
                "username": "nuevo",
                "first_name": "Ana",
                "last_name": "Pérez",
                "email": "ana@example.com",
                "password1": "UnaClaveSegura#2026",
                "password2": "UnaClaveSegura#2026",
            },
        )
        self.assertRedirects(respuesta, reverse("dashboard"))
        self.assertTrue(get_user_model().objects.filter(username="nuevo").exists())
