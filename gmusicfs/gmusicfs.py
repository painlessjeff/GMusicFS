#!/usr/bin/env python2

import os
import re
import sys
import struct
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
import pprint

from eyed3.id3 import Tag
from eyed3.id3 import ID3_V1_0, ID3_V1_1, ID3_V2_3, ID3_V2_4

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
from gmusicapi import Mobileclient as GoogleMusicAPI
from gmusicapi import Webclient as GoogleMusicWebAPI

import fifo

reload(sys) # Reload does the trick
sys.setdefaultencoding('UTF-8')

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
deviceId = None
pp = pprint.PrettyPrinter(indent=4) # For debug logging

# Size of the ID3v1 trailer appended to the mp3 file (at read time)
# Add the size to the reported size of the mp3 file so read function receive correct params.
# The read function will read size bytes - 128 since we have to generate this 128 bytes.
ID3V1_TRAILER_SIZE = 128

def formatNames(string_from):
<<<<<<< HEAD
    """Format a name to make it suitable to use as a filename"""
    return re.sub('/', '-', string_from)

=======
    string_from = string_from.replace(": ", " - ")
    string_from = string_from.replace(":", "-")
    string_from = re.sub("[/]", '-', string_from)
    string_from = re.sub("[\?\"\`]", '', string_from)
    return string_from
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

class NoCredentialException(Exception):
    pass

class Playlist(object):
    """This class manages playlist information"""

    def __init__(self, library, pldata):
        self.library = library
        self.__filename_re = re.compile('^([0-9]+) - [^/]+\.mp3$')

        self.realname = pldata['name']
        self.dirname = formatNames(self.realname).strip()
        log.debug('New playlist: %s' % self.realname)

        self.__tracks = []
        for entry in pldata['tracks']:
            log.debug('Playlist entry: %s' % pp.pformat(entry))
            if 'track' in entry:
                track = entry['track']
                track['id'] = entry['trackId']
            else:
                track = self.library.get_track(entry['trackId'])
            self.__tracks.append(track)

    def get_tracks(self, get_size=False):
        """Return the list of tracks, in order, that comprise the playlist"""
        # TODO Converge implementation by creating a Track class?
        #      It could get the size only on demand per-track
        # Retrieve and remember the filesize of each track:
        if get_size and self.library.true_file_size:
            for t in self.__tracks:
                if not 'bytes' in t:
                    r = urllib2.Request(self.get_track_stream(t)[0])
                    r.get_method = lambda: 'HEAD'
                    u = urllib2.urlopen(r)
                    t['bytes'] = int(u.headers['Content-Length']) + ID3V1_TRAILER_SIZE
        return self.__tracks

    def get_track(self, filename):
        """Return the track that corresponds to a filename from this playlist"""
        m = self.__filename_re.match(filename)
        if m:
            tracknum = int(m.groups()[0])
            return self.__tracks[tracknum - 1]
        return None

    def get_track_stream(self, track):
        """Return the track stream URL"""
        return self.library.api.get_stream_url(track['id'], deviceId)

    def __repr__(self):
        return u'<Playlist \'{name}\'>'.format(name=self.realname)

class Artist(object):
    """This class manages artist information"""

    def __init__(self, library, name):
        self.library = library
        self.realname = name
        self.dirname = formatNames(name)
        self.__albums = {}

    def add_album(self, album):
        """Add an album to the artist"""
        self.__albums[album.normtitle.lower()] = album

    def get_albums(self):
        """Return a list of all the albums by the artist"""
        return self.__albums.values()

    def get_album(self, title):
        """Return a specific album from the set that belongs to the artist"""
        return self.__albums.get(title.lower(), None)

    def __repr__(self):
        return u'<Artist \'{name}\'>'.format(name=self.realname)

class Album(object):
<<<<<<< HEAD
    """This class manages album information"""

    def __init__(self, library, title):
        self.library = library
        self.realtitle = title
        self.normtitle = formatNames(self.realtitle)
        self.__tracks = []
        self.__sorted = True
        self.__filename_re = re.compile("^[0-9]+ - (.*)\.mp3$")

    def add_track(self, track):
        """Add a track to the album"""
