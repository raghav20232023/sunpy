"""
This module provides a generic file reader for internal use.
"""
import re
import gzip
import pathlib

import fsspec

try:
    from . import _fits as fits
except ImportError:
    fits = None

try:
    from . import _jp2
except ImportError:
    _jp2 = None

try:
    from . import ana
except ImportError:
    ana = None

__all__ = ['read_file', 'read_file_header', 'write_file', 'detect_filetype']

# File formats supported by sunpy.io
_KNOWN_EXTENSIONS = {
    ('fts', 'fits'): 'fits',
    ('jp2', 'j2k', 'jpc', 'jpt'): 'jp2',
    ('fz', 'f0'): 'ana'
}

class Readers(dict):
    def __init__(self, *args):
        dict.__init__(self, *args)

    def __getitem__(self, key):
        val = dict.__getitem__(self, key)
        if val is None:
            raise ReaderError(
                f"The Reader sunpy.io.{key} is not available, "
                "please check that you have the required dependencies "
                "installed."
            )
        return val

# File readers supported by sunpy.io
_READERS = Readers({
    'fits': fits,
    'jp2': _jp2,
    'ana': ana
})

def get_open_file(filepath, **kwargs):
    """
    Ensures the filepath is converted to an fsspec.OpenFile object.

    Parameters
    ----------
    filepath : str, pathlib.Path, or fsspec.OpenFile
        The file path or file object to be validated.
    **kwargs : dict
        Additional keyword arguments for fsspec.open.

    Returns
    -------
    fsspec.OpenFile
        An open file object.

    Raises
    ------
    TypeError
        If the filepath is not of type str, pathlib.Path, or fsspec.OpenFile.
    """
    if isinstance(filepath, fsspec.core.OpenFile):
        return filepath

    if isinstance(filepath, (str, pathlib.Path)):
        return fsspec.open(filepath, 'rb', **kwargs)

    raise TypeError("filepath must be a string, pathlib.Path, or fsspec.OpenFile.")

def _read(open_file, function_name, filetype=None, **kwargs):
    """
    This function provides the logic paths for reading a file.

    Parameters
    ----------
    open_file : fsspec.OpenFile
        The file to be read as an open file object.
    function_name : {'read' | 'get_header'}
        The name of the function to call on the reader.
    filetype : {'jp2' | 'fits' | 'ana'}, optional
        Supported reader or extension to manually specify the filetype.
        Supported readers are ('jp2', 'fits', 'ana').
    **kwargs : dict
        Additional keyword arguments are handed to the file-specific reader.

    Returns
    -------
    pairs : list
        A list of (data, header) tuples.
    """
    with open_file as fp:
        if filetype is not None:
            return getattr(_READERS[filetype], function_name)(fp, **kwargs)

        try:
            readername = detect_filetype(fp)
            if readername in _READERS.keys():
                return getattr(_READERS[readername], function_name)(fp, **kwargs)
        except UnrecognizedFileTypeError:
            readername = None

        for extension, name in _KNOWN_EXTENSIONS.items():
            if open_file.path.endswith(extension) or filetype in extension:
                return getattr(_READERS[name], function_name)(fp, **kwargs)

    raise UnrecognizedFileTypeError("The requested filetype is not currently supported by sunpy.")

def read_file(filepath, filetype=None, **kwargs):
    """
    Automatically determine the filetype and read the file.

    Parameters
    ----------
    filepath : `str`, path-like, or fsspec.OpenFile
        The file to be read.
    filetype : `str`, optional
        Supported reader or extension to manually specify the filetype.
        Supported readers are ('jp2', 'fits', 'ana')
    memmap : `bool`, optional
        Should memory mapping be used, i.e. keep data on disk rather than in RAM.
        This is currently only supported by the FITS reader.
    **kwargs : `dict`
        All extra keyword arguments are passed to ``.read`` for the file specific reader.

    Returns
    -------
    pairs : `list`
        A list of (data, header) tuples.
    """
    open_file = get_open_file(filepath, **kwargs)
    return _read(open_file, 'read', filetype, **kwargs)

