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

        # Indicadores de la transmisión (se reinician en cada START).
        self.t_start = 0.0  # tiempo del START recibido
        self.t_end = 0.0    # tiempo del END recibido
        self.bytes_rx = 0   # bytes de audio recibidos (carga DATA)
        self.rpd_hits = 0   # paquetes con señal > -64 dBm (RPD)
        self.pkts = 0       # paquetes muestreados

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
            # Reiniciar indicadores para esta transmisión.
            self.t_start = self.last_rx
            self.t_end = 0.0
            self.bytes_rx = 0
            self.rpd_hits = 0
            self.pkts = 0
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
        # Muestrear el RPD (indicador de señal) por cada paquete recibido.
        self.pkts += 1
        if radio_mod.read_rpd(self.radio):
            self.rpd_hits += 1
        msg_type, seq, data = common.parse_packet(payload)
        if msg_type == common.T_DATA:
            self.blocks[seq] = data
            self.bytes_rx += len(data)
        elif msg_type == common.T_END:
            self.t_end = self.last_rx
            self.state = VERIFYING

    def _state_verifying(self):
        """Acepta la transmisión si faltan a lo sumo MAX_LOSS_PCT de los bloques
        (los huecos se rellenan con silencio en PLAYING); si faltan más, ERROR."""
        total = self.params["total_blocks"]
        faltan = total - len(self.blocks)
        pct = 100.0 * faltan / total if total else 0.0
        if pct <= config.MAX_LOSS_PCT:
            if faltan:
                print(f"Faltan {faltan}/{total} bloques ({pct:.1f}%) -> "
                      f"se rellenan con silencio.")
            else:
                print("Archivo completo.")
            self.state = PLAYING
        else:
            print(f"Demasiada pérdida: {faltan}/{total} bloques ({pct:.1f}% > "
                  f"{config.MAX_LOSS_PCT}%).")
            self.state = ERROR

    def _state_playing(self):
        """Reensambla los bytes recibidos (rellenando los bloques faltantes con
        silencio), los decodifica según el códec del START, reconstruye el WAV y
        lo reproduce por el DAC."""
        self.signals.playing()
        total = self.params["total_blocks"]
        # Byte de silencio según el códec: PCM unsigned -> 128; ADPCM -> 0.
        fill = (b"\x80" if self.params["codec"] == "pcm" else b"\x00") \
            * config.DATA_BYTES
        encoded = b"".join(self.blocks.get(i, fill) for i in range(total))
        # Decodificar a int16 según el códec (pcm o adpcm).
        samples = common.decode_audio(encoded, self.params["codec"])
        path = os.path.join(config.AUDIO_TMP_DIR, "recibido.wav")
        common.build_wav(path, samples.tobytes(), fs=self.params["fs"],
                         bits=16, channels=self.params["channels"])
        print(f"Reproduciendo {path} ({len(encoded)} bytes, "
              f"codec={self.params['codec']})...")
        self._print_link_report()
        self._play(samples)
        self.state = SUCCESS

    def _print_link_report(self):
        """Imprime los indicadores de la transmisión (duración, tasa efectiva,
        calidad de enlace y RPD)."""
        if not self.params:
            return
        end = self.t_end or self.last_rx
        print(common.link_report(
            audio_bytes=self.bytes_rx,
            duration_s=end - self.t_start,
            received=len(self.blocks),
            total=self.params["total_blocks"],
            rpd_hits=self.rpd_hits,
            pkts=self.pkts,
            codec=self.params["codec"],
            nominal_rate=config.RF_DATA_RATE,
        ))

    def _state_success(self):
        """Recepción y reproducción correctas, indica éxito y vuelve a escuchar."""
        self.signals.success()
        time.sleep(config.STATE_TIMEOUT)
        self._reset()

    def _state_error(self):
        """Fallo (archivo incompleto o timeout), señaliza error y vuelve a escuchar."""
        self._print_link_report()
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
