#!/usr/bin/env python2

import os
import re
import sys
import urllib2
import ConfigParser
from errno import ENOENT
from stat import S_IFDIR, S_IFREG
import time
import argparse
import operator
import shutil
import tempfile
import threading
import logging

from eyed3.id3 import Tag
from eyed3.id3 import ID3_V1_0, ID3_V1_1, ID3_V2_3, ID3_V2_4

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
from gmusicapi import Mobileclient as GoogleMusicAPI
from gmusicapi import Webclient as GoogleMusicWebAPI

import fifo

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
deviceId=None

def formatNames(string_from):
    string_from = string_from.replace(": ", " - ")
    string_from = string_from.replace(":", "-")
    string_from = re.sub("[/]", '-', string_from)
    string_from = re.sub("[\?\"\`]", '', string_from)
    return string_from

class NoCredentialException(Exception):
    pass

class Album(object):
    'Keep record of Album information'
    def __init__(self, library, normtitle, artist, album, year):
        self.library = library
        self.normtitle = formatNames(normtitle)
        self.artist = artist
        self.album = album
        self.year = year
        self.__tracks = []
        self.__sorted = True
        self.__filename_re = re.compile("^[0-9]{2}_(.*)\.mp3$")
        self.__art = None
        self.__art_size = None
        self.__art_url = None
        self.__discs = []
        self.show_discnum = False

    def gen_tag(self, track, fake_art=False):
        tag = Tag()

        if track.has_key('album'):
            tag.album = track['album']
        if track.has_key('artist'):
            tag.artist = " / ".join(track['artist'])
            if len(track['artist']) == 2:
                print track['artist']
        if track.has_key('title'):
            tag.title = track['title']
        if track.has_key('discNumber') and self.show_discnum:
            tag.disc_num = int(track['discNumber'])
        if track.has_key('trackNumber'):
            tag.track_num = int(track['trackNumber'])
        if track.has_key('genre'):
            tag.genre = track['genre']
        if track.has_key('albumArtist') and (len(track['artist']) != 1 or track['albumArtist'] != track['artist'][0]):
            tag.setTextFrame('TPE2', track['albumArtist'])
        if track.has_key('year') and int(track['year']) != 0:
            tag.recording_date = track['year']
        if track.has_key('albumArtRef'):
            art = None
            if self.__art is None:
                if fake_art:
                    art = '\0' * self.__art_size
                else:
                    if self.load_art():
                        art = self.__art
                    else:
                        art = None
            else:
                art = self.__art
            if art is not None:
                tag.images.set(0x03, art, 'image/jpeg', u'Front cover')
        return tag

    def render_tag(self, tag, version):
        tmpfd, tmpfile = tempfile.mkstemp()
        os.close(tmpfd)
        tag.save(tmpfile, version)
        tmpfd = open(tmpfile, "r")
        rendered_tag = tmpfd.read()
        tmpfd.close()
        os.unlink(tmpfile)
        return rendered_tag

    def calc_size(self, track):
        if not track.has_key('tagSize'):
            if self.__art_url is None and track.has_key('albumArtRef'):
                self.__art_url = "%s" % track['albumArtRef'][0]['url']
                r = urllib2.Request(self.__art_url)
                r.get_method = lambda: 'HEAD'
                u = urllib2.urlopen(r)
                self.__art_size = int(u.headers['Content-Length'])
                u.close()

            tag = self.gen_tag(track, fake_art=True)
            id3data = self.render_tag(tag, ID3_V2_4)
            track['tagSize'] = str(int(track['estimatedSize']) + 128 + len(id3data))
            del id3data
            for frame in tag.frame_set.getAllFrames():
                if hasattr(frame, 'text'):
                    print frame.id, frame.text
                else:
                    print frame.id
            del tag
            for tnum in range(0, len(self.__tracks)):
                if self.__tracks[tnum]['id'] == track['id']:
                    self.__tracks[tnum]['tagSize'] = track['tagSize']
        return track

    def add_track(self, track):
        'Add a track to the Album'
        if track.has_key('discNumber') and int(track['discNumber']) not in self.__discs:
            self.__discs.append(int(track['discNumber']))
        self.__tracks.append(track)
        self.__sorted = False

    def copy_art_to(self, new_album):
        'Copies art information to another album'
        new_album.set_art(self.__art_url, self.__art_size, self.__art)

    def set_art(self, art_url, art_size, art_data):
        'Sets art data to values.  If you think you need this, you probably do not'
        self.__art_url = art_url
        self.__art_size = art_size
        self.__art = art_data

    def load_art(self):
        if self.__art_url is not None:
            u = urllib2.urlopen(self.__art_url)
            self.__art = ""
            data = u.read()
            while data != "":
                self.__art += data
                data = u.read()
            return True
        else:
            return False

    def get_tracks(self, get_size=False):
        # Re-sort by track number:
        if not self.__sorted:
            self.__tracks.sort(key=lambda t: t.get('track'))
        return self.__tracks

    def get_track(self, filename):
        """Get the track name corresponding to a filename
        (eg. '001 - brilliant track name.mp3')"""
        m = self.__filename_re.match(filename)
        if m:
            title = m.groups()[0]
            for track in self.get_tracks():
                if formatNames(track['title']) == title:
                    return track
        return None

    def get_track_stream(self, track):
        "Get the track stream URL"
        return self.library.api.get_stream_url(track['id'], deviceId)

    def get_cover_url(self):
        'Get the album cover image URL'
        try:
            #Assume the first track has the right cover URL:
            url = "%s" % self.__tracks[0]['albumArtRef'][0]['url']
        except:
            url = None
        return url

    def get_year(self):
        """Get the year of the album.
        Aggregate all the track years and pick the most popular year
        among them"""
        years = {} # year -> count
        for track in self.get_tracks():
            y = track.get('year', None)
            if y:
                count = years.get(y, 0)
                years[y] = count + 1
        top_years = sorted(years.items(),
                           key=operator.itemgetter(1), reverse=True)
        try:
            top_year = top_years[0][0]
        except IndexError:
            top_year = 0
        return top_year

    def get_track_count(self):
        return len(self.__tracks)

    def get_disc_count(self):
        return len(self.__discs)

    def get_discs(self):
        return self.__discs

    def __repr__(self):
        return u'<Album \'{title}\'>'.format(title=self.normtitle)

