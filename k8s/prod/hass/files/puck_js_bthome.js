var slowTimeout; //< After 60s we revert to slow advertising

// Update the data we're advertising here
function updateAdvertising(buttonState) {
  NRF.setAdvertising(require("BTHome").getAdvertisement([
    {
      type : "battery",
      v : E.getBattery()
    },
    {
      type : "temperature",
      v : E.getTemperature()
    },
    {
      type: "button_event",
      v: buttonState
    },
  ]), {
    name : "Sensor",
    interval: (buttonState!="none")?20:2000, // fast when we have a button press, slow otherwise
    // not being connectable/scannable saves power (but you'll need to reboot to connect again with the IDE!)
    //connectable : false, scannable : false,
  });
  /* After 60s, call updateAdvertising again to update battery/temp
  and to ensure we're advertising slowly */
  if (slowTimeout) clearTimeout(slowTimeout);
  slowTimeout = setTimeout(function() {
    slowTimeout = undefined;
    updateAdvertising("none" /* no button pressed */);
  }, 60000);
}

// When a button is pressed, update advertising with the event
setWatch(function(e) {
  var buttonState = ((e.time - e.lastTime) > 0.5) ? "long_press" : "press";
  updateAdvertising(buttonState);
  console.log("pressed");
}, BTN, {edge:"falling", repeat:true})

// Update advertising now
updateAdvertising("none");

// Enable highest power advertising (4 on nRF52, 8 on nRF52840)
NRF.setTxPower(4);
