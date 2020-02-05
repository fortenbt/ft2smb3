#!/usr/bin/env python3
import re
import sys
from binascii import hexlify
from itertools import zip_longest

NOTES = ['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-']

NOISE_NOTE_BYTES = {
    '0-': 2,
    '1-': 2,
    '2-': 2,
    '3-': 2,
    '4-': 2,
    '5-': 2,
    '6-': 2,
    '7-': 2,
    '8-': 2,
    '9-': 2,
    'A-': 2,
    'B-': 2,
    # Note that to support other songs, we list the above noise
    # bytes 0 through B and we just use the C/D noise table entry.
    'C-': 2,
    'D-': 2,
    'E-': 3,
    'F-': 3,
}

PATTERN_INT = lambda t: int(t.split()[1], 16)
NCHANNELS_INT = lambda t: len(t.split(':')[1].split())
ROW_INT = lambda t: int(t.split(':')[0].split()[1], 16)
ROWS_PER_PATTERN_INT = lambda t: int(t.split()[1])

def usage(name):
    return 'Usage: {} <FAMITRACKER EXPORTED TEXT FILE>'.format(name)

class SMB3Format(object):
    @classmethod
    def pretty_array(self, arr):
        s = ''
        for i, b in enumerate(arr):
            if i % 16 == 0:
                s += '\n\t.byte '
            if i % 16 == 15 or i == len(arr)-1:
                s += '${:02X}'.format(b)
            else:
                s += '${:02X}, '.format(b)
        return s




class FTSong(object):
    # Famitracker stores song data in columns in the following order
    CHANNELS = [
        'sq1',      # index 0
        'sq2',      # index 1
        'tri',      # index 2
        'nse',      # index 3
        'dpcm',     # index 4
        # TODO: mmc5 channels
    ]

    # SMB3's format stores the song segment as a concatenation of the channel buffers
    # in the following order.
    SEGMENT_DATA_CHANNELS = [
        'sq2',
        'sq1',
        'tri',
        'nse',
        'dpcm',
        # TODO: mmc5 channels
    ]

class FTSegment(object):
    '''Contains all Channels from a parsed text file

    Attributes:
        total_rows (int): The total number of rows in the song
        tcontents (string): The complete text contents, as-is from the file (from .read())
        rows_per_pattern (int): The number of rows per pattern
        nchannels (int): The number of channels in this song
        channels (dict): key = one of CHANNELS string
                         value = FTChannel object

    '''
    @classmethod
    def parse_channels_line(cls, line):
        '''Split a song's ROW line into a list containing each channel's column'''
        return line.split(':')[1:]

    def __init__(self, fpath):
        self.channels = {}
        self.total_rows = 0
        self.rest_array = []

        with open(fpath, 'r') as f:
            self.tcontents = f.read()

        self._init_settings()

        for i in range(self.nchannels):
            self.channels[FTSong.CHANNELS[i]] = FTChannel(FTSong.CHANNELS[i])

        npatterns = -1
        tlines = self.tcontents.splitlines()
        for l in tlines:
            if l.startswith('PATTERN'):
                npatterns += 1
                n = PATTERN_INT(l)
                if npatterns != n:
                    raise Exception('Found a pattern out-of-order. Expected 0x{:x}, found 0x{:x}'.format(npatterns, n))
                continue
            if l.startswith('ROW'):
                row = ROW_INT(l)
                if npatterns*self.rows_per_pattern + row != self.total_rows:
                    raise Exception('Found a row out-of-order. Expected total_rows 0x{:x}, found PATTERN {:02X}: ROW {:02X}'.format(self.total_rows, npatterns, row))
                self.total_rows += 1
                if not self._parse_row(l):
                    break
                continue

        self._create_channel_buffers()

    def dump_info(self):
        '''Prints the song data in individuals channels'''
        s = 'Rests array:'
        s += SMB3Format.pretty_array(self.rest_array)
        s += '\n\n'

        for channame, chanobj in self.channels.items():
            s += '{} channel:'.format(channame)
            s += SMB3Format.pretty_array(chanobj.buffer)
            s += '\n\n'

        print(s)

    def smb3_format(self):
        '''Returns a string in the format that is used in the assembly'''
        s = 'Rests array:'
        s += SMB3Format.pretty_array(self.rest_array)
        s += '\n\n'

        segdata = bytearray()
        for c in FTSong.SEGMENT_DATA_CHANNELS:
            segdata += self.channels[c].buffer

        sq2l = len(self.channels['sq2'].buffer)
        sq1l = len(self.channels['sq1'].buffer)
        tril = len(self.channels['tri'].buffer)
        nsel = len(self.channels['nse'].buffer)
        dpcml = len(self.channels['dpcm'].buffer)
        sq1off = sq2l if sq1l > 0 else 0
        trioff = sq2l+sq1l if tril > 0 else 0
        nseoff = sq2l+sq1l+tril if nsel > 0 else 0
        dpcmoff = sq2l+sq1l+tril+nsel if dpcml > 0 else 0
        s += 'Segment header offsets:\n'
        s += '    tri, sq1, nse, dpcm\n'
        s += '    ${:02X}, ${:02X}, ${:02X}, ${:02X}\n\n'.format(trioff, sq1off, nseoff, dpcmoff)

        s += 'Segment data:'
        s += SMB3Format.pretty_array(segdata)
        s += '\n\n'

        return s

    def _create_channel_buffers(self):
        # Set all the note lengths
        for chanobj in self.channels.values():
            chanobj.set_note_lengths(self.total_rows, self.rest_array)

        # Create the channel bytes
        for chanobj in self.channels.values():
            chanobj.create_buffer(self.rest_array)

        #print(''.join('${:02X}, '.format(b) for b in self.channels['sq1'].buffer))


    def _parse_row(self, line):
        '''Parse a line beginning with ROW XX. Each individual channel
        is parsed by the associated FTChannel object.

        Args:
            line (str): The text line to parse.

        Returns:
            True if the row was parsed.
            False if it was found to be the last line.

        '''
        #
        if 'C00' in line:
            return False

        chan_text_list = FTSong.parse_channels_line(line)
        for chanobj,chantext in zip(self.channels.values(), chan_text_list):
            chanobj.parse_chan_text(self.total_rows, chantext)
        return True

    def _init_settings(self):
        '''Parses out "global" settings for a song so that we don't have to
        conditionally check for these things on every line during parsing.

        Args:
            None

        '''
        # TODO: DPCMDEF to get DPCM indices

        start, end = re.search('^TRACK .*?$', self.tcontents, re.MULTILINE).span()
        self.rows_per_pattern = ROWS_PER_PATTERN_INT(self.tcontents[start: end])

        start, end = re.search('^COLUMNS .*?$', self.tcontents, re.MULTILINE).span()
        self.nchannels = NCHANNELS_INT(self.tcontents[start: end])
        if self.nchannels > len(FTSong.CHANNELS):
            print('This program currently only supports the following channels, where more channels were found in this song.')
            for c in FTSong.CHANNELS:
                print('    {}'.format(c))
            self.nchannels = len(FTSong.CHANNELS)