class MusicLibrary(object):
    'Read information about your Google Music library'

    def __init__(self, username=None, password=None,
                 true_file_size=False, scan=True, verbose=0):
        self.verbose = False
        if verbose > 1:
            self.verbose = True

        self.__login_and_setup(username, password)

        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__galbums = {}
        self.__gartists = {}
        self.__albums = [] # [Album(), ...]
        if scan:
            self.rescan()
        self.true_file_size = true_file_size

    def rescan(self):
        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__albums = [] # [Album(), ...]
        self.__galbums = {}
        self.__gartists = {}
        self.__aggregate_albums()

    def __login_and_setup(self, username=None, password=None):
        # If credentials are not specified, get them from $HOME/.gmusicfs
        if not username or not password:
            cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs')
            if not os.path.isfile(cred_path):
                raise NoCredentialException(
                    'No username/password was specified. No config file could '
                    'be found either. Try creating %s and specifying your '
                    'username/password there. Make sure to chmod 600.'
                    % cred_path)
            if not oct(os.stat(cred_path)[os.path.stat.ST_MODE]).endswith('00'):
                raise NoCredentialException(
                    'Config file is not protected. Please run: '
                    'chmod 600 %s' % cred_path)
            self.config = ConfigParser.ConfigParser()
            self.config.read(cred_path)
            username = self.config.get('credentials','username')
            password = self.config.get('credentials','password')
            global deviceId
            deviceId = self.config.get('credentials','deviceId')
            if not username or not password:
                raise NoCredentialException(
                    'No username/password could be read from config file'
                    ': %s' % cred_path)
            if not deviceId:
                raise NoCredentialException(
                    'No deviceId could be read from config file'
                    ': %s' % cred_path)

        self.api = GoogleMusicAPI(debug_logging=self.verbose)
        log.info('Logging in...')
        self.api.login(username, password)
        log.info('Login successful.')

    def __set_key_from_ginfo(self, track, ginfo, key, to_key=None):
        'Set track key from either album_info or artist_info'
        if to_key is None:
            to_key = key

        try:
            int_key = int(key)
        except ValueError:
            int_key = None

        if (not track.has_key(key) or track[key] == "" or int_key == 0) and ginfo.has_key(to_key):
            track[key] = ginfo[to_key]

        return track

    def __cleanup_artist(self, artist):
        if artist.startswith("featuring"):
            artist = artist[len("featuring"):].strip()
        if artist.startswith("feat"):
            artist = artist[len("feat"):].strip()
        return artist

    def __cleanup_name(self, name, track):
        for bracket in (('\[', '\]'), ('\{', '\}'), ('\(', '\)')):
            # Remove (xxx Album Version) from track names
            match = re.compile('^(?P<name>(.*))([ ]+[%s-]([^%s]*)[Vv]ersion[%s]?[ ]*)$' % (bracket[0], bracket[1], bracket[1])).match(name)
            if match is not None:
                name = match.groupdict()['name']
                name, track = self.__cleanup_name(name, track)

            # Pull (feat. <artist>) out of name and add to artist list
            match = re.compile('^(?P<name>(.*))([ ]+[%s][ ]*[Ff]eat[\.]?[ ]*(?P<artist>(.*))[%s]+)(?P<postfix>(.*))$' % (bracket[0], bracket[1])).match(name)
            if match is not None:
                name = match.groupdict()['name']
                artist = match.groupdict()['artist']
                if match.groupdict().has_key('postfix') and match.groupdict()['postfix'] is not None:
                    name += match.groupdict()['postfix']
                artist = artist.strip()
                if artist[-1] in ")}]": # I hate regex's.  The one above doesn't catch the last parenthesis if there's one
                    artist = artist[:-1]
                if artist.find(" and ") > -1 or artist.find(" & ") > -1:
                    artist = artist.replace(', ', ';')
                artist = artist.replace(' & ', ';')
                artist = artist.replace(' and ', ';')
                alist = artist.split(';')
                for artist in alist:
                     track['artist'].append(artist.strip())
                name, track = self.__cleanup_name(name, track)

            # Remove () or ( ) from track names
            match = re.compile('^(?P<name>(.*))([ ]*[%s][ ]?[%s][ ]*)$' % (bracket[0], bracket[1])).match(name)
            if match is not None:
                name = match.groupdict()['name']
                name, track = self.__cleanup_name(name, track)

        # Strip any extra whitespace from the name
        name = name.strip()
        return name, track

    def __cleanup_track(self, track):
        name = track['title']
        name, track = self.__cleanup_name(name, track)
        track['title'] = name
        for anum in range(0, len(track['artist'])):
            track['artist'][anum] = self.__cleanup_artist(track['artist'][anum])
        return track

    def __aggregate_albums(self):
        'Get all the tracks in the library, parse into artist and album dicts'
        all_artist_albums = {}
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        for track in tracks:
            if track.has_key('artist'):
                if track['artist'].find(" and ") > -1 or track['artist'].find(" & ") > -1:
                    track['artist'] = track['artist'].replace(', ', ';')
                track['artist'] = track['artist'].replace(' & ', ';')
                track['artist'] = track['artist'].replace(' and ', ';')
                track['artist'] = track['artist'].split(';')
            else:
                track['artist'] = []

            track = self.__cleanup_track(track)

            if track.has_key('albumArtist') and track['albumArtist'] != "":
                albumartist = track['albumArtist']
            elif len(track['artist']) == 1 and track['artist'][0] != "":
                albumartist = track['artist'][0]
            else:
                albumartist = "Unknown"

            # Get album and artist information from Google
            if track.has_key('albumId'):
                if self.__galbums.has_key(track['albumId']):
                    album_info = self.__galbums[track['albumId']]
                else:
                    print "Downloading album info for '%s'" % track['album']
                    album_info = self.__galbums[track['albumId']] = self.api.get_album_info(track['albumId'], include_tracks=False)
                if album_info.has_key('artistId') and len(album_info['artistId']) > 0 and album_info['artistId'][0] != "":
                    artist_id = album_info['artistId'][0]
                    if self.__gartists.has_key(artist_id):
                        artist_info = self.__gartists[artist_id]
                    else:
                        print "Downloading artist info for '%s'" % album_info['albumArtist']
                        if album_info['albumArtist'] == "Various":
                            print album_info
                        artist_info = self.__gartists[artist_id] = self.api.get_artist_info(artist_id, include_albums=False, max_top_tracks=0, max_rel_artist=0)
                else:
                    artist_info = {}
            else:
                album_info = {}
                artist_info = {}

            track = self.__set_key_from_ginfo(track, album_info, 'album', 'name')
            track = self.__set_key_from_ginfo(track, album_info, 'year')
            track = self.__set_key_from_ginfo(track, artist_info, 'albumArtist', 'name')

            # Fix for odd capitalization issues
            if artist_info.has_key('name') and track['albumArtist'].lower() == artist_info['name'].lower() and track['albumArtist'] != artist_info['name']:
                track['albumArtist'] = artist_info['name']
            for anum in range(0, len(track['artist'])):
                if artist_info.has_key('name') and track['artist'][anum].lower() == artist_info['name'].lower() and track['artist'][anum] != artist_info['name']:
                    track['artist'][anum] = artist_info['name']

            if not track.has_key('albumId'):
                track['albumKey'] = "%s|||%s" % (albumartist, track['album'])
            else:
                track['albumKey'] = track['albumId']
            album = all_artist_albums.get(track['albumKey'], None)

            if not album:
                album = all_artist_albums[track['albumKey']] = Album(
                    self, formatNames(track['album']), track['albumArtist'], track['album'], track['year'] )
                self.__albums.append(album)
                artist_albums = self.__artists.get(track['albumArtist'], None)
                if artist_albums:
                    artist_albums[formatNames(album.normtitle)] = album
                else:
                    self.__artists[track['albumArtist']] = {album.normtitle: album}
                    artist_albums = self.__artists[track['albumArtist']]
            album.add_track(track)

        # Separate multi-disc albums
        for artist in self.__artists.values():
            for key in artist.keys():
                album = artist[key]
                if album.get_disc_count() > 1:
                    for d in album.get_discs():
                        new_name = "%s - Disc %i" % (album.album, d)
                        new_album = Album(album.library, formatNames(new_name), album.artist, new_name, album.year)
                        album.copy_art_to(new_album)
                        new_album.show_discnum = True
                        new_key = None
                        for t in album.get_tracks():
                            if int(t['discNumber']) == d:
                                new_album.add_track(t)
                        artist[formatNames(new_name)] = new_album
                    del artist[key]

        log.debug('%d tracks loaded.' % len(tracks))
        log.debug('%d artists loaded.' % len(self.__artists))
        log.debug('%d albums loaded.' % len(self.__albums))

    def get_artists(self):
        return self.__artists

    def get_albums(self):
        return self.__albums

    def get_artist_albums(self, artist):
        log.debug(artist)
        return self.__artists[artist]

    def cleanup(self):
        pass

