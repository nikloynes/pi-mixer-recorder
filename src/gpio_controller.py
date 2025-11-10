"""
GPIO control for physical button and LED indicator
"""

import logging
from typing import TYPE_CHECKING

try:
    from RPi import GPIO

    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    logging.warning("RPi.GPIO not available, GPIO features disabled")

if TYPE_CHECKING:
    from config import ConfigManager
    from src.audio_recorder import AudioRecorder

logger = logging.getLogger(__name__)


class GPIOController:
    """Handles GPIO button and LED control"""

    def __init__(self, config: "ConfigManager", recorder: "AudioRecorder") -> None:
        """
        Initialize GPIO controller

        Args:
            config: ConfigManager instance
            recorder: AudioRecorder instance

        """
        if not GPIO_AVAILABLE:
            raise RuntimeError("GPIO not available on this system")

        self.config = config
        self.recorder = recorder

        self.button_pin: int = config.get("gpio.button_pin")
        self.led_pin: Optional[int] = config.get("gpio.led_pin")
        self.bounce_time: int = config.get("gpio.button_bounce_time", 300)

        if self.button_pin is None:
            raise ValueError("Button pin not configured")

        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Setup button with pull-up resistor
        GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(
            self.button_pin,
            GPIO.FALLING,
            callback=self._button_pressed,
            bouncetime=self.bounce_time,
        )

        # Setup LED if configured
        if self.led_pin is not None:
            GPIO.setup(self.led_pin, GPIO.OUT)
            GPIO.output(self.led_pin, GPIO.LOW)

        logger.info(
            f"GPIO initialized - Button: GPIO{self.button_pin}, LED: GPIO{self.led_pin}"
        )

    def _button_pressed(self, channel: int) -> None:
        """Callback for button press"""
        logger.info("Button pressed")

        if self.recorder.is_recording:
            self.recorder.stop_recording()
            self._set_led(False)
        else:
            self.recorder.start_recording()
            self._set_led(True)

    def _set_led(self, state: bool) -> None:
        """
        Set LED state

        Args:
            state: True for on, False for off

        """
        if self.led_pin is not None:
            GPIO.output(self.led_pin, GPIO.HIGH if state else GPIO.LOW)

    def cleanup(self) -> None:
        """Cleanup GPIO resources"""
        logger.info("Cleaning up GPIO")
        if GPIO_AVAILABLE:
            GPIO.cleanup()
