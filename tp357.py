#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import datetime

from gi.repository import GLib
import pydbus


def binaryDataTime (week = False):
    dt_now = datetime.datetime.now();
    bs = bytes([dt_now.year%100,dt_now.month,dt_now.day,dt_now.hour,dt_now.minute,dt_now.second])
    if week:
        bs += bytes([dt_now.isoweekday()])
    return bs


def get_device(bus, address):
    try:
        return bus.get("org.bluez", "/org/bluez/hci0/dev_" + address.replace(":", "_"))
    except KeyError:
        adapter = bus.get("org.bluez", "/org/bluez/hci0")
        adapter.StartDiscovery()
        N_TRIES = 12
        N_TRY_LENGTH = 5
        for i in range(N_TRIES):
            time.sleep(N_TRY_LENGTH)
            try:
                device = bus.get("org.bluez", "/org/bluez/hci0/dev_" + address.replace(":", "_"))
                break
            except KeyError:
                pass
            print(f"Waiting for device... {i+1}/{N_TRIES}", file=sys.stderr)
        else:
            adapter.StopDiscovery()
            print("Device not found", file=sys.stderr)
            sys.exit(1)
        adapter.StopDiscovery()
        return device


def bt_setup(address):
    bus = pydbus.SystemBus()
    device = get_device(bus, address)

    N_TRIES = 3
    for i in range(N_TRIES):
        try:
            device.Connect()
            break
        except GLib.Error as e:
            print(f"Connecting to device... {i+1}/{N_TRIES}", file=sys.stderr)
            print(e, file=sys.stderr)
            time.sleep(1)
    else:
        print("Connection failed", file=sys.stderr)
        sys.exit(1)
    time.sleep(2)  # XXX: wait for services etc. to be populated

    object_manager = bus.get("org.bluez", "/")["org.freedesktop.DBus.ObjectManager"]

    uuid_write = "00010203-0405-0607-0809-0a0b0c0d2b11"
    uuid_read  = "00010203-0405-0607-0809-0a0b0c0d2b10"

    def get_characteristic(uuid):
        return [desc for desc in object_manager.GetManagedObjects().items()
                if desc[0].startswith(device._path) and desc[1].get("org.bluez.GattCharacteristic1", {}).get("UUID") == uuid][0]

    write = bus.get("org.bluez", get_characteristic(uuid_write)[0])
    read = bus.get("org.bluez", get_characteristic(uuid_read)[0])
    return device, read, write

def decodeTempHumidity(triplet):
    return [(triplet[0]+triplet[1]*256)/10, triplet[2]]

def decodeHistoryReply(repl):
    results = []
    offset = repl[3]+repl[4]*256
    for ofs in range(7,offset + 6,3):
        results.append(decodeTempHumidity(repl[ofs:ofs+3]))
    return results

def wait_for_temp(read, write):
    raw = []

    def temp_handler(iface, prop_changed, prop_removed):
        if not 'Value' in prop_changed:
            return

        if prop_changed['Value'][0] == 194:
            raw.extend(prop_changed['Value'])
            mainloop.quit()
            return

    read.onPropertiesChanged = temp_handler
    read.StartNotify()
    mainloop = GLib.MainLoop()
    mainloop.run()

#    temp = (raw[3] + raw[4] * 256) / 10
#    humid = raw[5]
    return [decodeTempHumidity(raw[3:6])]


def get_temperatures(read, write, mode):
    raw = []

    if mode == "day":
        op_code = [b"\xa7", b"\x7a"]
    elif mode == "week":
        op_code = [b"\xa6", b"\x6a"]
    elif mode == "year":
        op_code = [b"\xa8", b"\x8a"]
    else:
        raise RuntimeError(f"Unknown mode: {mode}")

    def temp_handler(iface, prop_changed, prop_removed):
        if not 'Value' in prop_changed:
            return

        print(prop_changed['Value'])
        if prop_changed['Value'][0] == 194:  #204: #ord(op_code[0]):
#            raw.append(prop_changed['Value'])
#        elif raw:
            mainloop.quit()
            return
        else:
            raw.extend(prop_changed['Value'])
#        mainloop.quit()
#        return

    read.onPropertiesChanged = temp_handler
    read.StartNotify()
    print("Starting request of history")

    write.AcquireWrite({})
    
    cmd_fxd1 = b"\xCC\xCC\x02\x01\x00\x00\x01\x04\x66\x66"
    cmd_fxd2 = b"\xCC\xCC\x04\x00\x00\x00\x04\x66\x66"
    
#    write.WriteValue(op_code[0] + b"\x01\x00" + op_code[1], {})
    write.WriteValue(cmd_fxd1, {})
    write.WriteValue(cmd_fxd2, {})

    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00" + binaryDataTime () + b"\x0F\x00" + b"\x00" + b"\x66\x66"
# Various  version of this command I have snooped from the Android app:
    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x0F\x00\x8F\x66\x66"
    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x1F\x00\x8F\x66\x66" # Changing the number of points requested stops this working properly!
    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x1F\x00\x9F\x66\x66" # Aha, seems to use a simple check sum
    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x04\x27\x77\x00\xea\x66\x66"
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x0F\x00\x8F\x66\x66"
    write.WriteValue(cmd2, {})
    print("Written command string: ")
    print(cmd2)

    mainloop = GLib.MainLoop()
    mainloop.run()

    hist = decodeHistoryReply(raw)
# original code below. Output format seems to have changed... 
 #   temps = []
 #   humids = []
 #   for t in raw:
 #       if t[0] != ord(op_code[0]):
 #           continue
 #       time = t[1] + t[2]*256
 #       flag = t[3]
 #       for i in range(5):
 #           ofs = 4 + i * 3
 #           if t[ofs] == 0xff and t[ofs + 1] == 0xff:
 #               temps.append(float('nan'))
 #               humids.append(float('nan'))
 #               continue
 #           temps.append((t[ofs] + t[ofs + 1] * 256) / 10)
 #           humids.append(t[ofs + 2])
    return hist


if __name__ == "__main__":
    device, read, write = bt_setup(sys.argv[1])

    if sys.argv[2] == "now":
        readings = wait_for_temp(read, write)
    else:
        readings = get_temperatures(read, write, sys.argv[2])
#        print(device, read, write)

    device.Disconnect()

    import csv
    writer = csv.writer(sys.stdout)
    writer.writerow(["temp","humid"])
    for i in range(len(readings)):
        writer.writerow(readings[i])
