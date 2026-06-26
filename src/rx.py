#!/usr/bin/env python3
"""
Nodo receptor del sistema de transmisión inalámbrica de audio.

Permanece en escucha continua. Al recibir un paquete START prepara el buffer,
almacena los paquetes DATA por número de bloque y al recibir END verifica la
integridad, reconstruye el WAV y lo reproduce.

Sigue la siguiente máquina de estados:
  IDLE(listen) -> RECEIVING -> VERIFYING -> PLAYING -> SUCCESS -> IDLE
"""

import atexit
import os
import signal
import sys
import time
import sounddevice as sd

# Módulos creados
import common
import config
import leds
import radio as radio_mod

# Estados
IDLE, RECEIVING, VERIFYING, PLAYING, SUCCESS, ERROR = range(6)


class Receiver:
    def __init__(self):
        """Inicializa la radio (modo RX en escucha), los LEDs y el estado interno."""
        self.radio = radio_mod.open_radio()
        radio_mod.open_rx(self.radio)
        self.signals = leds.Signals()

        self.state = IDLE   # Estado
        self.params = None  # parámetros del START
        self.blocks = {}    # Bytes de audio
        self.last_rx = 0.0  # Marca de tiempo del último paquete

        os.makedirs(config.AUDIO_TMP_DIR, exist_ok=True)
        atexit.register(self.cleanup)

    def _read_payload(self):
        """Lee un payload disponible de la FIFO de recepción o None."""
        if not self.radio.available():
            return None
        size = self.radio.getDynamicPayloadSize() if config.DYNAMIC_PAYLOADS \
            else config.PAYLOAD_SIZE
        return self.radio.read(size)

    def run(self):
        """Bucle principal"""
        self.signals.ready()
        print("RX listo. Escuchando...")

        handlers = {
            IDLE: self._state_idle,
            RECEIVING: self._state_receiving,
            VERIFYING: self._state_verifying,
            PLAYING: self._state_playing,
            SUCCESS: self._state_success,
            ERROR: self._state_error,
        }

        while True:
            handlers[self.state]()

    def _state_idle(self):
        """Escucha continua. Descarta los paquetes hasta recibir un START, que 
        marca el inicio de una transmisión junto con los parámetros del audio."""
        payload = self._read_payload()
        if payload is None:
            time.sleep(0.001)
            return
        msg_type, _, raw = common.parse_packet(payload)
        if msg_type == common.T_START:
            self.params = common.parse_start(raw)
            self.blocks = {}
            self.last_rx = time.time()
            print(f"START: {self.params['total_blocks']} bloques esperados")
            self.signals.receiving()
            self.state = RECEIVING

    def _state_receiving(self):
        """Almacena cada bloque DATA por su número de secuencia. Sale al recibir
        END o si pasa mucho tiempo sin paquetes (timeout)."""
        payload = self._read_payload()
        if payload is None:
            if time.time() - self.last_rx > config.RX_PACKET_TIMEOUT:
                print("Timeout de recepción.")
                self.state = ERROR
            else:
                time.sleep(0.001)
            return
        self.last_rx = time.time()
        msg_type, seq, data = common.parse_packet(payload)
        if msg_type == common.T_DATA:
            self.blocks[seq] = data
        elif msg_type == common.T_END:
            self.state = VERIFYING

    def _state_verifying(self):
        """Comprueba que estén todos los bloques (0..total-1) antes de
        reconstruir el audio."""
        total = self.params["total_blocks"]
        missing = [i for i in range(total) if i not in self.blocks]
        if missing:
            print(f"Archivo incompleto: faltan {len(missing)} de {total}.")
            self.state = ERROR
        else:
            print("Archivo completo.")
            self.state = PLAYING

    def _state_playing(self):
        """Reensambla los bytes recibidos, los decodifica según el códec del
        START, reconstruye el WAV y lo reproduce por el DAC."""
        self.signals.playing()
        total = self.params["total_blocks"]
        encoded = b"".join(self.blocks[i] for i in range(total))
        # Decodificar a int16 según el códec (pcm o adpcm).
        samples = common.decode_audio(encoded, self.params["codec"])
        path = os.path.join(config.AUDIO_TMP_DIR, "recibido.wav")
        common.build_wav(path, samples.tobytes(), fs=self.params["fs"],
                         bits=16, channels=self.params["channels"])
        print(f"Reproduciendo {path} ({len(encoded)} bytes, "
              f"codec={self.params['codec']})...")
        self._play(samples)
        self.state = SUCCESS

    def _state_success(self):
        """Recepción y reproducción correctas, indica éxito y vuelve a escuchar."""
        self.signals.success()
        time.sleep(config.STATE_TIMEOUT)
        self._reset()

    def _state_error(self):
        """Fallo (archivo incompleto o timeout), señaliza error y vuelve a escuchar."""
        self.signals.error()
        time.sleep(config.STATE_TIMEOUT)
        self._reset()

    def _play(self, samples):
        """Reproduce muestras int16 ya decodificadas por el DAC PCM5102 (I2S)."""
        sd.play(samples, samplerate=self.params["fs"], blocking=True)

    def _reset(self):
        """Reinicio de atributos y FIFO de transceiver"""
        self.blocks = {}
        self.params = None
        self.signals.ready()
        self.radio.flush_rx() # Vaciar la FIFO antes de volver a escuchar
        self.state = IDLE
        print("RX listo. Escuchando...")

    def cleanup(self, *_):
        """Limpieza"""
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
    rx = Receiver()
    signal.signal(signal.SIGTERM, lambda *_: (rx.cleanup(), sys.exit(0)))
    try:
        rx.run()
    except KeyboardInterrupt:
        pass
    finally:
        rx.cleanup()


if __name__ == "__main__":
    main()
