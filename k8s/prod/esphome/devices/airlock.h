#include "esphome.h"
#include "plaato_stm8.h"
#include "pct2075.h"

const uint16_t POLLING_PERIOD = 1000; //milliseconds

const enum Led_mode {
  NO_MODE,
  COUNTING1,
  COUNTING2,
  SLOWBREATHING,
  FASTBREATHING,
  SLOWFLASH,
  FASTFLASH,
  ALLOFF,
  ALLON,
  BOT,
  MID,
  TOP,
  SLOWDOWN,
  FASTDOWN,
  SLOWUP,
  FASTUP,
  BOTSLOWFLASH,
  BOTFASTFLASH,
  MIDSLOWFLASH,
  MIDFASTFLASH,
  TOPSLOWFLASH,
  TOPFASTFLASH,
  BOTONBUBBLE
};

class PlaatoAirlock : public PollingComponent {
 public:
  PlaatoAirlock() : PollingComponent(POLLING_PERIOD) {}
  float get_setup_priority() const override { return esphome::setup_priority::BUS; } //Access I2C bus
  Sensor *bubble_count_sensor = new Sensor();
  Sensor *temperature_sensor = new Sensor();


  void setup() override {
    stm8.setup();             // This sets up I2C.
    delay(100);               // Delay for I2C to work
  }

  void update() override {
    temperature_sensor.wake_up();
    temperature_sensor.read_temperature();
    temperature_sensor.shut_down();

    // Check for reset and get bubblecount
    stm8.sync();

    // Set LED on STM8
    stm8.set_led(SLOWBREATHING);

    // Get values and publish them
    float temp = temperature_sensor.get_temperature();
    int bubble_count = stm8.get_count();

    bubble_count_sensor->publish_state(bubble_count)
    temperature_sensor->publish_state(temp)

    ESP_LOGD("main", "temperature: %0.2f°C", temp);
    ESP_LOGD("main", "bubbles: %0.2f°C", bubble_count);

  }
};
