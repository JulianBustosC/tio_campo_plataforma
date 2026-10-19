from django.urls import path

from . import views

app_name = "pagos"

urlpatterns = [
    path("pedido/<int:pedido_id>/pagar/", views.pagar, name="pagar"),
    path("retorno/", views.retorno, name="retorno"),
    path("webhook/<slug:proveedor>/", views.webhook, name="webhook"),
]