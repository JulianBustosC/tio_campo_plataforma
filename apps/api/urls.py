from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

app_name = "api"

urlpatterns = [
    # Autenticación
    path("auth/token/", obtain_auth_token, name="token"),

    # Catálogo (público)
    path("catalogo/categorias/", views.CategoriaLista.as_view(), name="categorias"),
    path("catalogo/productos/", views.ProductoLista.as_view(), name="productos"),
    path("catalogo/productos/<int:pk>/", views.ProductoDetalle.as_view(), name="producto"),
    path("catalogo/combos/", views.ComboLista.as_view(), name="combos"),

    # Carrito (público: usuario autenticado o sesión de invitado)
    path("carrito/", views.carrito, name="carrito"),
    path("carrito/items/", views.carrito_items, name="carrito_items"),

    # Pedidos
    path("pedidos/", views.pedidos, name="pedidos"),
    path("pedidos/<int:pedido_id>/", views.pedido_detalle, name="pedido"),
    path("pedidos/seguimiento/<uuid:codigo>/", views.pedido_seguimiento, name="pedido_seguimiento"),
    path("pedidos/<int:pedido_id>/cancelar/", views.pedido_cancelar, name="pedido_cancelar"),
    path("pedidos/<int:pedido_id>/pagar-saldo/", views.pedido_pagar_saldo, name="pedido_pagar_saldo"),
    path("pedidos/<int:pedido_id>/pago-en-linea/", views.pedido_pago_en_linea, name="pedido_pago_en_linea"),

    # Descuento por nómina (comprador autenticado)
    path("nomina/fondos/", views.FondoLista.as_view(), name="fondos"),
    path("nomina/solicitudes/", views.solicitudes_nomina, name="solicitudes"),

    # Portal del fondo (gestores)
    path("fondo/solicitudes/", views.GestorSolicitudLista.as_view(), name="gestor_solicitudes"),
    path("fondo/solicitudes/<int:pk>/", views.GestorSolicitudDetalle.as_view(), name="gestor_solicitud"),
    path("fondo/solicitudes/<int:solicitud_id>/decision/", views.gestor_decision, name="gestor_decision"),
    path("fondo/fondos/<int:fondo_id>/padron/", views.gestor_padron, name="gestor_padron"),
    path("fondo/fondos/<int:fondo_id>/reporte/", views.gestor_reporte, name="gestor_reporte"),
    path("fondo/fondos/<int:fondo_id>/reporte/cerrar/", views.gestor_cerrar_corte, name="gestor_cerrar_corte"),
]
