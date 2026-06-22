"""
Configuración del transceiver nRF24L01+PA+LNA mediante pyRF24.
"""

from pyrf24 import (
    RF24,
    RF24_CRC_16,
    RF24_PA_HIGH,
    RF24_PA_LOW,
    RF24_PA_MAX,
    RF24_PA_MIN,
    RF24_250KBPS,
    RF24_1MBPS,
    RF24_2MBPS,
)

import config

# Tasas de datos soportadas
_DATA_RATES = {
    "250kbps": RF24_250KBPS,
    "1Mbps": RF24_1MBPS,
    "2Mbps": RF24_2MBPS,
}

# Niveles de potencia
_PA_LEVELS = {
    "min": RF24_PA_MIN,
    "low": RF24_PA_LOW,
    "high": RF24_PA_HIGH,
    "max": RF24_PA_MAX,
}


def _apply_common(radio):
    """Aplica la configuración compartida del enlace."""
    radio.setPALevel(_PA_LEVELS[config.RF_PA_LEVEL])
    radio.setDataRate(_DATA_RATES[config.RF_DATA_RATE])
    radio.setChannel(config.RF_CHANNEL)
    radio.setAddressWidth(len(config.RF_ADDRESS))
    radio.setCRCLength(RF24_CRC_16)
    radio.setAutoAck(config.AUTO_ACK)
    radio.setRetries(config.RETRY_DELAY, config.RETRY_COUNT)
    if config.DYNAMIC_PAYLOADS:
        radio.enableDynamicPayloads()
    else:
        radio.setPayloadSize(config.PAYLOAD_SIZE)


def open_radio():
    """Inicializa la radio y devuelve la instancia de RF24 para configurarse
    como TX o RX."""
    radio = RF24(config.PIN_CE, config.SPI_BUS * 10 + config.SPI_DEVICE)

    # Abrir comunicación
    if not radio.begin():
        raise RuntimeError("No se pudo inicializar el nRF24L01.")
    _apply_common(radio)
    return radio


def open_tx(radio):
    """Configura la radio como transmisor."""
    radio.stopListening()
    radio.openWritingPipe(config.RF_ADDRESS)


def open_rx(radio):
    """Configura la radio como receptor en escucha continua."""
    radio.openReadingPipe(1, config.RF_ADDRESS)
    radio.startListening()
