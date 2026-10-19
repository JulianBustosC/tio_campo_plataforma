from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.carrito.models import CarritoItem
from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.productos.models import Producto, ProductoPresentacion
from apps.promociones.models import Combo


class TiendaTest(TestCase):
    """Portada, catálogo y carrito sin recargar (interfaz tipo supermercado)."""

    def setUp(self):
        unidad = UnidadMedida.objects.create(nombre="Mililitro", abreviatura="ml")
        self.categoria = Categoria.objects.create(nombre="Lácteos", icono="cup-straw")
        otra = Categoria.objects.create(nombre="Panadería", icono="cake2")
        marca = Marca.objects.create(nombre="Tío Campo")
        self.leche = Producto.objects.create(
            codigo="L1", nombre="Leche entera", categoria=self.categoria, marca=marca, destacado=True
        )
        self.litro = ProductoPresentacion.objects.create(
            producto=self.leche, codigo="L1-1000",
            presentacion=Presentacion.objects.create(nombre="1000 ml", cantidad=1000, unidad=unidad),
            precio=Decimal("4500"),
        )
        self.medio = ProductoPresentacion.objects.create(
            producto=self.leche, codigo="L1-500",
            presentacion=Presentacion.objects.create(nombre="500 ml", cantidad=500, unidad=unidad),
            precio=Decimal("2500"),
        )
        pan = Producto.objects.create(codigo="P1", nombre="Pan mogolla", categoria=otra, marca=marca)
        ProductoPresentacion.objects.create(
            producto=pan, codigo="P1-6", presentacion=self.medio.presentacion, precio=Decimal("5200")
        )
        # Producto sin presentaciones activas: no debe aparecer en la tienda.
        Producto.objects.create(codigo="X1", nombre="Producto oculto", categoria=otra, marca=marca)
        self.combo = Combo.objects.create(
            codigo="C1", nombre="Combo desayuno", precio=Decimal("30000"),
            precio_anterior=Decimal("40000"), stock=3,
        )

    def api(self, tipo, objeto_id, cantidad):
        return self.client.post(
            reverse("carrito:api_cantidad", args=[tipo, objeto_id]), {"cantidad": cantidad}
        )

    def test_portada(self):
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "Compra por categoría")
        self.assertContains(respuesta, "bi-cup-straw")
        self.assertContains(respuesta, "Leche entera")
        self.assertContains(respuesta, "-25%")              # combo 30.000 vs 40.000
        self.assertContains(respuesta, "$2.500")            # presentación más barata primero
        self.assertNotContains(respuesta, "Producto oculto")

    def test_catalogo_busqueda_y_orden(self):
        respuesta = self.client.get(reverse("productos:lista"), {"q": "mogolla"})
        self.assertContains(respuesta, "Pan mogolla")
        self.assertNotContains(respuesta, "Leche entera")

        respuesta = self.client.get(reverse("productos:lista"), {"orden": "precio_desc"})
        contenido = respuesta.content.decode()
        self.assertLess(contenido.index("Pan mogolla"), contenido.index("Leche entera"))

        respuesta = self.client.get(reverse("productos:categoria", args=[self.categoria.id]))
        self.assertContains(respuesta, "Leche entera")
        self.assertNotContains(respuesta, "Pan mogolla")

        respuesta = self.client.get(reverse("productos:lista"), {"q": "zzzz"})
        self.assertContains(respuesta, "No encontramos productos")

    def test_api_carrito_invitado(self):
        datos = self.api("p", self.medio.id, 2).json()
        self.assertEqual((datos["cantidad"], datos["cantidad_carrito"]), (2, 2))
        self.assertEqual(Decimal(datos["total"]), Decimal("5000"))

        datos = self.api("p", self.litro.id, 1).json()
        self.assertEqual(datos["cantidad_carrito"], 3)

        datos = self.api("p", self.medio.id, 0).json()      # 0 elimina
        self.assertEqual(datos["cantidad_carrito"], 1)
        self.assertEqual(CarritoItem.objects.count(), 1)

        # El encabezado de la siguiente página refleja el carrito.
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, '"p%d": 1' % self.litro.id)

    def test_api_combo_respeta_stock(self):
        datos = self.api("c", self.combo.id, 10).json()
        self.assertEqual(datos["cantidad"], 3)
        self.assertIn("Solo hay 3", datos["mensaje"])

    def test_api_valida_entrada(self):
        self.assertEqual(self.api("x", 1, 1).status_code, 400)
        self.assertEqual(self.api("p", self.medio.id, "abc").status_code, 400)
        self.assertEqual(self.api("p", 999999, 1).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("carrito:api_cantidad", args=["p", self.medio.id])).status_code, 405
        )

    def test_carrito_de_invitado_se_conserva_al_ingresar(self):
        self.api("p", self.medio.id, 2)
        usuario = get_user_model().objects.create_user(username="ana", password="x")
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("carrito:mini"))
        self.assertContains(respuesta, "Leche entera")

    def test_mini_carrito_vacio(self):
        self.assertContains(self.client.get(reverse("carrito:mini")), "Tu carrito está vacío")

    def test_paginas_existentes_siguen_funcionando(self):
        for nombre, args in [
            ("carrito:detalle", []),
            ("combos:lista_combos", []),
            ("combos:detalle_combo", [self.combo.id]),
            ("productos:detalle", [self.leche.id]),
            ("login", []),
            ("registro", []),
        ]:
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 200, nombre)

    def test_tarjeta_precio_visible_separado_de_opciones(self):
        # El JS actualiza [data-precio-visible]; las opciones usan data-precio. No deben confundirse.
        contenido = self.client.get(reverse("productos:lista")).content.decode()
        self.assertEqual(contenido.count('data-precio-visible'), 2)          # una por producto
        self.assertNotIn('class="tc-precio" data-precio>', contenido)

    def test_detalle_combo_tiene_boton_agregar(self):
        respuesta = self.client.get(reverse("combos:detalle_combo", args=[self.combo.id]))
        self.assertContains(respuesta, f'data-tipo="c" data-id="{self.combo.id}"')
        self.assertContains(respuesta, 'data-accion="agregar"')
        self.assertContains(respuesta, "-25%")
