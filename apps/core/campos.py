from django.db import models

from .cifrado import cifrar, descifrar


class TextoCifrado(models.TextField):
    """
    Campo de texto que se guarda cifrado en la base de datos y se lee en claro
    en Python. No admite búsquedas (icontains, igualdad): para eso use una huella.
    """

    description = "Texto cifrado en reposo"

    def from_db_value(self, value, expression, connection):
        return descifrar(value)

    def to_python(self, value):
        return descifrar(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return cifrar(value)