def read_file_header(filepath, filetype=None, **kwargs):
    """
    Reads the header from a given file.

    This should always return a instance of `~sunpy.io._header.FileHeader`.

    Parameters
    ----------
    filepath : str, path-like, or fsspec.OpenFile
        The file from which the header is to be read.
    filetype : str, optional
        Supported reader or extension to manually specify the filetype.
        Supported readers are ('jp2', 'fits').
    **kwargs : `dict`
        All extra keyword arguments are passed to ``.get_header`` for the file specific reader.

    Returns
    -------
    headers : `list`
        A list of headers.
    """
    open_file = get_open_file(filepath, **kwargs)
    return _read(open_file, 'get_header', filetype, **kwargs)

def write_file(fname, data, header, filetype='auto', **kwargs):
    """
    Write a file from a data & header pair using one of the defined file types.

    Parameters
    ----------
    fname : str or fsspec.OpenFile
        Filename of the file to save.
    data : numpy.ndarray
        Data to save to a fits file.
    header : collections.OrderedDict
        Meta data to save with the data.
    filetype : str, {'auto', 'fits', 'jp2'}, optional
        Filetype to save if `auto`, the filename extension will
        be detected; otherwise, specify a supported file extension.
    **kwargs : dict
        All extra keyword arguments are passed to `.write` for the file-specific reader.

    Notes
    -----
    This routine currently only supports saving a single HDU.
    """
    open_file = get_open_file(fname, **kwargs)
    if filetype == 'auto':
        filetype = pathlib.Path(open_file.path).suffix[1:]

    for extension, readername in _KNOWN_EXTENSIONS.items():
        if filetype in extension:
            return _READERS[readername].write(open_file, data, header, **kwargs)

    raise ValueError(f"The filetype provided ({filetype}) is not supported")

def detect_filetype(open_file, **kwargs):
    """
    Attempts to determine the type of file a given filepath is.

    Parameters
    ----------
    open_file : fsspec.OpenFile
        The file to inspect.
    **kwargs : dict
        Additional keyword arguments.

    Returns
    -------
    filetype : str
        The type of file.
    """
    with open_file as fp:
        line1 = fp.readline()
        line2 = fp.readline()
        # Some FITS files do not have line breaks at the end of header cards.
        fp.seek(0)
        first80 = fp.read(80)
        # First 8 bytes of netcdf4/hdf5 to determine filetype as have same sequence
        fp.seek(0)
        first_8bytes = fp.read(8)
        # First 4 bytes of CDF
        fp.seek(0)
        cdf_magic_number = fp.read(4).hex()

    # For ASDF files
    if first80.startswith(b"#ASDF"):
        return "asdf"

    # FITS
    # Checks for gzip signature.
    # If found, decompresses first few bytes and checks for FITS
    if first80[:3] == b"\x1f\x8b\x08":
        with gzip.open(open_file.path, 'rb') as fp:
            first80 = fp.read(80)

    # Check for "KEY_WORD  =" at beginning of file
    match = re.match(br"[A-Z0-9_]{0,8} *=", first80)
    if match is not None:
        return 'fits'

    # JPEG 2000
    # Checks for one of two signatures found at beginning of all JP2 files.
    # Adapted from ExifTool
    # [1] https://www.sno.phy.queensu.ca/~phil/exiftool/
    # [2] http://www.hlevkin.com/Standards/fcd15444-2.pdf
    # [3] http://www.hlevkin.com/Standards/fcd15444-1.pdf
    jp2_signatures = [b"\x00\x00\x00\x0cjP  \x0d\x0a\x87\x0a",
                      b"\x00\x00\x00\x0cjP\x1a\x1a\x0d\x0a\x87\x0a"]
    for sig in jp2_signatures:
        if line1 + line2 == sig:
            return 'jp2'

    # netcdf4 and hdf5 files
    if first_8bytes == b'\x89HDF\r\n\x1a\n':
        return 'hdf5'

    if cdf_magic_number in ['cdf30001', 'cdf26002', '0000ffff']:
        return 'cdf'

    raise UnrecognizedFileTypeError("The requested filetype is not currently supported by sunpy.")


class UnrecognizedFileTypeError(OSError):
    """
    Exception to raise when an unknown file type is encountered.
    """


class ReaderError(ImportError):
    """
    Exception to raise when a reader errors.
    """
