#include "esphome.h"
#include "Ultrasonic.h"

Ultrasonic ultrasonic(23);


class UltrasonicSensor : public PollingComponent, public Sensor {
 public:
  UltrasonicSensor(uint32_t update_interval) : PollingComponent(update_interval) {}

  void setup() override {
  }

  void update() override {
    int distance = ultrasonic.MeasureInCentimeters();
    ESP_LOGD("main", "ultrasonic: %0.2f", distance);

    publish_state(distance);
  }
};
