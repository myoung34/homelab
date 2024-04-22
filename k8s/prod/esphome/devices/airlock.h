#include "esphome.h"
#include <Wire.h>

const uint16_t POLLING_PERIOD = 1000; //milliseconds
int original = -1; //Initial value of the register

class Foo : public PollingComponent {
 public:
  Foo() : PollingComponent(POLLING_PERIOD) {}
  float get_setup_priority() const override { return esphome::setup_priority::BUS; } //Access I2C bus
  Sensor *foo = new Sensor();

  void update() override {

    byte error, address;
    int nDevices;

    nDevices = 0;
    //char register_value = id(input_1).state; //Read the number set on the dashboard
    int register_value = id(input_1).state - '0' + 48; //Read the number set on the dashboard
    //Did the user change the input?
    if(register_value != original){
      //ESP_LOGD("custom", "Trying 0x%d", register_value);
      char register_as_char = register_value;
      Wire.beginTransmission(0x00);
      error = Wire.endTransmission();
      // Looking for error code "0" to know we found the device over i2c
      foo->publish_state(error);

      Wire.requestFrom(0x00, 1);
      if (Wire.available()) { // slave may send less than requested
        char c = Wire.read(); // receive a byte as character
        ESP_LOGD("custom", "read %s", c);
      }


      original = register_value; //Swap in the new value
    }
  }
};