=======
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
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
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
        """Return a sorted list of tracks in the album"""
        # Re-sort by track number
        if not self.__sorted:
            self.__tracks.sort(key=lambda t: t.get('track'))
<<<<<<< HEAD
        # Retrieve and remember the filesize of each track
        if get_size and self.library.true_file_size:
            for t in self.__tracks:
                if not 'bytes' in t:
                    r = urllib2.Request(self.get_track_stream(t))
                    r.get_method = lambda: 'HEAD'
                    u = urllib2.urlopen(r)
                    t['bytes'] = int(u.headers['Content-Length']) + ID3V1_TRAILER_SIZE
=======
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
        return self.__tracks

    def get_track(self, filename):
        """Get the track name corresponding to a filename
        (eg. '001 - brilliant track name.mp3')"""
        m = self.__filename_re.match(filename)
        if m:
            title = m.groups()[0]
            for track in self.get_tracks():
<<<<<<< HEAD
                if formatNames(track['title'].lower()) == title.lower():
=======
                if formatNames(track['title']) == title:
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
                    return track
        return None

    def get_track_stream(self, track):
        """Return the track stream URL"""
        return self.library.api.get_stream_url(track['id'], deviceId)

    def get_cover_url(self):
        """Return the album cover image URL"""
        try:
            # Assume the first track has the right cover URL
            url = "%s" % self.__tracks[0]['albumArtRef'][0]['url']
        except:
            url = None
        return url
        
    def get_cover_size(self):
        """Return the album cover size"""
	if self.library.true_file_size:
	    r = urllib2.Request(self.get_cover_url())
	    r.get_method = lambda: 'HEAD'
	    u = urllib2.urlopen(r)
	    return int(u.headers['Content-Length'])
	return None
	    
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
    """This class reads information about your Google Play Music library"""

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
        self.__tracks = {}
        self.__playlists = {}
        if scan:
            self.rescan()
        self.true_file_size = true_file_size

    def rescan(self):
        """Scan the Google Play Music library"""
        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__albums = [] # [Album(), ...]
<<<<<<< HEAD
        self.__tracks = {}
        self.__playlists = {}
=======
        self.__galbums = {}
        self.__gartists = {}
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
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
            if deviceId.startswith("0x"):
                deviceId = deviceId[2:]

        self.api = GoogleMusicAPI(debug_logging=self.verbose)
        log.info('Logging in...')
        self.api.login(username, password, deviceId)
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
<<<<<<< HEAD
        """Get all the tracks and playlists in the library, parse into relevant dicts"""
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        for track in tracks:
            log.debug('track = %s' % pp.pformat(track))

            # Prefer the album artist over the track artist if there is one
            artist_name = formatNames(track['albumArtist'])
            if artist_name.strip() == '':
                artist_name = formatNames(track['artist'])
            if artist_name.strip() == '':
                artist_name = 'Unknown'

            # Get the Artist object, or create one if it doesn't exist
            artist = self.__artists.get(artist_name.lower(), None)
            if not artist:
                artist = Artist(self, artist_name)
                self.__artists[artist_name.lower()] = artist

            # Get the Album object, or create one if it doesn't exist
            album = artist.get_album(formatNames(track['album']))
            if not album:
                album = Album(self, track['album'])
                self.__albums.append(album) # NOTE: Current no purpose other than to count
                artist.add_album(album)

            # Add track to album
            album.add_track(track)

            # Add track to list of all tracks, indexable by track ID
            if 'id' in track:
                self.__tracks[track['id']] = track
=======
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
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

        log.debug('%d tracks loaded.' % len(tracks))
        log.debug('%d artists loaded.' % len(self.__artists))
        log.debug('%d albums loaded.' % len(self.__albums))

        # Add all playlists
        playlists = self.api.get_all_user_playlist_contents()
        for pldata in playlists:
            playlist = Playlist(self, pldata)
            self.__playlists[playlist.dirname.lower()] = playlist
        log.debug('%d playlists loaded.' % len(self.__playlists))

    def get_artists(self):
        """Return list of all artists in the library"""
        return self.__artists.values()

    def get_artist(self, name):
        """Return the artist from the library with the specified name"""
        return self.__artists.get(name.lower(), None)

    def get_playlists(self):
        """Return list of all playlists in the library"""
        return self.__playlists.values()

    def get_playlist(self, name):
        """Return the playlist from the library with the specified name"""
        return self.__playlists.get(name.lower(), None)

    def get_track(self, trackid):
        """Return the track from the library with the specified track ID"""
        return self.__tracks.get(trackid, None)

    def cleanup(self):
        pass

