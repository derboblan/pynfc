#! /usr/bin/env python3

from . import nfc
import ctypes
import binascii

context = ctypes.pointer(nfc.nfc_context())
nfc.nfc_init(ctypes.byref(context))

conn_strings = (nfc.nfc_connstring * 10)()
devices_found = nfc.nfc_list_devices(context, conn_strings, 10)

if not devices_found:
    print("No devices found")
    exit(-1)

device = nfc.nfc_open(context, conn_strings[0])

init = nfc.nfc_initiator_init(device)

nt = nfc.nfc_target()

mods = [(nfc.NMT_ISO14443A, nfc.NBR_106)]
modulations = (nfc.nfc_modulation * len(mods))()
for i in range(len(mods)):
    modulations[i].nmt = mods[i][0]
    modulations[i].nbr = mods[i][1]

res = nfc.nfc_initiator_poll_target(device, modulations, len(modulations), 10, 2, ctypes.byref(nt))

if res < 0:
    raise IOError("NFC Error whilst polling")

uidLen = 7
uid = bytearray([nt.nti.nai.abtUid[i] for i in range(uidLen)])
print("uid = {}".format(binascii.hexlify(uid)))