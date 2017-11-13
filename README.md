# Pynfc - Python bindings for libnfc

## Requirements

* libnfc >= 1.7.0
* python >= 2.6 < 3.5 (tested with 2.7 and 3.5)

## Building

The bindings are constructed at runtime using ctypes.  Just ensure the library is correctly installed.

## Instalation

```
sudo apt-get install -y libnfc5 debhelper python3-all python3-setuptools
git clone git@github.com:ppatrik/pynfc.git
cd pynfc
python3 setup.py install
```

Now you can import pynfc in your projects

```py
import pynfc as nfc;
```

## Examples

### Mifareauth

There is an example program included for conducting simple mifare authentication:

```bash
> python mifareauth.py
Example output (bulk of the raw hex excised for space):

Connect to reader: True
Initialize Reader: True
Field Down: True
CRC False: True
Parity True: True
Field Up: True
key: A0A1A2A3A4A5
...
T -> R: A2 7F 33 EE
TR == Next(TN, 96): True
R -> T: 8F A4 FA D1
T -> R: CA 9E 73 93
```

This indicates that it successfully authenticated to the requested block.

### NTags
```bash
python -m pynfc.ntag_read
```

This will test whether can do password protection and remove the password all together in the end.


## Documentation

The pynfc bindings should offer an intuitive, yet pythonic way of calling the standard libnfc API.

This version of pynfc does not yet do that, it is currently just a duplicate of the C library calls without any strong python integration.

As much as possible all libnfc commands are mirrored in the created nfc object.

Please note whilst this does implement the full range of features found in libnfc, their use in python may be difficult or tricky to use.
Pynfc requires much more development and time dedicated to it, before it will be useful as a production tool.

The NTagReadWrite class offers a more Pythonic and high-level interface, geared towards NXP NTags 213, 215 and 216 but should be extendable/generalized to other tag types as well. 