class GMusicFS(LoggingMixIn, Operations):
    """Google Music Filesystem"""

    def __init__(self, path, username=None, password=None,
                 true_file_size=False, verbose=0, scan_library=True,
                 lowercase=True):
        Operations.__init__(self)
        self.artist_dir = re.compile('^/artists/(?P<artist>[^/]+)$')
        self.artist_album_dir = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4})_(?P<album>[^/]+)$')
        self.artist_album_track = re.compile(
<<<<<<< HEAD
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4}) - (?P<album>[^/]+)/(?P<track>[^/]+\.mp3)$')
        self.artist_album_image = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4}) - (?P<album>[^/]+)/(?P<image>[^/]+\.jpg)$')
        self.playlist_dir = re.compile('^/playlists/(?P<playlist>[^/]+)$')
        self.playlist_track = re.compile(
            '^/playlists/(?P<playlist>[^/]+)/(?P<track>[^/]+\.mp3)$')
=======
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4})_(?P<album>[^/]+)/(?P<track>[^/]+\.mp3)$')
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

        self.__open_files = {} # path -> urllib2_obj
        self.__urls = {}       # path -> url
        self.__tags = {}       # fh -> (id3v1, id3v2)

        # Define transformation based on whether lowercase filenames will be used or not
        if lowercase:
            self.transform = lambda x: x.lower()
        else:
            self.transform = lambda x: x

        # Login to Google Play Music and parse the tracks:
        self.library = MusicLibrary(username, password,
                                    true_file_size=true_file_size, verbose=verbose, scan=scan_library)
        log.info("Filesystem ready : %s" % path)

    def cleanup(self):
        self.library.cleanup()

    def track_to_stat(self, track, st = {}):
        """Construct and results stat information based on a track"""
        # TODO This could be moved into a Track class in the future
        st['st_mode'] = (S_IFREG | 0444)
        st['st_size'] = int(track['estimatedSize'])
        if 'bytes' in track:
            st['st_size'] = int(track['bytes'])
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = 0
        if 'creationTimestamp' in track:
            st['st_ctime'] = st['st_mtime'] = int(track['creationTimestamp']) / 1000000
        if 'recentTimestamp' in track:
            st['st_atime'] = int(track['recentTimestamp']) / 1000000
        return st

    def getattr(self, path, fh=None):
        """Get information about a file or directory"""
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)
<<<<<<< HEAD
        artist_album_image_m = self.artist_album_image.match(path)
        playlist_dir_m = self.playlist_dir.match(path)
        playlist_track_m = self.playlist_track.match(path)
=======
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

        # Default to a directory
        st = {
            'st_mode' : (S_IFDIR | 0755),
            'st_size' : 1,
            'st_nlink' : 2 }
        date = 0 # Make the date really old, so that cp -u works correctly.
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date

        if path == '/':
            pass
        elif path == '/artists':
<<<<<<< HEAD
            pass
        elif path == '/playlists':
            pass
=======
            st['st_size'] = len(self.library.get_artists())
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
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
<<<<<<< HEAD
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            track = album.get_track(parts['track'])
            st = self.track_to_stat(track)
        elif artist_album_image_m:
            parts = artist_album_image_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            cover_size = album.get_cover_size()
            if cover_size is None:
            	cover_size = 10000000
            st = {
                'st_mode' : (S_IFREG | 0444),
                'st_size' : cover_size }
        elif playlist_dir_m:
            pass
        elif playlist_track_m:
            parts = playlist_track_m.groupdict()
            playlist = self.library.get_playlist(parts['playlist'])
            track = playlist.get_track(parts['track'])
            st = self.track_to_stat(track)
=======
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
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
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
        """Open a file (track or cover image) and return a filehandle"""

        artist_album_track_m = self.artist_album_track.match(path)
<<<<<<< HEAD
        artist_album_image_m = self.artist_album_image.match(path)
        playlist_track_m = self.playlist_track.match(path)
=======
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

        if artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            track = album.get_track(parts['track'])
