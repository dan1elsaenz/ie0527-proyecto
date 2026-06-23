"""
Empaquetado del protocolo de aplicación, conversión de muestras de audio
y reconstrucción del archivo WAV.

Se diseñaron tres tipos de mensaje, todos dentro del payload de 32 bytes
del nRF24:

  START : 0x01 | total_blocks(2) | fs(2) | bits(1) | channels(1) | codec(1)
  DATA  : 0x02 | seq(2)          | audio(29 como máximo)
  END   : 0x03

El total de bloques se envía solo en el START (el transmisor lo conoce de
antemano porque graba y fragmenta todo antes de transmitir). El END es un simple
marcador de fin de transmisión.
"""

import struct
import wave

import numpy as np

from config import (
    BITS,
    CHANNELS,
    CODEC,
    DATA_BYTES,
    SAMPLE_RATE,
)

# Tipos de mensaje
T_START = 0x01
T_DATA = 0x02
T_END = 0x03

# Códigos de códec dentro del paquete START
# Se puede expandir eventualmente
CODEC_CODES = {"pcm": 0x00, "ulaw": 0x01}
CODEC_NAMES = {v: k for k, v in CODEC_CODES.items()}


# ———————————————————————————————————————————————————————————————————————————
# Empaquetado / parseo del protocolo
# ———————————————————————————————————————————————————————————————————————————

def pack_start(total_blocks, fs=SAMPLE_RATE, bits=BITS, channels=CHANNELS,
               codec=CODEC):
    """Construye el paquete START con los parámetros necesarios para que el
    receptor reconstruya el audio."""
    return struct.pack(
        ">BHHBBB",          # Big endian, B=1 byte, H=2 bytes
        T_START,            # Código de inicio
        total_blocks,       # Número de paquetes de data
        fs,                 # Frecuencia de muestreo
        bits,               # Bits por muestra
        channels,           # Número de canales
        CODEC_CODES[codec], # Tipo de códec
    )


def parse_start(payload):
    """Devuelve un dict con los parámetros del paquete START."""
    _, total_blocks, fs, bits, channels, codec_code = struct.unpack(
        ">BHHBBB", bytes(payload[:8]) # 8 bytes
    )
    return {
        "total_blocks": total_blocks,
        "fs": fs,
        "bits": bits,
        "channels": channels,
        "codec": CODEC_NAMES.get(codec_code, "pcm"), # pcm predeterminado
    }


def pack_data(seq, chunk):
    """Construye un paquete DATA: tipo | número de bloque | datos de audio."""
    if len(chunk) > DATA_BYTES:
        raise ValueError(f"Chunk de {len(chunk)} bytes excede {DATA_BYTES}")
    return struct.pack(">BH", T_DATA, seq) + bytes(chunk)


def pack_end():
    """Construye el paquete END."""
    return struct.pack(">B", T_END)


def parse_packet(payload):
    """Parsea un payload recibido. Devuelve (tipo, seq, datos).

    - START/END: seq vale None y datos contiene el payload.
    - DATA: seq es el número de bloque y datos los bytes de audio.
    """
    payload = bytes(payload)
    if not payload:
        return None, None, b""
    msg_type = payload[0] # primer byte
    if msg_type == T_DATA:
        seq = struct.unpack(">H", payload[1:3])[0] # Extraer seq
        return T_DATA, seq, payload[3:]
    if msg_type in (T_START, T_END):
        # Pasar el payload completo a parse_start
        return msg_type, None, payload
    return msg_type, None, payload[1:]


def chunk_bytes(data, size=DATA_BYTES):
    """Divide data en bloques de (a lo sumo) size bytes."""
    return [data[i:i + size] for i in range(0, len(data), size)]


# ———————————————————————————————————————————————————————————————————————————
# Conversión de audio
# ———————————————————————————————————————————————————————————————————————————

def pcm24_to_u8(samples, gain=1.0):
    """Convierte muestras PCM de 24 bits con signo (del INMP441) a PCM de 8
    bits unsigned.

    samples es un array de enteros con signo (int32). El INMP441 entrega los
    24 bits útiles alineados a la izquierda dentro del word de 32 bits del I2S.
    Por eso se desplaza 16 bits para quedar en un valor de 16 bits con signo y
    luego dividir por 256 para tomar los 8 MSB.
    """
    s = np.asarray(samples, dtype=np.int32)
    # Valor de 16 bits con signo
    s16 = (s >> 16).astype(np.float32)        # rango [-32768, 32767]
    s16 = np.clip(s16 * gain, -32768.0, 32767.0)

    # Pasar a uint8: dividir por 256 y desplazar a 0-255
    u8 = np.clip(np.round(s16 / 256.0) + 128.0, 0, 255).astype(np.uint8)
    return u8.tobytes()


def build_wav(path, pcm_bytes, fs=SAMPLE_RATE, bits=BITS, channels=CHANNELS):
    """Escribe un archivo WAV a partir de los bytes PCM crudos. Incluye
    el header de 44 bytes."""
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(bits // 8)
        wav.setframerate(fs)
        wav.writeframes(bytes(pcm_bytes))
    return path
