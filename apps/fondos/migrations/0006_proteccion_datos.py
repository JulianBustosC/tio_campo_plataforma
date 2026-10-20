"""
Ley 1581 de 2012: cifra documento y teléfono que ya existen en la base de datos,
agrega huellas de búsqueda y los campos de autorización y anonimización.
"""

import apps.core.campos
from django.db import migrations, models


def cifrar_existentes(apps, schema_editor):
    from apps.core.cifrado import cifrar, huella, normalizar_documento

    Afiliado = apps.get_model("fondos", "AfiliadoFondo")
    for afiliado in Afiliado.objects.all():
        documento = normalizar_documento(afiliado.documento)
        Afiliado.objects.filter(pk=afiliado.pk).update(
            documento=cifrar(documento), documento_huella=huella(documento)
        )

    Solicitud = apps.get_model("fondos", "SolicitudDescuentoNomina")
    for solicitud in Solicitud.objects.all():
        Solicitud.objects.filter(pk=solicitud.pk).update(
            documento=cifrar(solicitud.documento),
            telefono=cifrar(solicitud.telefono),
            documento_huella=huella(solicitud.documento),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("fondos", "0005_verificacion_padron_auditoria"),
    ]

    
    operations = [
        # 1. Agregar las huellas antes de utilizarlas.
        migrations.AddField(
            model_name="afiliadofondo",
            name="documento_huella",
            field=models.CharField(
                max_length=64,
                default="",
                db_index=True,
                editable=False,
                help_text="Huella HMAC del documento para buscarlo sin guardarlo en claro.",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="SolicitudDescuentoNomina",
            name="documento_huella",
            field=models.CharField(
                max_length=64,
                blank=True,
                db_index=True,
                editable=False,
            ),
        ),

        # 2. Cambiar los campos personales a TextoCifrado.
        migrations.AlterField(
            model_name="afiliadofondo",
            name="documento",
            field=apps.core.campos.TextoCifrado(
                help_text="Cifrado en la base de datos. Normalizado: solo dígitos y letras."
            ),
        ),
        migrations.AlterField(
            model_name="SolicitudDescuentoNomina",
            name="documento",
            field=apps.core.campos.TextoCifrado(),
        ),
        migrations.AlterField(
            model_name="SolicitudDescuentoNomina",
            name="telefono",
            field=apps.core.campos.TextoCifrado(blank=True),
        ),

        # 3. Agregar los campos de autorización y anonimización.
        migrations.AddField(
            model_name="SolicitudDescuentoNomina",
            name="autorizacion_datos",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="SolicitudDescuentoNomina",
            name="autorizacion_fecha",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="SolicitudDescuentoNomina",
            name="autorizacion_version",
            field=models.CharField(
                blank=True,
                max_length=20,
                help_text="Versión de la política de tratamiento de datos que aceptó el titular.",
            ),
        ),
        migrations.AddField(
            model_name="SolicitudDescuentoNomina",
            name="anonimizada_en",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Fecha en que se borraron los datos personales por la política de retención.",
            ),
        ),
    ]