<<<<<<< HEAD
            url = album.get_track_stream(track)
        elif artist_album_image_m:
            parts = artist_album_image_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            url = album.get_cover_url()
        elif playlist_track_m:
            parts = playlist_track_m.groupdict()
            playlist = self.library.get_playlist(parts['playlist'])
            track = playlist.get_track(parts['track'])
            url = self.library.api.get_stream_url(track['id'], deviceId)
=======
            if not track.has_key('tagSize'):
                track = album.calc_size(track)

            self.__urls[fh] = (album, track)
            self.__tags[fh] = (album.gen_tag(track))
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
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
<<<<<<< HEAD
            raise RuntimeError('unexpected path: %r' % path)
        artist_album_track_m = self.artist_album_track.match(path)
        if artist_album_track_m and (int(u.headers['Content-Length']) < (offset + size)):
            parts = artist_album_track_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            track = album.get_track(parts['track'])
            # Genre tag is always set to Other as Google MP3 genre tags are not id3v1 id.
            id3v1 = struct.pack("!3s30s30s30s4s30sb", 'TAG', str(track['title']), str(track['artist']),
        	                str(track.get('album','')), str(0), str(track.get('comment','')), 12)
            buf = u.read(size - ID3V1_TRAILER_SIZE) + id3v1
        else:
            buf = u.read(size)
            
        try:
            u.bytes_read += size
        except AttributeError:
            # Only urllib2 files need this attribute, harmless to
            # ignore it.
            pass
=======
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
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
        return buf

    def readdir(self, path, fh):
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)
<<<<<<< HEAD
        artist_album_image_m = self.artist_album_image.match(path)
        playlist_dir_m = self.playlist_dir.match(path)
=======
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6

        if path == '/':
            return ['.', '..', 'artists', 'playlists']
        elif path == '/artists':
            artist_dirs = map((lambda a: self.transform(a.dirname)), self.library.get_artists())
            return  ['.','..'] + artist_dirs
        elif path == '/playlists':
            playlist_dirs = map((lambda p: self.transform(p.dirname)), self.library.get_playlists())
            return  ['.','..'] + playlist_dirs
        elif artist_dir_m:
            # Artist directory, lists albums.
            parts = artist_dir_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            albums = artist.get_albums()
            # Sort albums by year:
<<<<<<< HEAD
            album_dirs = [u'{year:04d} - {name}'.format(
                year=a.get_year(), name=self.transform(a.normtitle)) for a in albums]
=======
            album_dirs = []
            for a in albums.values():
                album_dirs.append(u'{year:04d}_{name}'.format(year=a.get_year(), name=formatNames(a.normtitle)))
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
            return ['.','..'] + album_dirs
        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            artist = self.library.get_artist(parts['artist'])
            album = artist.get_album(parts['album'])
            files = ['.','..']
            for track in album.get_tracks(get_size=True):
<<<<<<< HEAD
                files.append('%03d - %s.mp3' %
                    (track['trackNumber'], self.transform(formatNames(track['title']))))
            # Include cover image:
            cover = album.get_cover_url()
            if cover:
                files.append('cover.jpg')
=======
                track = album.calc_size(track)
                files.append('%02d_%s.mp3' % (track['trackNumber'], formatNames(track['title'])))
>>>>>>> 556157a0ec707fed62dd1323aa55ccebd3fe31a6
            return files
        elif playlist_dir_m:
            parts = playlist_dir_m.groupdict()
            playlist = self.library.get_playlist(parts['playlist'])
            files = ['.', '..']
            tracknum = 1
            for track in playlist.get_tracks():
                files.append(self.transform(formatNames('%03d - %s - %s - %s.mp3' % (tracknum, track['artist'], track['album'], track['title']))))
                tracknum += 1
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
            device['name'] = 'NoName'
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
    parser.add_argument('-l', '--lowercase', help='Convert all path elements to lowercase',
                        action='store_true', dest='lowercase')

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

    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, scan_library= not args.nolibrary, lowercase=args.lowercase)
    try:
        fuse = FUSE(fs, mountpoint, foreground=args.foreground,
                    ro=True, nothreads=True, allow_other=args.allusers)
    finally:
        fs.cleanup()

if __name__ == '__main__':
    main()
