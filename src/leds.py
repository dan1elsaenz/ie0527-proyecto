"""
Señalización mediante los tres LEDs (verde, amarillo, rojo).

Implementa el código de estados definido
"""

from gpiozero import LED

import config


class Signals:
    """Controla los tres LEDs."""

    def __init__(self):
        self.green = LED(config.PIN_LED_GREEN)
        self.yellow = LED(config.PIN_LED_YELLOW)
        self.red = LED(config.PIN_LED_RED)

    def _all_off(self):
        """Método privado para apagar todos los LEDs."""
        self.green.off()
        self.yellow.off()
        self.red.off()

    # Estados compartidos
    def ready(self):
        """Listo / espera: verde fijo."""
        self._all_off()
        self.green.on()

    def recording(self):
        """Grabando: amarillo parpadeo lento."""
        self._all_off()
        self.yellow.blink(on_time=0.5, off_time=0.5, background=True)

    def transmitting(self):
        """Transmitiendo / recibiendo: amarillo parpadeo rápido."""
        self._all_off()
        self.yellow.blink(on_time=0.1, off_time=0.1, background=True)

    receiving = transmitting # Mismo comportamiento

    def retrying(self):
        """Reintentando paquete: amarillo fijo y rojo parpadeo."""
        self._all_off()
        self.yellow.on()
        self.red.blink(on_time=0.1, off_time=0.1, background=True)

    def playing(self):
        """Reproduciendo: verde y amarillo fijos."""
        self._all_off()
        self.green.on()
        self.yellow.on()

    def success(self):
        """Transmisión exitosa: verde parpadeo rápido."""
        self._all_off()
        self.green.blink(on_time=0.1, off_time=0.1, background=True)

    def error(self):
        """Error: rojo fijo."""
        self._all_off()
        self.red.on()

    def close(self):
        """Apaga todo y libera los pines."""
        self._all_off()
        self.green.close()
        self.yellow.close()
        self.red.close()
