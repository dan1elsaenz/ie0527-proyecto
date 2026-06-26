"""
Parámetros compartidos entre el nodo transmisor (tx.py) y el receptor (rx.py).
"""

# ———————————————————————————————————————————————————————————————————————————
# nRF24L01+PA+LNA
# ———————————————————————————————————————————————————————————————————————————

# Dirección del pipe (misma en tx y rx). 5 bytes.
RF_ADDRESS = b"AUDIO"

# Canal RF (0-125). Cada canal son 1 MHz a partir de 2400 MHz.
# Alejado de los canales WiFi 1/6/11.
RF_CHANNEL = 76

# Tasa de datos: "250kbps", "1Mbps" o "2Mbps".
# Se usa 1 Mbps para cumplir el tiempo de transmisión (< 60 s).
RF_DATA_RATE = "1Mbps"

# Potencia de salida: "min" (-18 dBm), "low" (-12), "high" (-6), "max" (0 dBm).
RF_PA_LEVEL = "max"

# Tamaño máximo del payload del nRF24.
PAYLOAD_SIZE = 32

# Payload dinámico.
DYNAMIC_PAYLOADS = True

# Auto-ACK (Enhanced ShockBurst): confirmación y retransmisión automáticas.
AUTO_ACK = True

# Reintentos automáticos del ESB por paquete.
RETRY_COUNT = 15        # ARC 0-15 reintentos
RETRY_DELAY = 5         # ARD pasos de 250 us (1500 us)

# Reintentos a nivel de aplicación.
APP_RETRIES = 5

# ———————————————————————————————————————————————————————————————————————————
# Parámetros de digitalización de audio
# ———————————————————————————————————————————————————————————————————————————

SAMPLE_RATE = 8000      # Hz
BITS = 8                # bits por muestra
CHANNELS = 1            # mono

# Códec de la carga de audio:
#   "pcm"   -> PCM lineal 8 bits (64 kbps)
#   "adpcm" -> IMA ADPCM 4 bits (~32 kbps)
CODEC = "adpcm"

# Ganancia digital aplicada al pasar de 24 a 8 bits
# Hay que ajustar.
MIC_GAIN = 1.0

# ———————————————————————————————————————————————————————————————————————————
# Estructura de la trama dentro del payload de 32 bytes
# ———————————————————————————————————————————————————————————————————————————

# Paquete DATA
TYPE_BYTES = 1
SEQ_BYTES = 2
DATA_BYTES = PAYLOAD_SIZE - TYPE_BYTES - SEQ_BYTES   # 29

# ———————————————————————————————————————————————————————————————————————————
# Asignación de pines GPIO
# ———————————————————————————————————————————————————————————————————————————

# nRF24L01+PA+LNA (SPI0)
PIN_CE = 25             # Chip Enable
PIN_CSN = 0             # Chip Select
SPI_BUS = 0
SPI_DEVICE = 0          # CE0 = GPIO8

# Botón y LEDs
PIN_BUTTON = 17
PIN_LED_GREEN = 27
PIN_LED_YELLOW = 22
PIN_LED_RED = 23

# ———————————————————————————————————————————————————————————————————————————
# Tiempos de operación
# ———————————————————————————————————————————————————————————————————————————

STATE_TIMEOUT = 3.0      # Tiempo que permanecen los estados SUCCESS/ERROR antes de IDLE
RX_PACKET_TIMEOUT = 5.0  # Tiempo sin paquetes durante recepción

# Carpeta para archivos WAV temporales en el receptor.
AUDIO_TMP_DIR = "/tmp/audio_rx"
