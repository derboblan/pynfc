#! /usr/bin/env python3

from . import pynfc as nfc
import ctypes
import binascii
import enum
import logging

class TagType(enum.Enum):
    NTAG_213 = {"user_memory_start": 4, "user_memory_end": 39}  # 4 is the first page of the user memory, 39 is the last
    NTAG_215 = {"user_memory_start": 4, "user_memory_end": 129}  # 4 is the first page of the user memory, 129 is the last
    NTAG_216 = {"user_memory_start": 4, "user_memory_end": 225}  # 4 is the first page of the user memory, 255 is the last

SET_CONNSTRING = 'You may need to $ export LIBNFC_DEFAULT_DEVICE="pn532_uart:/dev/ttyUSB0" ' \
                 'or edit /etc/nfc/libnfc.conf and set device.connstring in case of a failure'

class Commands(enum.Enum):
    MC_AUTH_A = 0x60
    MC_AUTH_B = 0x61
    MC_READ = 0x30
    MC_WRITE = 0xA0
    MC_TRANSFER = 0xB0
    MC_DECREMENT = 0xC0
    MC_INCREMENT = 0xC1
    MC_STORE = 0xC2

class NTagReadWrite(object):
    """
    Allows to read/write to an NTag 21x device.
    Tested with a Adafruit PN532 breakout board connected via serial over an FTDI cable
    """
    card_timeout = 10

    def __init__(self, logger=None):
        """Initialize a ReadWrite object
        :param logger: function to be called as logging. Can be import logging; logging.getLogger("ntag_read").info or simply the builtin print function.
        Defaults to no logging"""
        def nolog(log):
            pass
        self.log = logger if logger else nolog

        try:
            self.context = ctypes.pointer(nfc.nfc_context())
            self.log("Created NFC library context")
            nfc.nfc_init(ctypes.byref(self.context))
            self.log("Initializing NFC library")

            conn_strings = (nfc.nfc_connstring * 10)()
            devices_found = nfc.nfc_list_devices(self.context, conn_strings, 10)
            # import ipdb; ipdb.set_trace()
            self.log("{} devices found".format(devices_found))

            if not devices_found:
                IOError("No devices found. "+SET_CONNSTRING)
            else:
                self.log("Using conn_string[0] = {} to get a device. {}".format(conn_strings[0].value, SET_CONNSTRING))

            self.device = nfc.nfc_open(self.context, conn_strings[0])
            self.log("Opened device {}, initializing NFC initiator".format(self.device))
            _ = nfc.nfc_initiator_init(self.device)
            self.log("NFC initiator initialized")
        except IOError as error:
            IOError(SET_CONNSTRING)

    def setup_target(self):
        """
        Find a target if there is one and returns the target's UID
        :return: UID of the found target
        :rtype bytes
        """
        nt = nfc.nfc_target()

        mods = [(nfc.NMT_ISO14443A, nfc.NBR_106)]
        modulations = (nfc.nfc_modulation * len(mods))()
        for i in range(len(mods)):
            modulations[i].nmt = mods[i][0]
            modulations[i].nbr = mods[i][1]

        res = nfc.nfc_initiator_poll_target(self.device, modulations, len(modulations), 10, 2, ctypes.byref(nt))

        if res < 0:
            raise IOError("NFC Error whilst polling")

        uidLen = 7
        uid = bytes([nt.nti.nai.abtUid[i] for i in range(uidLen)])

        # setup device
        if nfc.nfc_device_set_property_bool(self.device, nfc.NP_ACTIVATE_CRYPTO1, True) < 0:
            raise Exception("Error setting Crypto1 enabled")
        if nfc.nfc_device_set_property_bool(self.device, nfc.NP_INFINITE_SELECT, False) < 0:
            raise Exception("Error setting Single Select option")
        if nfc.nfc_device_set_property_bool(self.device, nfc.NP_AUTO_ISO14443_4, False) < 0:
            raise Exception("Error setting No Auto ISO14443-A jiggery pokery")
        if nfc.nfc_device_set_property_bool(self.device, nfc.NP_HANDLE_PARITY, True) < 0:
            raise Exception("Error setting Easy Framing property")

        return uid

    def set_easy_framing(self, enable=True):
        if nfc.nfc_device_set_property_bool(self.device, nfc.NP_EASY_FRAMING, enable) < 0:
            raise Exception("Error setting Easy Framing property")

    def transceive_bytes(self, transmission, receive_length):
        """
        Send the bytes in the send
        :param device: The device *via* which to transmit the bytes
        :param transmission: Data or command to send:
        :type transmission bytes
        :param receive_length: how many bytes to receive?
        :type receive_length int
        :return: whatever was received back. Should be nothing actually
        """

        abttx = (ctypes.c_uint8 * len(transmission))()  # command length
        for index, byte in enumerate(transmission):
            abttx[index] = byte

        abtrx = (ctypes.c_uint8 * receive_length)()  # 16 is the minimum
        res = nfc.nfc_initiator_transceive_bytes(self.device,
                                                 ctypes.pointer(abttx), len(abttx),
                                                 ctypes.pointer(abtrx), len(abtrx),
                                                 0)
        if res < 0:
            raise IOError("Error reading data")

        data = bytes(abtrx[:res])
        return data

    def read_page(self, page):
        """Read the bytes at the given page"""
        received_data = self.transceive_bytes(bytes([int(Commands.MC_READ.value), page]), 16)
        data = received_data[:4]  # Only the first 4 bytes as a page is 4 bytes
        return data

    def read_user_memory(self, tag_type):
        """Read the complete user memory, ie. the actual content of the tag.
        Configuration bytes surrounding the user memory is omitted"""
        start = tag_type.value['user_memory_start']
        end = tag_type.value['user_memory_end'] + 1  # + 1 because the Python range generator excluded the last value

        user_memory = []
        for page in range(start, end):
            user_memory += list(self.read_page(page))

        return bytes(user_memory)

    def write_block(self, block, data):
        """Writes a block of data to an NTag
        Raises an exception on error
        """
        self.set_easy_framing(True)

        if len(data) > 16:
            raise ValueError( "Data value to be written cannot be more than 16 bytes.")

        abttx = bytearray(18) # 18 is 1 byte for command, 1 byte for block/page address, 16 for actual data
        abttx[0] = int(Commands.MC_WRITE.value)
        abttx[1] = block
        for index, byte in enumerate(data):
            abttx[index + 2] = byte

        recv = self.transceive_bytes(bytes(abttx), 250)
        return recv

    def write_page(self, page, data, debug=False):
        if debug:
            print("Write page {:3}: {}".format(page, data))
        if len(data) > 4:
            raise ValueError( "Data value to be written cannot be more than 4 bytes.")
        return self.write_block(page, data)

    def write_user_memory(self, data, tag_type, debug=False):
        """Read the complete user memory, ie. the actual content of the tag.
        Configuration bytes surrounding the user memory are omitted, given the correct tag type.
        Otherwise, we cannot know where user memory start and ends"""
        start = tag_type.value['user_memory_start']
        end = tag_type.value['user_memory_end'] + 1  # + 1 because the Python range generator excluded the last value

        page_contents = [data[i:i+4] for i in range(0, len(data), 4)]
        self.log("Writing {} pages".format(len(page_contents)))
        for page, content in zip(range(start, end), page_contents):
            self.write_page(page, content, debug)

    def close(self):
        nfc.nfc_close(self.device)
        nfc.nfc_exit(self.context)

if __name__ == "__main__":
    logger = print  # logging.getLogger("ntag_read").info

    read_writer= NTagReadWrite(logger)

    uid = read_writer.setup_target()
    print("uid = {}".format(binascii.hexlify(uid)))

    read_writer.set_easy_framing()

    # read_writer.write_page(41, bytes([0b0000000, 0b00000000, 0b00000000, 0xFF]))  # Disable ascii UID mirroring
    # read_writer.write_user_memory(self.device, bytes([0x00] * 4 * 100), TagType.NTAG_213.value)
    # read_writer.write_page(self.device, 4, bytes([0xff,0xff,0xff,0xff]))
    # read_writer.write_page(self.device, 5, bytes([0xff,0xff,0xff,0xff]))
    # read_writer.write_page(self.device, 6, bytes([0xff,0xff,0xff,0xff]))

    # print("-" * 10)

    print(read_writer.read_user_memory(tag_type=TagType.NTAG_213))

    read_writer.close()