class GMusicFS(LoggingMixIn, Operations):
    'Google Music Filesystem'
    def __init__(self, path, username=None, password=None,
                 true_file_size=False, verbose=0, scan_library=True):
        Operations.__init__(self)
        self.artist_dir = re.compile('^/artists/(?P<artist>[^/]+)$')
        self.artist_album_dir = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4})_(?P<album>[^/]+)$')
        self.artist_album_track = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4})_(?P<album>[^/]+)/(?P<track>[^/]+\.mp3)$')

        self.__open_files = {} # path -> urllib2_obj
        self.__urls = {}       # path -> url
        self.__tags = {}       # fh -> (id3v1, id3v2)

        # login to google music and parse the tracks:
        self.library = MusicLibrary(username, password,
                                    true_file_size=true_file_size, verbose=verbose, scan=scan_library)
        log.info("Filesystem ready : %s" % path)

    def cleanup(self):
        self.library.cleanup()

    def getattr(self, path, fh=None):
        'Get info about a file/dir'
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)

        # Default to a directory
        st = {
            'st_mode' : (S_IFDIR | 0755),
            'st_size' : 1,
            'st_nlink' : 2 }
        date = time.time()
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date

        if path == '/':
            pass
        elif path == '/artists':
            st['st_size'] = len(self.library.get_artists())
        elif artist_dir_m:
            try:
                albums = self.library.get_artist_albums(
                    artist_dir_m.groupdict()['artist'])
            except KeyError:
                raise FuseOSError(ENOENT)
            st['st_size'] = len(albums)
        elif artist_album_dir_m:
            parts = artist_album_dir_m.groupdict()
            try:
                album = self.library.get_artists()[
                    parts['artist']][parts['album']]
            except KeyError:
                raise FuseOSError(ENOENT)
            st['st_size'] = album.get_track_count()
        elif artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            try:
                album = self.library.get_artists()[
                    parts['artist']][parts['album']]
                track = album.get_track(parts['track'])
            except KeyError:
                raise FuseOSError(ENOENT)

            if not track.has_key('tagSize'):
                track = album.calc_size(track)
            st = {
                'st_mode' : (S_IFREG | 0644),
                'st_size' : int(track['tagSize']),
                'st_nlink' : 1,
                'st_ctime' : int(track['creationTimestamp']) / 1000000,
                'st_mtime' : int(track['creationTimestamp']) / 1000000,
                'st_atime' : int(track['recentTimestamp']) / 1000000}
        else:
            raise FuseOSError(ENOENT)

        return st

    def _open(self, path, fh):
        album_track = self.__urls.get(fh, None)
        if album_track is None:
            raise RuntimeError('unexpected path: %r' % path)
        (album, track) = album_track
        url = album.get_track_stream(track)
        u = self.__open_files[fh] = urllib2.urlopen(url)
        u.bytes_read = 0
        return fh

    def open(self, path, fh):
        artist_album_track_m = self.artist_album_track.match(path)

        if artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            track = album.get_track(parts['track'])
            if not track.has_key('tagSize'):
                track = album.calc_size(track)

            self.__urls[fh] = (album, track)
            self.__tags[fh] = (album.gen_tag(track))
        else:
            RuntimeError('unexpected opening of path: %r' % path)

        return fh


    def release(self, path, fh):
        for clear_item in (self.__open_files, self.__urls, self.__tags):
            u = clear_item.get(fh, None)
            if u:
                if hasattr(u, 'close'):
                    u.close()
                del clear_item[fh]

    def read(self, path, size, offset, fh):
        album_track = self.__urls.get(fh, None)
        if album_track is None:
            raise RuntimeError('unexpected path: %r' % path)
        (album, track) = album_track

        tag = self.__tags.get(fh, None)
        if tag is None:
            id3v1data = '\0' * 128
            id3v2data = ''
        else:
            id3v1data = album.render_tag(tag, ID3_V1_1)
            id3v2data = album.render_tag(tag, ID3_V2_4)

        start_id3v1tag = int(track['tagSize']) - 128
        end_id3v2tag = len(id3v2data)
        buf = ""

        if offset >= start_id3v1tag:
            buf = id3v1data[offset - start_id3v1tag:(offset - start_id3v1tag) + size]
            return buf

        if offset < end_id3v2tag:
            buf = id3v2data[offset:offset+size]
            size -= len(buf)
            offset = end_id3v2tag

        if size <= 0:
            return buf

        u = self.__open_files.get(fh, None)
        if u is None:
            if self.__urls.get(fh, None) is None:
                raise RuntimeError('unexpected path: %r' % path)
            else:
                self._open(path, fh)
                u = self.__open_files.get(fh, None)
                if u is None:
                    raise RuntimeError('unexpected path: %r' % path)

        if offset + size > start_id3v1tag:
            temp_buf = u.read(start_id3v1tag - offset)
            if len(temp_buf) < start_id3v1tag - offset:
                diff = start_id3v1tag - offset - len(temp_buf)
                temp_buf += '\0' * diff
            buf += temp_buf
            buf += id3v1data[:size - (start_id3v1tag - offset)]
            try:
                u.bytes_read += (start_id3v1tag - offset)
            except AttributeError:
                pass
        else:
            temp_buf = u.read(size)
            if len(temp_buf) < size:
                diff = size - len(temp_buf)
                temp_buf += '\0' * diff
            buf += temp_buf
            try:
                u.bytes_read += size
            except AttributeError:
                # Only urllib2 files need this attribute, harmless to
                # ignore it.
                pass
        return buf

    def readdir(self, path, fh):
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)

        if path == '/':
            return ['.', '..', 'artists']
        elif path == '/artists':
            return  ['.','..'] + self.library.get_artists().keys()
        elif artist_dir_m:
            # Artist directory, lists albums.
            albums = self.library.get_artist_albums(
                artist_dir_m.groupdict()['artist'])
            # Sort albums by year:
            album_dirs = []
            for a in albums.values():
                album_dirs.append(u'{year:04d}_{name}'.format(year=a.get_year(), name=formatNames(a.normtitle)))
            return ['.','..'] + album_dirs
        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            files = ['.','..']
            for track in album.get_tracks(get_size=True):
                track = album.calc_size(track)
                files.append('%02d_%s.mp3' % (track['trackNumber'], formatNames(track['title'])))
            return files


