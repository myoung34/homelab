#pragma once

#include <Wire.h>

#define PCT_ADDRESS 0x49


class Pct2075 {
  private:
    float temperature;

  public:
    // Sets up I2C wire for the tmp102
    void setup(int sda, int scl) {
      Wire.begin(sda, scl);
    }

    bool shut_down() {
      Wire.beginTransmission(PCT_ADDRESS);
      Wire.write(0x01); // Set register pointer to 01h conf
      Wire.write(0x01); // Set B0 register to 1 to enable shutdown
      if (Wire.endTransmission() == 0) {
        return true;
      } else {
        return false;
      }
    }

    bool wake_up() {
      Wire.beginTransmission(PCT_ADDRESS);
      Wire.write(0x01); // Set register pointer to 01h conf
      Wire.write(0x00); // Set B0 register to 0 to wake up
      if (Wire.endTransmission() == 0) {
        return true;
      } else {
        return false;
      }
    }

    float get_temperature() {
      return this->temperature;
    }

    bool read_temperature() {
      Wire.beginTransmission(PCT_ADDRESS);
      Wire.write(0x00); // Set pointer to scratch
      if (Wire.endTransmission() != 0) {
        return false;
      }
      Wire.requestFrom(PCT_ADDRESS, 2);
      byte MSB = Wire.read();
      byte LSB = Wire.read();

      if (Wire.endTransmission() == 0) {
        //it's a 11bit int, using two's compliment for negative
        int TemperatureSum = ( (MSB << 3) | (LSB >> 5) );
        float TempC = TemperatureSum * 0.125;
        if (TempC > 128) {
          TempC = TempC - 256; // for negative temperatures
        }
        this->temperature = TempC;
        return true;
      } else {
        return false;
      }

    }
};

class Pct2075_simulator {
  private:
    float temperature;

  public:
    // Sets up I2C wire for the tmp102
    void setup(int sda, int scl) {
      (void)sda;
      (void)scl;
      randomSeed(analogRead(0));
    }

    bool shut_down() {
      return true;
    }

    bool wake_up() {
      return true;
    }

    float get_temperature() {
      return this->temperature;
    }

    bool read_temperature() {
      this->temperature = 18.0 + float(random(50))/10.0;
      return true;
    }
};


#ifdef SIMULATE_SENSORS
  Pct2075_simulator temperature_sensor;
#else
  Pct2075 temperature_sensor;
#endif
