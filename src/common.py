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
CODEC_CODES = {"pcm": 0x00, "ulaw": 0x01, "adpcm": 0x02}
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

def pcm24_to_pcm16(samples, gain=1.0):
    """Convierte muestras de 24 bits con signo (del INMP441) a int16.

    El INMP441 entrega los 24 bits útiles alineados a la izquierda dentro del
    word de 32 bits del I2S, así que se desplaza 16 bits para quedar en un valor
    de 16 bits con signo.
    """
    s = np.asarray(samples, dtype=np.int32)
    s16 = (s >> 16).astype(np.float32)        # rango [-32768, 32767]
    s16 = np.clip(s16 * gain, -32768.0, 32767.0)
    return np.round(s16).astype(np.int16)


def pcm24_to_u8(samples, gain=1.0):
    """Convierte muestras PCM de 24 bits con signo a PCM de 8 bits unsigned
    (0-255, 128 = cero). Toma los 8 MSB del valor de 16 bits."""
    s16 = pcm24_to_pcm16(samples, gain).astype(np.int16)
    u8 = np.clip((s16.astype(np.int32) >> 8) + 128, 0, 255).astype(np.uint8)
    return u8.tobytes()


def u8_to_pcm16(pcm_bytes):
    """Convierte PCM de 8 bits sin signo (0-255, 128 = cero) a muestras int16
    centradas en 0."""
    u8 = np.frombuffer(bytes(pcm_bytes), dtype=np.uint8)
    return ((u8.astype(np.int16) - 128) * 256).astype(np.int16)


# ———————————————————————————————————————————————————————————————————————————
# Compresión IMA ADPCM
# ———————————————————————————————————————————————————————————————————————————

# Tablas estándar IMA/DVI ADPCM
_ADPCM_INDEX_TABLE = np.array(
    [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8], dtype=np.int32
)
_ADPCM_STEP_TABLE = np.array([
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
    209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724,
    796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272,
    2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132,
    7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350,
    22385, 24623, 27086, 29794, 32767,
], dtype=np.int32)


def ima_adpcm_encode(samples_int16):
    """Comprime muestras int16 a IMA ADPCM de 4 bits/muestra. Devuelve bytes
    (2 muestras por byte). Codifica el buffer completo."""
    samples = np.asarray(samples_int16, dtype=np.int32)
    predictor = 0
    index = 0
    nibbles = []
    for sample in samples:
        step = int(_ADPCM_STEP_TABLE[index])
        diff = int(sample) - predictor
        code = 0
        if diff < 0:
            code = 8
            diff = -diff
        delta = 0
        if diff >= step:
            delta = 4
            diff -= step
        step >>= 1
        if diff >= step:
            delta |= 2
            diff -= step
        step >>= 1
        if diff >= step:
            delta |= 1
        code |= delta

        # Reconstruir el predictor como lo hará el decodificador.
        step = int(_ADPCM_STEP_TABLE[index])
        vpdiff = step >> 3
        if delta & 4:
            vpdiff += step
        if delta & 2:
            vpdiff += step >> 1
        if delta & 1:
            vpdiff += step >> 2
        predictor += -vpdiff if (code & 8) else vpdiff
        predictor = max(-32768, min(32767, predictor))
        index = int(np.clip(index + _ADPCM_INDEX_TABLE[code], 0, 88))
        nibbles.append(code & 0x0F)

    # Empaquetar 2 nibbles por byte (primera muestra en los 4 bits bajos).
    if len(nibbles) % 2:
        nibbles.append(0)
    arr = np.array(nibbles, dtype=np.uint8)
    packed = (arr[0::2] | (arr[1::2] << 4)).astype(np.uint8)
    return packed.tobytes()


def ima_adpcm_decode(data):
    """Descomprime bytes IMA ADPCM (4 bits/muestra) a muestras int16."""
    packed = np.frombuffer(bytes(data), dtype=np.uint8)
    nibbles = np.empty(packed.size * 2, dtype=np.uint8)
    nibbles[0::2] = packed & 0x0F
    nibbles[1::2] = packed >> 4

    predictor = 0
    index = 0
    out = np.empty(nibbles.size, dtype=np.int16)
    for i, code in enumerate(nibbles):
        code = int(code)
        step = int(_ADPCM_STEP_TABLE[index])
        vpdiff = step >> 3
        if code & 4:
            vpdiff += step
        if code & 2:
            vpdiff += step >> 1
        if code & 1:
            vpdiff += step >> 2
        predictor += -vpdiff if (code & 8) else vpdiff
        predictor = max(-32768, min(32767, predictor))
        index = int(np.clip(index + _ADPCM_INDEX_TABLE[code], 0, 88))
        out[i] = predictor
    return out


# ———————————————————————————————————————————————————————————————————————————
# Despacho por códec (lo que usan tx.py y rx.py)
# ———————————————————————————————————————————————————————————————————————————

def encode_audio(samples24, gain=1.0, codec=CODEC):
    """Codifica muestras de 24 bits (int32) al formato de transmisión según el
    códec. Devuelve los bytes listos para fragmentar y enviar."""
    if codec == "adpcm":
        return ima_adpcm_encode(pcm24_to_pcm16(samples24, gain))
    return pcm24_to_u8(samples24, gain)   # pcm default


def decode_audio(data, codec="pcm"):
    """Decodifica los bytes recibidos a muestras int16 listas para reproducir,
    según el códec indicado en el START."""
    if codec == "adpcm":
        return ima_adpcm_decode(data)
    return u8_to_pcm16(data)              # pcm default


def build_wav(path, pcm_bytes, fs=SAMPLE_RATE, bits=BITS, channels=CHANNELS):
    """Escribe un archivo WAV a partir de los bytes PCM crudos. Incluye
    el header de 44 bytes."""
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(bits // 8)
        wav.setframerate(fs)
        wav.writeframes(bytes(pcm_bytes))
    return path
