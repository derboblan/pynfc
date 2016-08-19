#! /usr/bin/env python3

from . import pynfc as nfc
import ctypes
import binascii
import enum
import logging

def bin(i):
    return "0b{0:08b}".format(i)

class TagType(enum.Enum):
    NTAG_213 = {"user_memory_start": 4, "user_memory_end": 39}  # 4 is the first page of the user memory, 39 is the last
    NTAG_215 = {"user_memory_start": 4, "user_memory_end": 129}  # 4 is the first page of the user memory, 129 is the last
    NTAG_216 = {"user_memory_start": 4, "user_memory_end": 225}  # 4 is the first page of the user memory, 255 is the last

capability_byte_type_map = {0x12: TagType.NTAG_213,
                            0x3e: TagType.NTAG_215,
                            0x6D: TagType.NTAG_216}


class UnknownTagTypeException(Exception):
    def __init__(self, message, capability_byte):
        super(UnknownTagTypeException, self).__init__(message)

        self.capability_byte = capability_byte


SET_CONNSTRING = 'You may need to $ export LIBNFC_DEFAULT_DEVICE="pn532_uart:/dev/ttyUSB0" ' \
                 'or edit /etc/nfc/libnfc.conf and set device.connstring in case of a failure'

class Commands(enum.Enum):
    MC_GET_VERSION = 0x60
    MC_READ = 0x30
    MC_FAST_READ = 0x3a
    MC_WRITE = 0xA2
    MC_COMPATIBILITY_WRITE = 0xA0
    MC_READ_CNT = 0x39
    MC_PWD_AUTH = 0x1b
    MC_READ_SIG = 0x3c


