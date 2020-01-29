#!/usr/bin/env python3
import sys
from binascii import hexlify
from itertools import zip_longest

NOTES = ['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-']
#RESTS = [0x04, 0x05, 0x06, 0x06, 0x09, 0x0D, 0x0C, 0x0C, 0x12, 0x1B, 0x24, 0x36, 0x48, 0x1E, 0x03, 0x00]
#RESTS = [0x04, 0x08, 0x06, 0x18, 0x09, 0x24, 0x0C, 0x26, 0x12, 0x1B, 0x2a, 0x3a, 0x3c, 0x1E, 0x03, 0x02]
#RESTS = [0x05, 0x06, 0x07, 0x15, 0x16, 0x08, 0x09, 0x0e, 0x18, 0x24, 0x2a, 0x3a, 0x3c, 0x1E, 0x03, 0x02]
RESTS = []
rest_index = 0

smb3_acceptable_replacements = {
    'nse':  {
        1:  6
    }
}

def usage(name):
    return 'Usage: {} <FAMITRACKER EXPORTED TEXT FILE>'.format(name)

def get_volume_caused_length(l, wavetype):
    global RESTS
    global rest_index
    if l not in RESTS:
        #try:
            #l = smb3_acceptable_replacements[wavetype][l]
        #except Exception as e:
        RESTS.append(l)
        rest_index += 1
        #print('Error: {}'.format(e))
        #print('    Could not find note of length 0x{:X} within RESTS array.'.format(l))
        print('#### Added {} to RESTS array ####'.format(l))
        if rest_index > 0xf:
            raise Exception('Too many new rests required.')
    return l

last_len = 0
def find_notelen(lines, start, wavetype):
    vol_len = []
    end = start
    extranneous = 0
    in_a_rest = False
    note_start = start
    while True:
        end = end + 1
        if 'ROW' not in lines[end]:
            extranneous += 1
            continue

        row, sq1, sq2, tri, nse, dpcm = lines[end].split(':')
        wave = {'sq1': sq1, 'sq2': sq2, 'tri': tri, 'nse': nse}.get(wavetype)

        note, octave, instrument, vol, fxlist = (lambda n, i, v, *f: (n[:-1], n[2], i, v, f))(*wave.split())
        if (vol != '.' and int(vol, 16) == 0):
            # Note ended because of vol = 0, we're in a rest until the next volume increase or note start
            print('            [line {}]: NOTE ended due to volume at {}'.format(note_start+1, end+1))
            in_a_rest = True
            l = get_volume_caused_length((end - note_start) - extranneous, wavetype)
            if l != 0:
                print('            [line {}]: adding note length 0x{:02X}'.format(note_start+1, l))
                vol_len.append(l)
                note_start += l
        if (note != '..' and note != '--' and (wavetype == 'tri' or int(vol, 16) != 0)):
            # Note ended due to another note. If we don't have this length here, try the last_len + a REST
            full_len = end - note_start - extranneous
            if full_len not in RESTS and last_len != 0 and full_len > last_len:
                # We can use last_len as our note length, and then use some RESTS amount
                # This effectively makes this a volume-caused length
                end = note_start + last_len      # reset end and continue the loop
                in_a_rest = True
                print('            [+] adding note length 0x{:02X}'.format(last_len))
                vol_len.append(last_len)
                note_start += last_len
                continue
            print('            * returning full_len = 0x{:02X}'.format(end - start - extranneous))
            return vol_len, end-start-extranneous
        if (vol != '.' and int(vol, 16) != 0 and in_a_rest):
            # This REST ended due to the volume going up
            print('            [line {}]: REST ended due to volume at {}'.format(note_start, end+1))
            in_a_rest = False
            l = get_volume_caused_length((end - note_start) - extranneous, wavetype)
            print('            [line {}]: adding note length 0x{:02X}'.format(note_start, l))
            vol_len.append(l)
            note_start += l

def _output_song_byte(outarray, notebyte, length, typ):
    global RESTS
    global rest_index
    global last_len
    real_length = length

    if length == last_len:
        # Just output it
        #print('{:X} '.format(notebyte))
        outarray.append(notebyte)
    else:
        try:
            lenbyte = 0x90 | RESTS.index(length)
        except Exception as e:
            RESTS.append(length)
            rest_index += 1
            print('#### Added {} to RESTS array ####'.format(length))
            if rest_index > 0xf:
                raise Exception('Too many new rests required.')
            #print('Error: {}'.format(e))
            #print('    Could not find note of length 0x{:X} within RESTS array.'.format(length))
            #lenbyte = 0xFF
            lenbyte = 0x90 | RESTS.index(length)
        last_len = length
        #print('{:X} {:X} '.format(lenbyte, notebyte))
        outarray.append(lenbyte)
        outarray.append(notebyte)
    return real_length

def output_song_byte(outarray, notebyte, length, typ):
    processed = 0
    restnote = 0x7E if typ != 'nse' else 0x01
    currnote = restnote
    if type(length) is list:
        for l in length:
            print('       Processing note length {}...'.format(l))
            currnote = notebyte if currnote == restnote else restnote
            processed += _output_song_byte(outarray, currnote, l, typ)
    else:
        processed = _output_song_byte(outarray, notebyte, length, typ)

    return processed

def main(args):
    if not len(args):
        print(usage(sys.argv[0]))
        return 1

    try:
        with open(args[0], 'r') as f:
            tlines = f.readlines()
    except FileNotFoundError as e:
        print('{}\n\t{}'.format(usage(sys.argv[0]), e))
        return 2

    create_pattern = False
    curr = -1
    sq1out = []
    sq2out = []
    triout = []
    nseout = []
    for l in tlines:
        curr = curr + 1
        if create_pattern:
            if not l.startswith('ROW'):
                create_pattern = False
                continue
            if 'C00' in l:
                print('sq1:\n', ''.join('${:02X}, '.format(b) for b in sq1out))
                print('sq2:\n', ''.join('${:02X}, '.format(b) for b in sq2out))
                print('tri:\n', ''.join('${:02X}, '.format(b) for b in triout))
                print('nse:\n', ''.join('${:02X}, '.format(b) for b in nseout))
                print('RESTS:\n', ''.join('${:02X}, '.format(b) for b in RESTS))
                return 0
            #print('Processing: {}'.format(l))

            row, sq1, sq2, tri, nse, dpcm = l.split(':')

            for typ, wave, outarray in [('sq1', sq1, sq1out),   \
                                        ('sq2', sq2, sq2out),   \
                                        ('tri', tri, triout),   \
                                        ('nse', nse, nseout)]:
                note, octave, instrument, vol, fxlist = (lambda n, i, v, *f: (n[:-1], n[2], i, v, f))(*wave.split())
                if note == '..' or note == '--':
                    continue
                print('{}[{}]: {}'.format(typ, curr+1, wave.split()))
                octave = 0 if octave == '#' else int(octave)
                if typ == 'nse':
                    notebyte = 0x2
                else:
                    notebyte = NOTES.index(note)*2 + (octave-1)*24

                vol_len, full_len = find_notelen(tlines, curr, typ)
                if vol_len:
                    vol_len = output_song_byte(outarray, notebyte, vol_len, typ)
                    full_len -= vol_len
                    notebyte = 0x7E if typ != 'nse' else 0x01

                if full_len:
                    output_song_byte(outarray, notebyte, full_len, typ)

        if l.startswith('PATTERN'):
            create_pattern = True

if __name__=='__main__':
    sys.exit(main(sys.argv[1:]))