class FTChannel(object):
    '''Contains all notes from a single channel

    Attributes:
        wavetype (str): The channel's wavetype, one of: 'sq1', 'sq2', 'tri',
                        'nse', or 'dpcm'
        notes (list): A list of FTNote objects representing all the notes
                      that make up this channel's music.

    '''

    def __init__(self, wavetype):
        self.wavetype = wavetype
        self.notes = []
        self.buffer = bytearray()

    @classmethod
    def get_note_field(cls, chan_text):
        '''Returns the note field (e.g. 'E-' from ' E-3 00 F P7D V01 ... ')'''
        return chan_text.split()[0][:-1]

    @classmethod
    def get_octave_field(cls, chan_text):
        '''Returns the octave field (e.g. '3' from ' E-3 00 F P7D V01 ... ')'''
        return chan_text.split()[0][-1]

    @classmethod
    def get_volume_field(cls, chan_text):
        '''Returns the volume field (eg 'F' from ' E-3 00 F P7D V01 ... ')'''
        return chan_text.split()[2]

    # Possible optimization method for doubled lengths?
    # This probably won't work, because doubling a single note probably sounds bad.
    # Alas, I'll leave it here in case we want to revisit this.
    def _optimize_buffer(self):
        optbuffer = bytearray()
        i = 0
        last_len = 0
        while i < len(self.buffer):
            b = self.buffer[i]

            # If this is just a note byte, keep it
            if b < 0x80:
                optbuffer.append(b)
                i += 1
                continue

            # If this length == last_len*2, we may be able to optimize
            if last_len == 0 or b != last_len*2:
                # If this length == last_len, we must have optimized, so delete this
                # by moving on without taking this length byte
                if b == last_len:
                    i += 1
                    continue
                # Otherwise, just keep this length and move on
                optbuffer.append(b)
                last_len = b
                i += 1
                continue
            # This length is double last_len, can we optimize?
            # - If there's more than one note before another length: no
            if i+2 < len(self.buffer) and self.buffer[i+2] < 0x80:
                # normal byte, we can't optimize this
                # just keep it and the two normal bytes following it
                # and update last_len
                optbuffer += self.buffer[i:i+3]
                last_len = b
                i += 3
                continue

            # We hit a length byte that we can optimize away
            # Don't append b, just append two of the following byte
            optbuffer.append(self.buffer[i+1])
            optbuffer.append(self.buffer[i+1])
            i += 2 # update i to after the optimized length and following note
            continue

        self.buffer = optbuffer


    def create_buffer(self, rest_array):
        '''Returns a bytearray that represents the channel's music in SMB3 format'''
        if len(self.notes) == 0:
            return
        note1 = self.notes[0]
        self.buffer.append(rest_array.index(note1.length) | 0xc0)
        self.buffer.append(note1.notebyte)
        last_len = note1.length
        for i, note in enumerate(self.notes[1:], 1):
            if note.length != last_len:
                self.buffer.append(rest_array.index(note.length) | 0xc0)
                last_len = note.length
            self.buffer.append(note.notebyte)

        # Square 2 is the master channel, so it gets a $00 byte to end the segment
        if self.wavetype == 'sq2':
            self.buffer.append(0x00)
        # There's something about the noise channel that it needs a $00 byte at the end of it
        if self.wavetype == 'nse':
            self.buffer.append(0x00)

        # Place to put any possible buffer optimizations
        #self._optimize_buffer()

    def get_rest(self):
        ''' Return the correct encoding for a rest byte for this channel

        '''
        return 1 if self.wavetype == 'nse' else 0x7E

    def parse_chan_text(self, row, chan_text):
        # We begin notes in a few different cases:
        # 1. When the actual 'note' field is not '...'
        #    a. If the field is '---' (cutoff), it's a rest.
        #    b. Otherwise, it's a note whose byte is calculated (or is an index for dpcm)
        # 2. For non-triangle or -dpcm channels:
        #    a. (note field _is_ ...: Volume != 0 and notes[-1] is a rest (volume-caused cloned note)
        #    b. Volume == 0: rest note
        is_rest = False
        is_clone = False
        create_note = False
        if FTChannel.get_note_field(chan_text) != '..':
            # note field is _not_ '...'
            if FTChannel.get_note_field(chan_text) == '--':
                # 1a
                is_rest = True
            else:
                # 1b
                create_note = True
        # TODO: mmc5, do we need to change this array?
        if self.wavetype not in ['tri', 'dpcm']:
            # 2b
            if FTChannel.get_volume_field(chan_text) == '0':
                is_rest = True
            else:
                if FTChannel.get_note_field(chan_text) == '..' \
                        and FTChannel.get_volume_field(chan_text) != '.' \
                        and self.notes[-1].is_rest():
                    # 2a
                    is_clone = True

        cloneobj = None if not is_clone else self.notes[-2]
        if create_note or is_clone or is_rest:
            self.notes.append(FTNote(row, chan_text, self, rest=is_rest, clone=cloneobj))

    def set_note_lengths(self, last_row, rest_array):
        if len(self.notes) == 0:
            print('NOTE: The {} channel is disabled.'.format(self.wavetype))
            return
        for i, curr in enumerate(self.notes[:-1]):
            curr.length = self.notes[i+1].row - curr.row
            if curr.length not in rest_array:
                rest_array.append(curr.length)
        # The last note's length is the last row minus the last note's row
        last_note = self.notes[-1]
        last_note.length = last_row - last_note.row
        if last_note.length not in rest_array:
            rest_array.append(last_note.length)

        # There's a problem if the rest_array's length > 16
        if len(rest_array) > 16:
            print('WARNING: The rest array is too large ({} items).'.format(len(rest_array)))


