import logging
import os
import shlex
import subprocess
import sys
from time import sleep
from streamlink.utils.encoding import get_filesystem_encoding, maybe_encode, maybe_decode
from StreamDownloader.compat import is_win32, stdout
from StreamDownloader.constants import DEFAULT_PLAYER_ARGUMENTS, SUPPORTED_PLAYERS
from contextlib import contextmanager

@contextmanager
def ignored(*exceptions):
    try:
        yield None
    except exceptions:
        pass

if is_win32:
    import msvcrt
log = logging.getLogger('streamlink.cli.output')

class Output(object):

    def __init__(self):
        self.opened = False

    def open(self):
        self._open()
        self.opened = True

    def close(self):
        if self.opened:
            self._close()
        self.opened = False

    def write(self, data):
        if not self.opened:
            raise IOError('Output is not opened')
        return self._write(data)

    def _open(self):
        pass

    def _close(self):
        pass

    def _write(self, data):
        pass

class FileOutput(Output):

    def __init__(self, filename=None, fd=None, record=None):
        super(FileOutput, self).__init__()
        self.filename = filename
        self.fd = fd
        self.record = record

    def _open(self):
        if self.filename:
            self.fd = open(self.filename, 'wb')
        if self.record:
            self.record.open()
        if is_win32:
            msvcrt.setmode(self.fd.fileno(), os.O_BINARY)

    def _close(self):
        if self.fd is not stdout:
            self.fd.close()
        if self.record:
            self.record.close()

    def _write(self, data):
        self.fd.write(data)
        if self.record:
            self.record.write(data)

class PlayerOutput(Output):
    PLAYER_TERMINATE_TIMEOUT = 10.0

    def __init__(self, cmd, args=DEFAULT_PLAYER_ARGUMENTS, filename=None, quiet=True, kill=True, call=False, http=None, namedpipe=None, record=None, title=None):
        super(PlayerOutput, self).__init__()
        self.cmd = cmd
        self.args = args
        self.kill = kill
        self.call = call
        self.quiet = quiet
        self.filename = filename
        self.namedpipe = namedpipe
        self.http = http
        self.title = title
        self.player = None
        self.player_name = self.supported_player(self.cmd)
        self.record = record
        if self.namedpipe or self.filename or self.http:
            self.stdin = sys.stdin
        else:
            self.stdin = subprocess.PIPE
        if self.quiet:
            self.stdout = open(os.devnull, 'w')
            self.stderr = open(os.devnull, 'w')
        else:
            self.stdout = sys.stdout
            self.stderr = sys.stderr

    @property
    def running(self):
        sleep(0.5)
        return self.player.poll() is None

    @classmethod
    def supported_player(cls, cmd):
        '''
        Check if the current player supports adding a title

        :param cmd: command to test
        :return: name of the player|None
        '''
        if not is_win32:
            cmd = shlex.split(cmd)[0]
        cmd = os.path.basename(cmd.lower())
        for (player, possiblecmds) in SUPPORTED_PLAYERS.items():
            for possiblecmd in possiblecmds:
                if cmd.startswith(possiblecmd):
                    return player

    @classmethod
    def _mpv_title_escape(cls, title_string):
        if '\\$>' in title_string:
            processed_title = ''
            double_dollars = True
            i = dollars = 0
            while i < len(title_string):
                if double_dollars:
                    if title_string[i] == '\\':
                        if title_string[i + 1] == '$':
                            processed_title += '$'
                            dollars += 1
                            i += 1
                            if title_string[i + 1] == '>' and dollars % 2 == 1:
                                double_dollars = False
                                processed_title += '>'
                                i += 1
                        else:
                            processed_title += '\\'
                            if title_string[i] == '$':
                                processed_title += '$$'
                            else:
                                dollars = 0
                                processed_title += title_string[i]
                    elif title_string[i] == '$':
                        processed_title += '$$'
                    else:
                        dollars = 0
                        processed_title += title_string[i]
                elif title_string[i:i + 2] == '\\$':
                    processed_title += '$'
                    i += 1
                else:
                    processed_title += title_string[i]
                i += 1
            return processed_title
        else:
            return title_string.replace('$', '$$').replace('\\$$', '$')

    def _create_arguments(self):
        if self.namedpipe:
            filename = self.namedpipe.path
        elif self.filename:
            filename = self.filename
        elif self.http:
            filename = self.http.url
        else:
            filename = '-'
        args = self.args.format(filename=filename)
        cmd = self.cmd
        extra_args = []
        if self.title is not None:
            if self.player_name == 'vlc':
                self.title = self.title.replace('$', '$$').replace('\\$$', '$')
                extra_args.extend(['--input-title-format', self.title])
            if self.player_name == 'mpv':
                self.title = self._mpv_title_escape(self.title)
                extra_args.extend(['--title', self.title])
        if is_win32:
            eargs = maybe_decode(subprocess.list2cmdline(extra_args))
            return maybe_encode(' '.join([cmd] + ([eargs] if eargs else []) + [args]), encoding=get_filesystem_encoding())
        return shlex.split(cmd) + extra_args + shlex.split(args)

    def _open(self):
        try:
            if self.record:
                self.record.open()
            if self.call and self.filename:
                self._open_call()
            else:
                self._open_subprocess()
        finally:
            if self.quiet:
                self.stdout.close()
                self.stderr.close()

    def _open_call(self):
        args = self._create_arguments()
        if is_win32:
            fargs = args
        else:
            fargs = subprocess.list2cmdline(args)
        log.debug('Calling: {0}'.format(fargs))
        subprocess.call(args, stdout=self.stdout, stderr=self.stderr)

    def _open_subprocess(self):
        args = self._create_arguments()
        if is_win32:
            fargs = args
        else:
            fargs = subprocess.list2cmdline(args)
        log.debug('Opening subprocess: {0}'.format(fargs))
        self.player = subprocess.Popen(args, stdin=self.stdin, bufsize=0, stdout=self.stdout, stderr=self.stderr)
        if not self.running:
            raise OSError('Process exited prematurely')
        if self.namedpipe:
            self.namedpipe.open('wb')
        elif self.http:
            self.http.open()

    def _close(self):
        if self.namedpipe:
            self.namedpipe.close()
        elif self.http:
            self.http.close()
        elif not self.filename:
            self.player.stdin.close()
        if self.record:
            self.record.close()
        if self.kill:
            with ignored(Exception):
                self.player.terminate()
                if not is_win32:
                    (t, timeout) = (0.0, self.PLAYER_TERMINATE_TIMEOUT)
                    while self.player.poll() is None and t < timeout:
                        sleep(0.5)
                        t += 0.5
                    if not self.player.returncode:
                        self.player.kill()
        self.player.wait()

    def _write(self, data):
        if self.record:
            self.record.write(data)
        if self.namedpipe:
            self.namedpipe.write(data)
        elif self.http:
            self.http.write(data)
        else:
            self.player.stdin.write(data)

__all__ = ['PlayerOutput', 'FileOutput']
