ThermoPro TP357S Temperature Sensor Client
==========================================

This tiny Python client for the ThermoPro TP357S BLE bluetooth sensor can be used to
retrieve the current temperature and humidity readings (the sensor periodically sends a
notification) as well as fetch the history that the sensor stores.

TP357S is a pretty nifty temperature and humidity sensor ideal for e.g.
monitoring individual rooms in a flat. It is tiny and cheap, has both display
and bluetooth, has battery life (single AAA) of around 6 months, and seems
pretty accurate.

Usage: `tp357s.py ADDRESS MODE NUM`

**ADDRESS** - hardware address of the device; use bluetoothctl + "scan on" + "devices" to find it

**MODE** - "now" (current temperature), "hist" (minute-by-minute history) or "log" (minute-by-minute history)

**NUM** - (optional) integer specifying the number of readings to take

Example: `./tp357s.py B8:59:CE:32:9C:D1 now`

Outputs a CSV file with timestamp, temperature and humidity (oldest first).



Modes
-----
- "now": Print the current reading to terminal
- "hist": Retrieve minute-by-minute history and save it to a csv file. The **NUM** argument can be provided to specify the number of data points the script tries to download. If **NUM** is not provided it defaults to the maximum supported value (which seems to be 28800).
- "log": Almost the same as "hist", but in this case **NUM** is interpreted as a unix time stamp and the script tries to download all the data since then. If **NUM** is not supplied the script will check the previous log timestamp. 

