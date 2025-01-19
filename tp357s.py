#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import datetime

from gi.repository import GLib
import pydbus


verbose = True
MAX_NUM = 28800

def byteStringDateTime (week = False):
    '''
    Get current date and time in the required format for requests to sensor

    Parameters
    ----------
    week : TYPE, optional
        If True it also returns a code for the weekday as needed for some commands. The default is False.

    Returns
    -------
    bs : bytestring
        Bytestring encoding the current date time.
    ts : integer
        Unix time stamp.
    '''
    dt_now = datetime.datetime.now();
    bs = bytes([dt_now.year%100,dt_now.month,dt_now.day,dt_now.hour,dt_now.minute,dt_now.second])
#    ts = dt_now.strftime('%y%m%d-%H%M%S')+'('+ str(int(dt_now.timestamp()))+')'
    ts = int(dt_now.timestamp())
    if week:
        bs += bytes([dt_now.isoweekday()])
    return bs, ts


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
    '''
    Convert triplet of bytes as returned by sensor into temperature and humidity values.

    Parameters
    ----------
    triplet : bytestring
        Triplet of bytes as returned by sensor. The first 2 bytes encode the temperature as a little endian int16, the final byte is the humidity.

    Returns
    -------
    list
        First value is temprature in deg C, 2nd humidity in percent.

    '''
    return [int.from_bytes(triplet[0:2], signed=True, byteorder='little')/10, triplet[2]]


def decodeHistoryReply(repl):
    results = []
    offset = int.from_bytes(repl[3:7], byteorder='little') 
    if (len(repl) != offset + 9):
        print("Response has the wrong length!")
        offset = len(repl) - 6
        print(repl)
    if not checkCheckSum(repl):
        print("Checksum incorrect")
    for ofs in range(7,offset + 6,3):
        results.append(decodeTempHumidity(repl[ofs:ofs+3]))
    return results

def checkCheckSum(response):
    '''
    Check that the simple checksum of data agrees with the transmitted checksum.

    Parameters
    ----------
    response : bytestring
        Array of bytes for which to calculate the checksum

    Returns
    -------
    boolean
        Does the data satisfy the checksum value.

    '''
    return sum(response[2:-3])%256 == response[-3]


def appendCheckSum(cmd):
    return cmd + bytes([sum(cmd)%256])


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

    return [decodeTempHumidity(raw[3:6])]


def get_temperatures(read, write, num):
    '''
    Get temperature history from the sensor.

    Parameters
    ----------
    read : TYPE
        DESCRIPTION.
    write : TYPE
        DESCRIPTION.
    num : int
        Number of timepoints requested, or if a negative number is supplied it 
        is interpreted as the time stamp of the last download and the number of 
        datapoints is automatically determined as the number of minutes passed
        since then.

    Returns
    -------
    hist : List of pairs 
        List of (temperature, humidity) values for the requested timepoints (latest first).
    ts : integer
        unix time stamp for the reading 
    '''
    raw = []
    responseExpectedSize = 0

#    if mode == "day":
#        op_code = [b"\xa7", b"\x7a"]
#    elif mode == "week":
#        op_code = [b"\xa6", b"\x6a"]
#    elif mode == "year":
#        op_code = [b"\xa8", b"\x8a"]
#    else:
#        raise RuntimeError(f"Unknown mode: {mode}")

    def temp_handler(iface, prop_changed, prop_removed):
        nonlocal responseExpectedSize

        if not 'Value' in prop_changed:
            return
#        print(prop_changed['Value'])
        if (responseExpectedSize == 0) and (prop_changed['Value'][0:2] == [204,204]):
            responseExpectedSize = int.from_bytes(prop_changed['Value'][3:7], byteorder='little') + 9 
            print("Expected response size", responseExpectedSize)
