import apps.core.campos
from django.db import migrations, models


def cifrar_telefonos(apps, schema_editor):
    from apps.core.cifrado import cifrar

    Pedido = apps.get_model("pedidos", "Pedido")
    for pedido in Pedido.objects.exclude(telefono_contacto=""):
        Pedido.objects.filter(pk=pedido.pk).update(telefono_contacto=cifrar(pedido.telefono_contacto))


class Migration(migrations.Migration):

    dependencies = [
        ("pedidos", "0004_compra_invitado"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pedido",
            name="telefono_contacto",
            field=apps.core.campos.TextoCifrado(blank=True),
        ),
        migrations.RunPython(cifrar_telefonos, migrations.RunPython.noop),
        migrations.AddField(
            model_name="pedido",
            name="anonimizado_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