def getDeviceId(verbose=False):
    cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs')
    if not os.path.isfile(cred_path):
        raise NoCredentialException(
            'No username/password was specified. No config file could '
            'be found either. Try creating %s and specifying your '
            'username/password there. Make sure to chmod 600.'
            % cred_path)
    if not oct(os.stat(cred_path)[os.path.stat.ST_MODE]).endswith('00'):
        raise NoCredentialException(
            'Config file is not protected. Please run: '
            'chmod 600 %s' % cred_path)
    config = ConfigParser.ConfigParser()
    config.read(cred_path)
    username = config.get('credentials','username')
    password = config.get('credentials','password')
    if not username or not password:
        raise NoCredentialException(
            'No username/password could be read from config file'
            ': %s' % cred_path)

    api = GoogleMusicWebAPI(debug_logging=verbose)
    log.info('Logging in...')
    api.login(username, password)
    log.info('Login successful.')

    for device in api.get_registered_devices():
        if not device['name']:
            device['name']='NoName'
        if device['id'][1]=='x':
            print '%s : %s' % (device['name'], device['id'])

def main():
    log.setLevel(logging.WARNING)
    logging.getLogger('gmusicapi').setLevel(logging.WARNING)
    logging.getLogger('fuse').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description='GMusicFS', add_help=False)
    parser.add_argument('--deviceid', action='store_true', dest='deviceId')

    args = parser.parse_known_args()

    if args[0].deviceId:
        getDeviceId()
        return

    parser = argparse.ArgumentParser(description='GMusicFS')
    parser.add_argument('mountpoint', help='The location to mount to')
    parser.add_argument('-f', '--foreground', dest='foreground',
                        action="store_true",
                        help='Don\'t daemonize, run in the foreground.')
    parser.add_argument('-v', '--verbose', help='Be a little verbose',
                        action='store_true', dest='verbose')
    parser.add_argument('-vv', '--veryverbose', help='Be very verbose',
                        action='store_true', dest='veryverbose')
    parser.add_argument('-t', '--truefilesize', help='Report true filesizes'
                        ' (slower directory reads)',
                        action='store_true', dest='true_file_size')
    parser.add_argument('--allusers', help='Allow all system users access to files'
                        ' (Requires user_allow_other set in /etc/fuse.conf)',
                        action='store_true', dest='allusers')
    parser.add_argument('--nolibrary', help='Don\'t scan the library at launch',
                        action='store_true', dest='nolibrary')
    parser.add_argument('--deviceid', help='Get the device ids bounded to your account',
                        action='store_true', dest='deviceId')

    args = parser.parse_args()

    mountpoint = os.path.abspath(args.mountpoint)

    # Set verbosity:
    if args.veryverbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('gmusicapi').setLevel(logging.DEBUG)
        logging.getLogger('fuse').setLevel(logging.DEBUG)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 10
    elif args.verbose:
        log.setLevel(logging.INFO)
        logging.getLogger('gmusicapi').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.INFO)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 1
    else:
        log.setLevel(logging.WARNING)
        logging.getLogger('gmusicapi').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.WARNING)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 0




    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, scan_library= not args.nolibrary)
    try:
        fuse = FUSE(fs, mountpoint, foreground=args.foreground,
                    ro=True, nothreads=True, allow_other=args.allusers)
    finally:
        fs.cleanup()

if __name__ == '__main__':
    main()