class NTagInfo(object):
    BYTES_PER_PAGE = 4


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

        mods = [(nfc.NMT_ISO14443A, nfc.NBR_106)]
        self.modulations = (nfc.nfc_modulation * len(mods))()
        for i in range(len(mods)):
            self.modulations[i].nmt = mods[i][0]
            self.modulations[i].nbr = mods[i][1]

        self.open()

    def open(self):
        """Open a connection with an NTag. Initializes pynfc context, the device.
        Call this after a close()"""
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
                IOError("No devices found. " + SET_CONNSTRING)
            else:
                self.log("Using conn_string[0] = {} to get a device. {}".format(conn_strings[0].value, SET_CONNSTRING))

            self.device = nfc.nfc_open(self.context, conn_strings[0])
            self.log("Opened device {}, initializing NFC initiator".format(self.device))
            _ = nfc.nfc_initiator_init(self.device)
            self.log("NFC initiator initialized")
        except IOError as error:
            IOError(SET_CONNSTRING)

    def list_targets(self, max_targets=10):
        """
        List the targets detected by the device
        :param max_targets: amount of targets to maximally find
        :return: list of bytes with the found UIDs
        """
        targets = (nfc.nfc_target * max_targets)()
        count = nfc.nfc_initiator_list_passive_targets(self.device, self.modulations[0], targets, len(targets))

        uids = []
        for index in range(count):
            uidLen = 7
            uid = bytes([targets[index].nti.nai.abtUid[i] for i in range(uidLen)])
            uids += [uid]

        return uids

    def setup_target(self):
        """
        Find a target if there is one and returns the target's UID
        :return: UID of the found target
        :rtype bytes
        """
        nt = nfc.nfc_target()

        res = nfc.nfc_initiator_poll_target(self.device, self.modulations, len(self.modulations), 10, 2, ctypes.byref(nt))

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
        data = received_data[:NTagInfo.BYTES_PER_PAGE]  # Only the first 4 bytes as a page is 4 bytes
        return data

    def determine_tag_type(self):
        """
        According to the NTAG213/215/216 specification, the Capability Container byte 2 contains the memory size of the tag
        This is written during tag production. The capability Container is on page 3
        The exact definitions are stated in table 4 of the datasheet:

        Table 4. NDEF memory size
        IC      | Value in byte 2 | NDEF memory size
        --------+-----------------+-----------------
        NTAG213 | 12h             | 144 byte
        NTAG215 | 3Eh             | 496 byte
        NTAG216 | 6Dh             | 872 byte
        """
        uid = self.setup_target()

        self.set_easy_framing()

        capability_container = self.read_page(3)
        capability_byte = capability_container[2]

        try:
            tag_type = capability_byte_type_map[capability_byte]

            return tag_type, uid
        except KeyError as key_error:
            raise UnknownTagTypeException("Tag has capability byte value {byte}, "
                                          "which is unknown. Known keys are {keys}".format(byte=capability_byte,
                                                                                           keys=list(capability_byte_type_map.keys())),
                                          capability_byte)

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
        abttx[0] = int(Commands.MC_COMPATIBILITY_WRITE.value)
        abttx[1] = block
        for index, byte in enumerate(data):
            abttx[index + 2] = byte

        recv = self.transceive_bytes(bytes(abttx), 250)
        return recv

    def write_page(self, page, data, debug=False):
        if debug:
            print("Write page {:3}: {}".format(page, data))
        if len(data) > NTagInfo.BYTES_PER_PAGE:
            raise ValueError( "Data value to be written cannot be more than 4 bytes.")
        return self.write_block(page, data)

    def write_user_memory(self, data, tag_type, debug=False):
        """Read the complete user memory, ie. the actual content of the tag.
        Configuration bytes surrounding the user memory are omitted, given the correct tag type.
        Otherwise, we cannot know where user memory start and ends"""
        start = tag_type.value['user_memory_start']
        end = tag_type.value['user_memory_end'] + 1  # + 1 because the Python range generator excluded the last value
        mem_size = (end-start)

        page_contents = [data[i:i+NTagInfo.BYTES_PER_PAGE] for i in range(0, len(data), NTagInfo.BYTES_PER_PAGE)]
        content_size = len(page_contents)

        if content_size > mem_size:
            raise ValueError("{type} user memory ({mem_size} 4-byte pages) too small for content ({content_size} 4-byte pages)".
                             format(type=tag_type, mem_size=mem_size, content_size=content_size))

        self.log("Writing {} pages".format(len(page_contents)))
        for page, content in zip(range(start, end), page_contents):
            self.write_page(page, content, debug)

    def authenticate(self, password, acknowledge=b'\x00\x00'):
        """After issuing this command correctly, the tag goes into the Authenticated-state,
        during which the protected bytes can be written
        :param password the 4-byte password with which the tag is protected
        :type password bytes
        :param acknowledge the 2 Password ACKnowledge bytes. If these are received, the password was correct
        :returns whether the password was correct or not
        :rtype bool"""

        # With easy framing enabled, there will be an "Application level error".
        # With easy-framing disabled, 'Chip error: "Timeout" (01), returned error: "RF Transmission Error" (-20))'
        # The PWD_AUTH command can have a timeout of max. 5ms.
        # With the timeout in tranceive_bytes set to:
        #    0ms: "Chip error: "Timeout" (01), returned error: "RF Transmission Error" (-20))",
        #    1ms, "libnfc.bus.uart	Timeout!" even before authenticating, its simply too short
        #    5ms, "libnfc.bus.uart	Timeout!" even before authenticating, its simply too short
        #   10ms, "libnfc.bus.uart	Timeout!"
        #  100ms: "Chip error: "Timeout" (01), returned error: "RF Transmission Error" (-20))",
        #         Which would indicate the wait for the UART is long enough (also the default).
        # But, this sets the timeout for the communication between host and PN532, not between PN532 and NTag.
        # On the other hand, this 5ms is the same for reading, to there should not be a need to set a different timeout
        # for PN532-to-NTag communication.
        self.set_easy_framing(False)

        if len(password) != 4:
            raise ValueError( "Password must be 4 bytes")

        if len(acknowledge) != 2:
            raise ValueError( "Password ACKnowledge must be 2 bytes")

        cmd = int(Commands.MC_PWD_AUTH.value)

        ctypes_key = (ctypes.c_uint8 * len(password))()  # command length
        for index, byte in enumerate(password):
            ctypes_key[index] = byte

        crc = (ctypes.c_uint8 * 2)()

        nfc.iso14443a_crc(ctypes.pointer(ctypes_key), len(password), ctypes.pointer(crc))

        abttx = bytes([cmd]) + password

        recv = self.transceive_bytes(bytes(abttx), 16)

        return recv == acknowledge

    def enable_uid_mirror(self, tag_type, page, byte_in_page):
        """
        An NTAG 21x has the option to mirror its UID to a place in the user memory.
        This can be useful for signatures, which can then sign over something unique tied to the tag.

        The mirror configuration page consists of 4 bytes:
        - CFG0: MIRROR, rfui, MIRROR_PAGE, AUTH0

        The MIRROR-byte consists of some bitfields:
        - 7,6: MIRROR_CONF: Set to 01 for UID ASCII Mirror
        - 5,4: MIRROR_BYTE: The 2 bits define the byte position within the page defined by the MIRROR_PAGE byte (beginning of ASCII mirror)
        - 3  : RFUI
        - 2  : STRG_MOD_EN: STRG MOD_EN defines the modulation mode. 0 disables, 1 enables
        - 1,0: RFUI

        The AUTH0-byte defines the page address from which the password verification is required.
        This is set through the set_password-method.

        :param tag_type: Which type of tag are we dealing with? Used to figure out where the config pages are
        :param page: On which page must the UID be mirrored?
        :type page int
        :param byte_in_page: On which byte in that page must the UID be mirrored.
         :type byte_in_page int
        :return:
        """
        cfg0_page = tag_type.value['user_memory_end'] + 2
        cfg0_orig = self.read_page(cfg0_page)


        mirror = 0b01000000
        mirror |= (byte_in_page) << 4

        #       MIRROR  rfui        MIRROR_PAGE AUTH0
        cfg0 = [mirror, 0b00000000, page,       cfg0_orig[3]]

        self.write_page(cfg0_page, cfg0)

    def check_uid_mirror(self, tag_type):
        """Return to which page and byte_in_page the UID mirroring is configured.
        If it is not enabled, return None

        :param tag_type: Which type of tag are we dealing with? Used to figure out where the config pages are
        :returns tuple (mirror_page, byte_in_page) in case UID mirroring is enabled, None if not enabled."""
        cfg0_page = tag_type.value['user_memory_end'] + 2

        config_page = self.read_page(cfg0_page)
        mirror, _, mirror_page, auth0 = config_page

        mirroring_enabled = mirror & 0b01000000 > 0

        mirror_byte_mask = 0b00110000
        byte_in_page = (mirror & mirror_byte_mask) >> 4

        if mirroring_enabled:
            return mirror_page, byte_in_page
        else:
            return None


    def set_password(self, tag_type, password=b'\xff\xff\xff\xff', acknowledge=b'\x00\x00', max_attempts=None,
                     also_read=False, auth_from=0xFF, lock_config=False, enable_counter=False, protect_counter=False):
        """

        The AUTH0-byte (byte 3 on page 0x29/0x83/0xE3 for resp Ntag 213,215,216) defines the page address from which the password verification is required.
        0xFF effectively disables it

        The ACCESS-byte (byte 0 on page 0x2A/0x84/0xE4 for resp Ntag 213,215,216) consists of some bitfields:
        - 7: PROT: 0 = write access is password protected, 1 = read and write are is password protected
        - 6: CGFLCK: Write locking bit for the user configuration
        - 5: RFUI (reserved for future use)
        - 4: NFC_CNT_EN: NFC counter configuration
        - 3: NFC_CNT_PWD_PROT: NFC counter password protection
        - 2,1,0: AUTHLIM: Limitation of negative password verification attempts

        The PACK-bytes in the PACK-page have a 16-bit password acknowledge used during the password verification process

        Password protected is needed to prevent the user from accidentally writing the tag with a NFC enabled phone.
        With a password, writing is still possible but needs to be deliberate.
        The password must thus protect writing only, but for the whole tag so the start page in AUTH0 must be 0
        There's no need to lock the user configuration (i.e. these bytes generated here), so CGFLCK=0
        """
        cfg0_page = tag_type.value['user_memory_end'] + 2
        cfg1_page = cfg0_page + 1
        pwd_page = cfg1_page + 1
        pack_page = pwd_page + 1

        cfg0 = bytearray(self.read_page(cfg0_page))
        # [MIRROR, rfui, MIRROR_PAGE, AUTH0], so we overwrite
        cfg0[3] = auth_from

        access = 0b00000000

        prot = 0b10000000 if also_read else 0b00000000
        access |= prot

        cfglck = 0b01000000 if lock_config else 0b00000000
        access |= cfglck

        nfc_cnt_en = 0b00010000 if enable_counter else 0b00000000
        access |= nfc_cnt_en

        nfc_cnt_pwd_prot = 0b00001000 if protect_counter else 0b00000000
        access |= nfc_cnt_pwd_prot

        if max_attempts and max_attempts > 7:
            raise ValueError("Max_attempts can be set to 7 at most (0b111) ")

        authlim = max_attempts if max_attempts != None else 0b000 # 3 bit field, at the end of  the byte so no shifting is needed
        access |= authlim

        #       ACCESS,     rfui,       rfui,       rfui
        cfg1 = [access, 0b00000000, 0b00000000, 0b00000000]

        # Password
        pwd = password

        #      [PACK, PACK,         rfui,       rfui
        pack = acknowledge + bytes([0b00000000, 0b00000000])  # unused

        self.write_page(pack_page, pack)
        self.write_page(pwd_page, pwd)
        self.write_page(cfg1_page, cfg1)
        self.write_page(cfg0_page, cfg0)

    def close(self):
        """Close connection to the target NTag and de-initialize the pynfc context.
        After a failed read/write due to password protection, call close(), then open() and then do the authenticate() call"""
        nfc.nfc_idle(self.device)
        nfc.nfc_close(self.device)
        nfc.nfc_exit(self.context)


