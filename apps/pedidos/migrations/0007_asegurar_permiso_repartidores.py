from django.db import migrations


def asegurar_permiso(apps, schema_editor):
    """El grupo "Repartidores" debe tener el permiso de registrar entregas (idempotente)."""
    from django.contrib.auth.management import create_permissions

    for config in apps.get_app_configs():
        config.models_module = True
        create_permissions(config, apps=apps, verbosity=0)
        config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    grupo, _ = Group.objects.get_or_create(name="Repartidores")
    permiso = Permission.objects.get(codename="registrar_entrega", content_type__app_label="pedidos")
    grupo.permissions.add(permiso)


class Migration(migrations.Migration):

    dependencies = [
        ("pedidos", "0006_entregas"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(asegurar_permiso, migrations.RunPython.noop),
    ]
