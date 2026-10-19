from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class FirmaInvalida(Exception):
    """El evento recibido no fue firmado por la pasarela."""


@dataclass(frozen=True)
class EventoPago:
    """Resultado de un pago, ya traducido a los estados de TransaccionPago."""

    referencia: str
    id_externo: str
    estado: str
    monto_centavos: int
    metodo: str = ""
    datos: dict = field(default_factory=dict)


class Pasarela(ABC):
    codigo = ""

    @abstractmethod
    def url_checkout(self, transaccion, url_retorno, correo=""):
        """URL a la que se redirige al comprador para pagar."""

    @abstractmethod
    def leer_evento(self, cuerpo):
        """
        Valida la firma del webhook y devuelve un EventoPago.
        Devuelve None si el evento no es de interés. Lanza FirmaInvalida si la firma no cuadra.
        """

    @abstractmethod
    def consultar(self, id_externo):
        """Consulta servidor-a-servidor el estado de una transacción. None si falla."""