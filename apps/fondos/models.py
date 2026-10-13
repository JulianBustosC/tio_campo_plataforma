from django.conf import settings
from django.db import models


class FondoEmpleado(models.Model):
    """
    Entidad (fondo de empleados / empresa) que respalda el descuento por nómina.

    `modo_verificacion` define CÓMO se valida que el comprador es empleado/afiliado:
    - MANUAL: un gestor del fondo revisa cada solicitud en el portal.
    - PADRON: se consulta el padrón de afiliados cargado por el fondo (CSV).
    - API: se consulta en línea un servicio web expuesto por el fondo.

    Si `decision_automatica` está activo y la verificación es concluyente,
    la plataforma aprueba total/parcialmente o rechaza sin intervención humana.
    """

    MODO_MANUAL = "MANUAL"
    MODO_PADRON = "PADRON"
    MODO_API = "API"

    MODOS_VERIFICACION = [
        (MODO_MANUAL, "Revisión manual del gestor"),
        (MODO_PADRON, "Padrón de afiliados cargado"),
        (MODO_API, "Servicio web del fondo"),
    ]

    nombre = models.CharField(max_length=200, unique=True)
    nit = models.CharField(max_length=50, blank=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    responsable = models.CharField(max_length=200, blank=True)
    gestores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="fondos_gestionados",
        blank=True,
        help_text="Usuarios autorizados para revisar solicitudes de este fondo.",
    )
    modo_verificacion = models.CharField(
        max_length=10,
        choices=MODOS_VERIFICACION,
        default=MODO_MANUAL,
    )
    decision_automatica = models.BooleanField(
        default=False,
        help_text=(
            "Si la verificación es concluyente, aprobar/rechazar automáticamente. "
            "Si no lo es (o falla el servicio), la solicitud queda para revisión manual."
        ),
    )
    api_url = models.URLField(
        blank=True,
        help_text="Solo modo API: endpoint del fondo que responde la verificación.",
    )
    api_token_env = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Solo modo API: NOMBRE de la variable de entorno que contiene el token. "
            "El token nunca se guarda en la base de datos."
        ),
    )
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fondo de empleados"
        verbose_name_plural = "Fondos de empleados"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class AfiliadoFondo(models.Model):
    """Registro del padrón de afiliados/empleados que el fondo carga a la plataforma."""

    fondo = models.ForeignKey(
        FondoEmpleado,
        on_delete=models.CASCADE,
        related_name="afiliados",
    )
    documento = models.CharField(
        max_length=30,
        help_text="Normalizado: solo dígitos y letras, sin puntos ni guiones.",
    )
    nombre = models.CharField(max_length=200, blank=True)
    empresa = models.CharField(max_length=200, blank=True)
    cupo_disponible = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    activo = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Afiliado del fondo"
        verbose_name_plural = "Padrón de afiliados"
        ordering = ["fondo", "documento"]
        constraints = [
            models.UniqueConstraint(
                fields=["fondo", "documento"],
                name="afiliado_documento_unico_por_fondo",
            ),
            models.CheckConstraint(
                condition=models.Q(cupo_disponible__gte=0),
                name="afiliado_cupo_no_negativo",
            ),
        ]

    def __str__(self):
        return f"{self.documento} - {self.nombre} ({self.fondo})"


class SolicitudDescuentoNomina(models.Model):
    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_APROBADA = "APROBADA"
    ESTADO_APROBADA_PARCIAL = "APROBADA_PARCIAL"
    ESTADO_RECHAZADA = "RECHAZADA"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADA, "Aprobada"),
        (ESTADO_APROBADA_PARCIAL, "Aprobada parcialmente"),
        (ESTADO_RECHAZADA, "Rechazada"),
    ]

    ORIGEN_AUTOMATICO = "AUTOMATICO"
    ORIGEN_GESTOR = "GESTOR"

    ORIGENES = [
        (ORIGEN_AUTOMATICO, "Automática (verificación del fondo)"),
        (ORIGEN_GESTOR, "Gestor del fondo"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="solicitudes_nomina",
    )
    fondo = models.ForeignKey(
        FondoEmpleado,
        on_delete=models.PROTECT,
        related_name="solicitudes",
    )
    pedido = models.OneToOneField(
        "pedidos.Pedido",
        on_delete=models.PROTECT,
        related_name="solicitud_nomina",
        null=True,
        blank=True,
    )
    afiliado = models.ForeignKey(
        AfiliadoFondo,
        on_delete=models.SET_NULL,
        related_name="solicitudes",
        null=True,
        blank=True,
    )

    nombre_completo = models.CharField(max_length=200)
    documento = models.CharField(max_length=50)
    telefono = models.CharField(max_length=50, blank=True)
    correo = models.EmailField(blank=True)
    empresa = models.CharField(max_length=200, default="Tío Campo")
    numero_afiliado = models.CharField(max_length=100, blank=True)

    valor_solicitado = models.DecimalField(max_digits=12, decimal_places=2)
    vinculacion_validada = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="¿Trabaja/está afiliado con la entidad?",
    )
    valor_aprobado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    cupo_disponible_reportado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    cupo_reservado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Cupo descontado del padrón; se devuelve si el pedido se cancela.",
    )
    verificacion_mensaje = models.TextField(
        blank=True,
        help_text="Resultado de la verificación automática (padrón o API).",
    )
    origen_decision = models.CharField(max_length=15, choices=ORIGENES, blank=True)
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="solicitudes_decididas",
        null=True,
        blank=True,
    )
    respuesta_fondo = models.TextField(blank=True)
    observaciones_usuario = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_PENDIENTE)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_respuesta = models.DateTimeField(blank=True, null=True)
    referencia_fondo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Solicitud de descuento por nómina"
        verbose_name_plural = "Solicitudes de descuento por nómina"
        ordering = ["-fecha_solicitud"]
        indexes = [
            models.Index(fields=["fondo", "estado"]),
        ]

    def __str__(self):
        return f"Solicitud #{self.id} - {self.nombre_completo}"

    @property
    def esta_pendiente(self):
        return self.estado == self.ESTADO_PENDIENTE


class HistorialSolicitud(models.Model):
    """Bitácora de auditoría: cada verificación y decisión queda registrada."""

    EVENTO_CREADA = "CREADA"
    EVENTO_VERIFICACION = "VERIFICACION"
    EVENTO_DECISION = "DECISION"
    EVENTO_CUPO_LIBERADO = "CUPO_LIBERADO"

    EVENTOS = [
        (EVENTO_CREADA, "Solicitud creada"),
        (EVENTO_VERIFICACION, "Verificación de vinculación"),
        (EVENTO_DECISION, "Decisión"),
        (EVENTO_CUPO_LIBERADO, "Cupo liberado"),
    ]

    solicitud = models.ForeignKey(
        SolicitudDescuentoNomina,
        on_delete=models.CASCADE,
        related_name="historial",
    )
    evento = models.CharField(max_length=20, choices=EVENTOS)
    estado = models.CharField(max_length=20, blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    detalle = models.JSONField(default=dict, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Historial de solicitud"
        verbose_name_plural = "Historial de solicitudes"
        ordering = ["fecha", "id"]

    def __str__(self):
        return f"#{self.solicitud_id} {self.get_evento_display()} {self.fecha:%Y-%m-%d %H:%M}"