if __name__ == "__main__":
    logger = print  # logging.getLogger("ntag_read").info

    read_writer = NTagReadWrite(logger)

    uids = read_writer.list_targets()
    if len(uids) > 1:
        print("Found {count} uids: {uids}. Please remove all but one from the device".format(count=len(uids), uids=uids))
        exit(-1)

    tt = TagType.NTAG_216
    testpage = 200  # Must be available on the chosen tag type.

    password = bytes([1, 2, 3, 4])
    ack = bytes([0xaa, 0xaa])


    uid = read_writer.setup_target()
    print("uid = {}".format(binascii.hexlify(uid)))

    read_writer.set_easy_framing()



    # Below, we'll test and demonstrate the behavior of password protection against writing
    # The tag is supposed to start with no password protection configured, as the factory default is.
    # This is also how the tag should end, eventually
    #
    # 1: The test starts by writing to a page, which should be OK because there is not password protection.
    # 2: This is verified by reading the data again
    #
    # 3: Then, we set a password, after which we close the connection so make sure we start over with the tag in its idle state
    # 3a: Check that we can still read
    #
    # 4: Without authenticating with the password, we try writing again. This should fail, as we are not authenticated
    # 5: We verify that the write was unsuccessful: the page should still have its old content
    #
    # 6: We authenticate ourselves
    #
    # 7: And try to write again, which should be allowed since we are now authenticated
    # 8: Again, this is verified
    #
    # 9: Lastly, we clear the password and the protection to their default states, so the test is repeatable.

    # 1
    try:
        read_writer.write_page(testpage, bytes([0xff,0xff,0xff,0xff])) # With no password set, this page is writable
        print("   OK 1: Can write page when no password set")
    except OSError as e:
        print("ERROR 1: Could not write test page: {err}".format(err=e))
        exit()

    # 2
    try:
        current_test_content = read_writer.read_page(testpage)
        if current_test_content != bytes([0xff,0xff,0xff,0xff]):
            print("ERROR: The test page was not written")
        print("   OK 2: Can read page when no password set")
    except OSError as e:
        print("ERROR 2: Could not read test page: {err}".format(err=e))
        exit()

    # 3
    try:
        read_writer.set_password(tt, password=password, acknowledge=ack, auth_from=testpage)
        print("   OK 3: password protection set")
    except OSError as e:
        print("ERROR 3: Could not set a password")

    # Close and reopen this connection, so we definitely need to re-authenticate
    read_writer.close()

    read_writer.open()

    read_writer.setup_target()

    # 3a
    try:
        current_test_content = read_writer.read_page(testpage)
        if current_test_content != bytes([0xff, 0xff, 0xff, 0xff]):
            print("ERROR 3b: The test page was changed after setting password but before writing")
        print("   OK 3b: Can read page after setting password")

    except OSError as e:
        print("ERROR 3b: Could not read test page after setting password: {err}".format(err=e))
        exit()

    # 4
    try:
        read_writer.write_page(testpage, bytes([0x00,0x00,0x00,0x00])) # After setting the password protection, the page cannot be written anymore
    except OSError as e:
        print("   OK 4: Could (correctly) not write test page, because we just set a password and now this page is password locked: {err}".format(err=e))

    # 5
    try:
        current_test_content = read_writer.read_page(testpage)
        if current_test_content != bytes([0xff, 0xff, 0xff, 0xff]):
            print("ERROR 5: The test page was changed while password protected and not authenticated")
            if current_test_content == bytes([0x00,0x00,0x00,0x00]):
                print("\tThe test page was overwritten with what we wrote without authentication")
        else:
            print("   OK 5: the test page could not be written after a password was required and not authenticated")
    except OSError as e:
        print("ERROR 5: Could not read test page: {err}".format(err=e))
        # exit()

    # Close and reopen this connection, so we definitely need to re-authenticate
    read_writer.close()

    read_writer.open()

    read_writer.setup_target()

    # 6
    try:
        read_writer.authenticate(password=password, acknowledge=ack)
        print("   OK 6: authentication successful")
    except OSError as e:
        print("ERROR 6: Could not authenticate: {err}".format(err=e))

    # 7
    try:
        read_writer.write_page(testpage, bytes([0xaa, 0xaa, 0xaa, 0xaa]))  # After authenticating ourselves, its writeable again
        print("   OK 7: write after authentication successful")
    except OSError as e:
        print("ERROR 7: Could not write test page: {err}".format(err=e))

    # 8
    try:
        current_test_content = read_writer.read_page(testpage)
        if current_test_content != bytes([0xaa, 0xaa, 0xaa, 0xaa]):
            print("ERROR 8: The test page was not written after authentication")
        print("   OK 8: read after writing with authentication successful")
    except OSError as e:
        print("ERROR 8: Could not read test page: {err}".format(err=e))
        exit()

    # 9
    try:
        read_writer.set_password(tt)  # Default arguments set to default state, clearing the password
        print("   OK 9: password cleared")
    except OSError as e:
        print("ERROR 9: Could not clear password")

    # import ipdb; ipdb.set_trace()
    read_writer.close()
    del read_writer

    print("Test completed")
