#!/usr/bin/env python3
"""
Nodo transmisor del sistema de transmisión inalámbrica de audio.

Sigue la siguiente máquina de estados:
  IDLE -> RECORDING -> PREPARING -> SENDING_START -> SENDING_DATA
       -> SENDING_END -> SUCCESS -> IDLE
"""

import atexit
import signal
import sys
import threading
import time
import numpy as np
import sounddevice as sd
from gpiozero import Button

# Módulos creados
import common
import config
import leds
import radio as radio_mod

# Estados
IDLE, RECORDING, PREPARING, SENDING_START, SENDING_DATA, SENDING_END, \
    SUCCESS, ERROR = range(8)


class Transmitter:
    def __init__(self):
        """Inicializa la radio (modo TX), los LEDs, el botón y el estado interno."""
        self.radio = radio_mod.open_radio()
        radio_mod.open_tx(self.radio)
        self.signals = leds.Signals()
        self.button = Button(config.PIN_BUTTON, pull_up=True, bounce_time=0.05)

        self.state = IDLE
        # Eventos de control de la grabación (toggle).
        self._recording = threading.Event()      # Activo mientras se graba
        self._press = threading.Event()          # Señala un toque pendiente
        self.button.when_pressed = self._on_press

        self._frames = []                        # Bloques capturados
        self._pcm = b""                          # Audio en 8 bits
        self._chunks = []

        atexit.register(self.cleanup)

    # Botón
    def _on_press(self):
        """Callback del botón. Marca que hay un toque pendiente por atender."""
        self._press.set()

    def _consume_press(self):
        """Devuelve True si había un toque pendiente y lo consume."""
        if self._press.is_set():
            self._press.clear()
            return True
        return False

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback de sounddevice. Acumula los bloques capturados mientras la
        grabación está activa."""
        if self._recording.is_set():
            self._frames.append(indata.copy())

    def record(self):
        """Graba mientras el usuario no presione el botón por segunda vez."""
        self._frames = []
        self._recording.set()
        with sd.InputStream(samplerate=config.SAMPLE_RATE,
                            channels=config.CHANNELS,
                            dtype="int32",
                            callback=self._audio_callback):
            # Esperar el segundo toque (detener).
            while not self._consume_press():
                time.sleep(0.02)
        self._recording.clear()

    def _send(self, payload):
        """Envía un payload por la radio reintentando hasta APP_RETRIES veces.
        Devuelve True si se recibió ACK, False si se agotaron los reintentos."""
        for _ in range(config.APP_RETRIES):
            if self.radio.write(bytes(payload)):
                return True
        return False

    def run(self):
        """Bucle principal"""
        self.signals.ready()
        print("TX listo. Esperando botón...")

        handlers = {
            IDLE: self._state_idle,
            RECORDING: self._state_recording,
            PREPARING: self._state_preparing,
            SENDING_START: self._state_sending_start,
            SENDING_DATA: self._state_sending_data,
            SENDING_END: self._state_sending_end,
            SUCCESS: self._state_success,
            ERROR: self._state_error,
        }

        while True:
            handlers[self.state]()

    def _state_idle(self):
        """Espera hasta que el usuario presione el botón para iniciar una nueva
        grabación."""
        if self._consume_press():
            self.state = RECORDING
        else:
            time.sleep(0.01)

    def _state_recording(self):
        """Graba audio del micrófono hasta que el usuario vuelve a presionar el
        botón."""
        print("Grabando... Presione de nuevo para detener")
        self.signals.recording()
        self.record()
        self.state = PREPARING

    def _state_preparing(self):
        """Convierte las muestras capturadas a PCM de 8 bits y las fragmenta en
        bloques del tamaño del payload."""
        samples = (np.concatenate(self._frames)
                   if self._frames else np.zeros((0, config.CHANNELS),
                                                  dtype=np.int32))
        # Solo el canal izquierdo del frame I2S (mono).
        if samples.ndim > 1:
            samples = samples[:, 0]
        self._pcm = common.encode_audio(samples, config.MIC_GAIN, config.CODEC)
        self._chunks = common.chunk_bytes(self._pcm)
        print(f"Capturado: {len(self._pcm)} bytes -> "
              f"{len(self._chunks)} paquetes")
        self.state = SENDING_START

    def _state_sending_start(self):
        """Envía el paquete START con el total de bloques y los parámetros del
        audio. Si falla, pasa a ERROR."""
        self.signals.transmitting()
        start = common.pack_start(len(self._chunks))
        self.state = SENDING_DATA if self._send(start) else ERROR

    def _state_sending_data(self):
        """Envía todos los bloques DATA en orden. Si alguno falla tras los
        reintentos, pasa a ERROR."""
        ok = True
        for seq, chunk in enumerate(self._chunks):
            if not self._send(common.pack_data(seq, chunk)):
                ok = False
                break
        self.state = SENDING_END if ok else ERROR

    def _state_sending_end(self):
        """Envía el paquete END. Si falla, pasa a ERROR."""
        end = common.pack_end()
        self.state = SUCCESS if self._send(end) else ERROR

    def _state_success(self):
        """Transmisión completa. Señaliza éxito y vuelve a IDLE."""
        print("Transmisión exitosa.")
        self.signals.success()
        time.sleep(config.STATE_TIMEOUT)
        self._back_to_idle()

    def _state_error(self):
        """Falla en algún envío. Indica error y vuelve a IDLE."""
        print("Error en la transmisión.")
        self.signals.error()
        time.sleep(config.STATE_TIMEOUT)
        self._back_to_idle()

    def _back_to_idle(self):
        """Descarta toques pendientes, deja el LED de listo y vuelve a IDLE."""
        self._press.clear()
        self.signals.ready()
        self.state = IDLE

    # Limpieza
    def cleanup(self, *_):
        """Apaga los LEDs/GPIO y la radio."""
        try:
            self.signals.close()
        except Exception:
            pass
        try:
            self.radio.powerDown()
        except Exception:
            pass


def main():
    """Punto de entrada"""
    tx = Transmitter()
    signal.signal(signal.SIGTERM, lambda *_: (tx.cleanup(), sys.exit(0)))
    try:
        tx.run()
    except KeyboardInterrupt:
        pass
    finally:
        tx.cleanup()


if __name__ == "__main__":
    main()
