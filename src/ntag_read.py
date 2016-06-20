#! /usr/bin/env python3

from . import nfc
import ctypes
import binascii

MC_AUTH_A = 0x60
MC_AUTH_B = 0x61
MC_READ = 0x30
MC_WRITE = 0xA0
card_timeout = 10

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

# setup device
if nfc.nfc_device_set_property_bool(device, nfc.NP_ACTIVATE_CRYPTO1, True) < 0:
    raise Exception("Error setting Crypto1 enabled")
if nfc.nfc_device_set_property_bool(device, nfc.NP_INFINITE_SELECT, False) < 0:
    raise Exception("Error setting Single Select option")
if nfc.nfc_device_set_property_bool(device, nfc.NP_AUTO_ISO14443_4, False) < 0:
    raise Exception("Error setting No Auto ISO14443-A jiggery pokery")
if nfc.nfc_device_set_property_bool(device, nfc.NP_HANDLE_PARITY, True) < 0:
    raise Exception("Error setting Easy Framing property")

# Select card, but waits for tag the be removed and placed again
# nt = nfc.nfc_target()
# _ = nfc.nfc_initiator_select_passive_target(device, modulations[0], None, 0, ctypes.byref(nt))
# uid = bytearray([nt.nti.nai.abtUid[i] for i in range(nt.nti.nai.szUidLen)])
# print("uid = {}".format(binascii.hexlify(uid)))

# _read_block
if nfc.nfc_device_set_property_bool(device, nfc.NP_EASY_FRAMING, True) < 0:
    raise Exception("Error setting Easy Framing property")

for block in range(45):  # 45 pages in NTAG213
    abttx = (ctypes.c_uint8 * 2)()  # command length
    abttx[0] = MC_READ
    abttx[1] = block
    abtrx = (ctypes.c_uint8 * 16)()  # 16 is the minimum
    res = nfc.nfc_initiator_transceive_bytes(device,
                                             ctypes.pointer(abttx), len(abttx),
                                             ctypes.pointer(abtrx), len(abtrx),
                                             0)
    if res < 0:
        raise IOError("Error reading data")
    #print("".join([chr(abtrx[i]) for i in range(res)]))

    print("{:3}: {}".format(block, binascii.hexlify(bytes(abtrx[:res]))))