#include "esphome.h"

class UltrasonicSensor : public PollingComponent, public Sensor {
 public:
  UltrasonicSensor(uint32_t update_interval) : PollingComponent(update_interval) {}
  const int pingPin = 14;
  Sensor *ultrasonic_sensor = new Sensor();

  void setup() override {
  }

  void update() override {
    long duration, cm;

    pinMode(pingPin, OUTPUT);
    digitalWrite(pingPin, LOW);
    delayMicroseconds(3);
    digitalWrite(pingPin, HIGH);
    delayMicroseconds(6);
    digitalWrite(pingPin, LOW);

    pinMode(pingPin, INPUT);
    duration = pulseIn(pingPin, HIGH);
    cm = duration / 29 / 2;

    if(cm > 2) {
      ultrasonic_sensor->publish_state(cm);
    }
  }
};
