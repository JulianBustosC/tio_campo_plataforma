from django.db import models


class TransaccionPago(models.Model):
    """
    Cada intento de pago en línea de un pedido. Un pedido puede tener varios
    intentos (si uno es rechazado, el cliente reintenta con una referencia nueva).
    """

    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_APROBADA = "APROBADA"
    ESTADO_RECHAZADA = "RECHAZADA"
    ESTADO_ANULADA = "ANULADA"
    ESTADO_ERROR = "ERROR"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADA, "Aprobada"),
        (ESTADO_RECHAZADA, "Rechazada"),
        (ESTADO_ANULADA, "Anulada"),
        (ESTADO_ERROR, "Error"),
    ]

    ESTADOS_FINALES = (ESTADO_APROBADA, ESTADO_RECHAZADA, ESTADO_ANULADA, ESTADO_ERROR)

    pedido = models.ForeignKey(
        "pedidos.Pedido",
        on_delete=models.PROTECT,
        related_name="transacciones",
    )
    referencia = models.CharField(max_length=64, unique=True)
    proveedor = models.CharField(max_length=20)
    monto_centavos = models.PositiveBigIntegerField()
    moneda = models.CharField(max_length=3, default="COP")
    estado = models.CharField(max_length=12, choices=ESTADOS, default=ESTADO_PENDIENTE)
    id_externo = models.CharField(max_length=64, blank=True, db_index=True)
    metodo = models.CharField(max_length=30, blank=True)
    respuesta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transacción de pago"
        verbose_name_plural = "Transacciones de pago"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referencia} ({self.get_estado_display()})"

    @property
    def monto(self):
        return self.monto_centavos / 100