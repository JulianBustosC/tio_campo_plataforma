import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def generar_codigos(apps, schema_editor):
    """Cada pedido existente recibe su propio código de acceso único."""
    Pedido = apps.get_model("pedidos", "Pedido")
    for pedido in Pedido.objects.filter(codigo_acceso__isnull=True).only("id"):
        pedido.codigo_acceso = uuid.uuid4()
        pedido.save(update_fields=["codigo_acceso"])


class Migration(migrations.Migration):

    dependencies = [
        ("pedidos", "0003_saldo_y_valor_nomina"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="pedido",
            name="usuario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pedidos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="pedido",
            name="nombre_contacto",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="pedido",
            name="correo_contacto",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="pedido",
            name="telefono_contacto",
            field=models.CharField(blank=True, max_length=30),
        ),
        # Paso 1: columna sin restricción, paso 2: llenar, paso 3: volverla única.
        migrations.AddField(
            model_name="pedido",
            name="codigo_acceso",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(generar_codigos, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pedido",
            name="codigo_acceso",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