class FTNote(object):
    '''Contains all information about a single note from a channel.

    Attributes:
        row (int): The overall row number this note corresponds to. This takes
                   into account rows per pattern and the current pattern.
        channel (str): The channel object to which this note belongs.
        note_text (str): The text from a single channel's column.
                         For example: 'E-3 00 A P80 V00 ...'
        octave (int): The octave of this note.
        length (int): The length (in "rows") of this note.
        volume (int): The volume (if applicable). The triangle and dpcm channels
                      don't use volume.

    '''

    def __init__(self, row, note_text, ft_channel, rest=False, clone=None):
        '''Contructed from the text within a single channel's column.

        Args:
            row (int): The overall row number this note corresponds to. This
                       is calculated by pattern*rows_per_pattern+rownum.
            note_text (str): The text from a single channel's column.
                             For example: 'E-3 00 A P80 V00 ...'
            ft_channel (FTChannel): The channel to which this note belongs.
            rest (bool): Create a rest note, ignoring the note_text.
            clone (FTNote): Create a clone of this note.

        '''
        self.row = row
        self.channel = ft_channel
        self.note_text = note_text

        if rest:
            self.notebyte = self.channel.get_rest()
            return

        if clone:
            self.notebyte = clone.notebyte
            return

        note = FTChannel.get_note_field(note_text)
        if self.channel.wavetype == 'nse':
            # Noise channel notes use a different lookup table
            self.notebyte = NOISE_NOTE_BYTES[note]
        elif self.channel.wavetype == 'dpcm':
            # DPCM channel notes are simply the index of the note plus 1
            self.notebyte = NOTES.index(note) + 1
        else:
            # Every other note is calculated based on octave
            octave = int(FTChannel.get_octave_field(note_text))
            self.notebyte = NOTES.index(note)*2 + (octave-1)*24

    def is_rest(self):
        return self.notebyte == self.channel.get_rest()

def main(args):
    if not len(args):
        print(usage(sys.argv[0]))
        return 1

    try:
        song = FTSong(args[0])
        print(song.smb3_format())
        song.dump_info()
    except FileNotFoundError as e:
        print('{}\n\t{}'.format(usage(sys.argv[0]), e))
        return 2

    return 0

if __name__=='__main__':
    sys.exit(main(sys.argv[1:]))
