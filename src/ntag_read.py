#! /usr/bin/env python3

from . import nfc
import ctypes
import binascii

ntag_213 = {"user_memory_start":4, "user_memory_end":39}  # 4 is the first page of the user memory, 39 is the last
ntag_215 = {"user_memory_start":4, "user_memory_end":129}  # 4 is the first page of the user memory, 39 is the last
ntag_216 = {"user_memory_start":4, "user_memory_end":225}  # 4 is the first page of the user memory, 39 is the last

MC_AUTH_A = 0x60
MC_AUTH_B = 0x61
MC_READ = 0x30
MC_WRITE = 0xA0
MC_TRANSFER = 0xB0
MC_DECREMENT = 0xC0
MC_INCREMENT = 0xC1
MC_STORE = 0xC2
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
# print("uid = {}".format(uid))

def set_easy_framing(enable=True):
    if nfc.nfc_device_set_property_bool(device, nfc.NP_EASY_FRAMING, enable) < 0:
        raise Exception("Error setting Easy Framing property")

# _read_block
set_easy_framing(True)

def tranceive_bytes(device, transmission, receive_length):
    """
    Send the bytes in the send
    :param device: The device *via* which to transmit the bytes
    :param transmission: Data or command to send:
    :type transmission bytes
    :param receive_length: how many bytes to receive?
    :type receive_length int
    :return:
    """
    abttx = (ctypes.c_uint8 * len(transmission))()  # command length
    for index, byte in enumerate(transmission):
        abttx[index] = byte

    abtrx = (ctypes.c_uint8 * receive_length)()  # 16 is the minimum
    res = nfc.nfc_initiator_transceive_bytes(device,
                                             ctypes.pointer(abttx), len(abttx),
                                             ctypes.pointer(abtrx), len(abtrx),
                                             0)
    if res < 0:
        raise IOError("Error reading data")

    data = bytes(abtrx[:res])
    return data

def read_page(device, page):
    recv_data = tranceive_bytes(device, bytes([MC_READ, page]), 16)
    data = recv_data[:4]  # Only the first 4 bytes as a page is 4 bytes
    return data

def read_simple(pages):
    accumulated = []

    for page in range(pages):  # 45 pages in NTAG213
        data = read_page(device, page)
        print("Read page  {:3}: {}".format(page, data))
        accumulated += list(data)

    return bytes(accumulated)

# read_simple(45)

def read_print(device, page, length=4):
    data = tranceive_bytes(device, bytes([MC_READ, page]), 16)
    if length:
        data = data[:length] # Only the first $length bytes
    print("Read page  {:3}: {}".format(page, data))

def write_block(device, block, data):
    """Writes a block of data to an NTag
    Raises an exception on error
    """
    set_easy_framing(True)

    if len(data) > 16:
        raise ValueError( "Data value to be written cannot be more than 16 bytes.")

    abttx = bytearray(18) # 18 is 1 byte for command, 1 byte for block/page address, 16 for actual data
    abttx[0] = MC_WRITE
    abttx[1] = block
    for index, byte in enumerate(data):
    #     abttx[i + 2] = ord((data + "\x00" * (16 - len(data)))[i])
        abttx[index + 2] = byte
    # abtrx = (ctypes.c_uint8 * 250)()
    # return nfc.nfc_initiator_transceive_bytes(self.__device, ctypes.pointer(abttx), len(abttx),
    #                                           ctypes.pointer(abtrx), len(abtrx), 0)

    recv = tranceive_bytes(device, bytes(abttx), 250)
    return recv

def write_page(device, page, data, debug=False):
    if debug:
        print("Write page {:3}: {}".format(page, data))
    if len(data) > 4:
        raise ValueError( "Data value to be written cannot be more than 4 bytes.")
    return write_block(device, page, data)

# write_page(device, 4, bytes([0xff,0xff,0xff,0xff]))
# write_page(device, 5, bytes([0xff,0xff,0xff,0xff]))
# write_page(device, 6, bytes([0xff,0xff,0xff,0xff]))

def write_user_memory(device, data, tagtype):
    start = tagtype['user_memory_start']
    end = tagtype['user_memory_end'] + 1  # + 1 because the Python range generator excluded the last value

    page_contents = [data[i:i+4] for i in range(0, len(data), 4)]
    print("Writing {} pages".format(len(page_contents)))
    for page, content in zip(range(start, end), page_contents):
        write_page(device, page, content, debug=True)

def read_user_memory(device, tagtype):
    start = tagtype['user_memory_start']
    end = tagtype['user_memory_end'] + 1  # + 1 because the Python range generator excluded the last value

    user_memory = []
    for page in range(start, end):
        user_memory += list(read_page(device, page))

    return bytes(user_memory)


write_page(device, 41, bytes([0b0000000, 0b00000000, 0b00000000, 0xFF]))  # Disable ascii UID mirroring 
# write_user_memory(device, bytes([0x00] * 4 * 100), ntag_213)

print("-" * 10)

print(read_user_memory(device, ntag_213))

nfc.nfc_close(device)

nfc.nfc_exit(context)