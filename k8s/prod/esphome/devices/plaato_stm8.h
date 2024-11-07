#pragma once

#include <Wire.h>

extern "C" {
  #include "user_interface.h"           // Needed for system_get_rst_info() in simulator
}

class  Plaato_stm8 {
  private:
    int address = 0x3;
    uint32_t bubble_count = 0;
    uint32_t bubble_size_total = 0;
    bool reset_flag = false;
  public:
    bool setup() {
      Wire.begin(14,12);
      uint8_t i = 0;
      while(digitalRead(14) == 0 ) { // if SDA is low, do (max) 10 cycles on SCL.
		    delayMicroseconds(4);
		    GPES = (1 << 12); // SCL low
		    delayMicroseconds(4);
		    GPEC = (1 << 12); // SCL high
		    i++;
		    if (i >= 10) {
		    	return false;
		    }
		  }
		  return true;
    }

    bool set_led(uint8_t led_mode) {
      Wire.beginTransmission(address);
      Wire.write(led_mode);
      if (Wire.endTransmission() == 0) {
        return true;
      } else {
        return false;
      }
    }

    bool sync() {
			uint8_t bytes[5];
			Wire.beginTransmission(address);
			if (Wire.requestFrom(address, 5) == 5) {
				bytes[0] = Wire.read();
				bytes[1] = Wire.read();
				bytes[2] = Wire.read();
				bytes[3] = Wire.read();
				bytes[4] = Wire.read();
				if (Wire.endTransmission() == 0) {
					if (bytes[0]) {
					  reset_flag = true;
					} else {
					  reset_flag = false;
					}

					bubble_count = (uint32_t)bytes[4] | (uint32_t)bytes[3] << 8| (uint32_t)bytes[2] << 16 | (uint32_t)bytes[1] << 24;
          return true;
				} else {
					return false;
				}
			}
			return false;
    }

    bool sync2() {
      uint8_t bytes[9];
      Wire.beginTransmission(address);
      if (Wire.requestFrom(address, 9) == 9) {
        bytes[0] = Wire.read();
        bytes[1] = Wire.read();
        bytes[2] = Wire.read();
        bytes[3] = Wire.read();
        bytes[4] = Wire.read();
        bytes[5] = Wire.read();
        bytes[6] = Wire.read();
        bytes[7] = Wire.read();
        bytes[8] = Wire.read();
        if (Wire.endTransmission() == 0) {
          if (bytes[0]) {
            reset_flag = true;
          } else {
            reset_flag = false;
          }

          bubble_count = (uint32_t)bytes[4] | (uint32_t)bytes[3] << 8| (uint32_t)bytes[2] << 16 | (uint32_t)bytes[1] << 24;
          bubble_size_total = (uint32_t)bytes[8] | (uint32_t)bytes[7] << 8| (uint32_t)bytes[6] << 16 | (uint32_t)bytes[5] << 24;
          return true;
        } else {
          return false;
        }
      }
      return false;
    }

    uint32_t get_count() {
      return bubble_count;
    }

    uint32_t get_size() {
      return bubble_size_total;
    }

    bool get_reset_flag() {
      return reset_flag;
    }
};

class  Plaato_stm8_simulator {
  private:
    uint32_t *ESP_bubble_count = (uint32_t *)0x60001200;
    uint32_t *extern_sleep_counter = (uint32_t *)0x60001240;
    bool reset_flag = false;
  public:
    bool setup() {
		if (system_get_rst_info()->reason != REASON_DEEP_SLEEP_AWAKE) {
			*ESP_bubble_count = 0;
		}
		pinMode(0, INPUT);
		return true;
    }

    bool set_led(uint8_t led_mode) {
      (void)led_mode;
      return true;
    }

    bool sync() {
      	if (digitalRead(0) == false) {
  			reset_flag = true;
  		}
		*ESP_bubble_count += 5 * (*extern_sleep_counter);
		return true;
    }

    uint32_t get_count() {
      return *ESP_bubble_count;
    }

    bool get_reset_flag() {
      return reset_flag;
    }
};


#ifdef SIMULATE_SENSORS
  Plaato_stm8_simulator stm8;
#else
  Plaato_stm8 stm8;
#endif