#        if prop_changed['Value'][0] == 194:  #204: #ord(op_code[0]):
        if len(prop_changed['Value']) == 7:
            # If we receive a 'standard response' quit the loop. 
            # Should not really happen any more...?
            print(prop_changed['Value'])
            mainloop.quit()
            return
        else:
            raw.extend(prop_changed['Value'])
            print(len(raw), " / ", responseExpectedSize)
            if (len(raw) >= responseExpectedSize):
                mainloop.quit()
            return

    read.onPropertiesChanged = temp_handler
    read.StartNotify()
    if verbose:
        print("Starting request of history")

    write.AcquireWrite({})
    # I currently have no idea what these 2 commands are doing. Are they actually needed?    
    cmd_fxd1 = b"\xCC\xCC\x02\x01\x00\x00\x01\x04\x66\x66"
    cmd_fxd2 = b"\xCC\xCC\x04\x00\x00\x00\x04\x66\x66"
    write.WriteValue(cmd_fxd1, {})
    write.WriteValue(cmd_fxd2, {})

    bs, ts = byteStringDateTime () 
    # Adjust timestamp to last full minute
    ts -= ts%60 
    if num < 0:
        num = (ts + num)//60
    # 28800 seems to be the maximum number of readings we can request:
    num = min(num, MAX_NUM)
    if verbose:
        print("Current timestamp: ", ts, ", number of points requested: ", num)
    cmd_var = b"\x01\x09\x00\x00\x00" + bs + bytes([num%256, num//256]) 
    cmd2 = b"\xCC\xCC" + appendCheckSum(cmd_var) + b"\x66\x66"
# Various  versions of this command I have snooped from the Android app:
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x0F\x00\x8F\x66\x66"
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x1F\x00\x8F\x66\x66" # Changing the number of points requested stops this working properly!
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x1F\x00\x9F\x66\x66" # Aha, seems to use a simple check sum
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x04\x27\x77\x00\xea\x66\x66"
#    cmd2 = b"\xCC\xCC\x01\x09\x00\x00\x00\x18\x04\x14\x0E\x13\x25\x0F\x00\x8F\x66\x66"
    write.WriteValue(cmd2, {})
    if verbose:
        print("Written command string: ")
        print(" ".join(hex(n) for n in cmd2))

    mainloop = GLib.MainLoop()
    mainloop.run()
    
#    print(raw)

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
    return hist, ts


if __name__ == "__main__":
    args = len(sys.argv) - 1 # Number of arguments provided
#    print(args)
    if args == 0:
        print("Need address of device as the first argument")
        exit()
    address = sys.argv[1]
    if verbose:
        print("Connecting to ", address)
    device, read, write = bt_setup(address)
    if verbose:
        print("Connected!");
    num = MAX_NUM
    mode = "hist"
    if args == 1:
        readings, ts = get_temperatures(read, write, num)        
    elif sys.argv[2] == "now":
        readings = wait_for_temp(read, write)
        print("Current reading: T =", readings[0][0], "C, H =", readings[0][1], "%")
        device.Disconnect()
        exit()
    elif sys.argv[2] == "hist":
        if (args == 3) and sys.argv[3].isdigit():
            num = int(sys.argv[3])
        readings, ts = get_temperatures(read, write, num)
    elif sys.argv[2] == "log":
        mode = "log"
        flog = address.replace(":", "-") + ".log"
        if (args == 3) and sys.argv[3].isdigit():
            num = -int(sys.argv[3])
        else:
            try:
                with open(flog, "r") as fl:
                    ts_log = fl.read()
                    if ts_log.isdigit():
                        num = -int(ts_log)
            except FileNotFoundError:
                print("No log file found for this device")
        readings, ts = get_temperatures(read, write, num)
#    else:

    device.Disconnect()

    import csv
#    writer = csv.writer(sys.stdout)
    tstart = ts - 60*(len(readings) - 1)
    fn = address.replace(":", "-") + "_" + str(tstart) + "-" + str(ts) + ".csv"
    if mode == "log":        
        with open(flog, "w") as logfile:
            logfile.write(str(ts))
    file1 = open(fn, 'w')
    writer = csv.writer(file1)
    writer.writerow(["timestamp", "temp","humid"])
    for res in reversed(readings):
        row = [tstart] + res
        writer.writerow(row)
        tstart += 60
    file1.close()
