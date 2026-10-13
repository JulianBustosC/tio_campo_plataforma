from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("confirmacion/<int:pedido_id>/", views.confirmacion, name="confirmacion"),
    path("<int:pedido_id>/pagar-saldo/", views.pagar_saldo, name="pagar_saldo"),
    path("<int:pedido_id>/cancelar/", views.cancelar, name="cancelar"),
    path("mis-pedidos/", views.mis_pedidos, name="mis_pedidos"),
]
