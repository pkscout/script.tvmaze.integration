# -*- coding: utf-8 -*-
# *  Credits:
# *
# *  original TV Maze Integration code by pkscout

from kodi_six import xbmc
import json, os, sys, time
from resources.lib.apis import tvmaze
from resources.lib.fileops import readFile, writeFile
from resources.lib.xlogger import Logger
from resources.lib.tvmisettings import loadSettings

def _upgrade():
    settings = loadSettings()
    if settings['version_upgrade'] != settings['ADDONVERSION']:
        settings['ADDON'].setSetting( 'version_upgrade', settings['ADDONVERSION'] )

def _logsafe_settings( settings ):
    show_in_log = settings.copy()
    show_in_log.pop( 'tvmaze_user', '' )
    show_in_log.pop( 'tvmaze_apikey', '' )
    return show_in_log



class tvmManual:

    def __init__( self ):
        """Runs the audio profiler switcher manually."""
        settings = loadSettings()
        lw = Logger( preamble='[TVMI Manual]', logdebug=settings['debug'] )
        lw.log( ['script version %s started' % settings['ADDONVERSION']], xbmc.LOGINFO )
        lw.log( ['debug logging set to %s' % settings['debug']], xbmc.LOGINFO )
        lw.log( ['SYS.ARGV: %s' % str(sys.argv)] )
        lw.log( ['loaded settings', _logsafe_settings( settings )] )
        self.TVMAZE = tvmaze.API( user=self.SETTINGS['tvmaze_user'], apikey=self.SETTINGS['tvmaze_apikey'] )
        lw.log( ['script version %s stopped' % settings['ADDONVERSION']], xbmc.LOGINFO )



class tvmMonitor( xbmc.Monitor ):

    def __init__( self ):
        """Starts the background process for automatic marking of played TV shows."""
        xbmc.Monitor.__init__( self )
        _upgrade()
        self._init_vars()
        self.LW.log( ['background monitor version %s started' % self.SETTINGS['ADDONVERSION']], xbmc.LOGINFO )
        self.LW.log( ['debug logging set to %s' % self.SETTINGS['debug']], xbmc.LOGINFO )
        while not self.abortRequested():
            if self.waitForAbort( 10 ):
                break
            if self.PLAYINGVIDEO:
                self.PLAYINGVIDEOTIME = self.KODIPLAYER.getTime()
        self.LW.log( ['background monitor version %s stopped' % self.SETTINGS['ADDONVERSION']], xbmc.LOGINFO )


    def onNotification( self, sender, method, data ):
        if 'Player.OnPlay' in method:
            self.waitForAbort( 1 )
            if self.KODIPLAYER.isPlayingVideo():
                data = json.loads( data )
                is_a_file = not self.KODIPLAYER.getPlayingFile().startswith(('plugin://','upnp://','pvr://'))
                is_an_episode = data.get( 'item', {} ).get( 'type', '' ) == 'episode'
                if is_a_file and is_an_episode:
                    self.LW.log( ['MONITOR METHOD: %s DATA: %s' % (str( method ), str( data ))] )
                    self.PLAYINGVIDEO = True
                    self.PLAYINGVIDEOTOTALTIME = self.KODIPLAYER.getTotalTime()
                    self._get_show_ep_info( 'playing', data )
        elif 'Player.OnStop' in method and self.PLAYINGVIDEO:
            if self.PLAYINGVIDEO:
                self.PLAYINGVIDEO = False
                data = json.loads( data )
                self.LW.log( ['MONITOR METHOD: %s DATA: %s' % (str( method ), str( data ))] )
                played_percentage = (self.PLAYINGVIDEOTIME / self.PLAYINGVIDEOTOTALTIME) * 100
                self.LW.log( ['got played percentage of %s' % str( played_percentage )], xbmc.LOGNOTICE )
                if played_percentage >= float( self.SETTINGS['percent_watched'] ):
                    self.LW.log( ['item was played for the minimum percentage in settings, trying to mark'], xbmc.LOGNOTICE )
                    self._mark_episodes( 'playing' )
                else:
                    self.LW.log( ['item was not played long enough to be marked, skipping'] )
                self._reset_playing()
        elif 'VideoLibrary.OnScanStarted' in method:
            data = json.loads( data )
            self.LW.log( ['MONITOR METHOD: %s DATA: %s' % (str( method ), str( data ))] )
            self.SCANSTARTED = True
        elif 'VideoLibrary.OnUpdate' in method and self.SCANSTARTED:
            data = json.loads( data )
            self.LW.log( ['MONITOR METHOD: %s DATA: %s' % (str( method ), str( data ))] )
            self._get_show_ep_info( 'scanned', data )
        elif 'VideoLibrary.OnScanFinished' in method and self.SCANSTARTED:
            data = json.loads( data )
            self.LW.log( ['MONITOR METHOD: %s DATA: %s' % (str( method ), str( data ))] )
            self._mark_episodes( 'scanned' )
            self._reset_scanned()


    def onSettingsChanged( self ):
        self._init_vars()


    def _init_vars( self ):
        self.SETTINGS = loadSettings()
        self.LW = Logger( preamble='[TVMI Monitor]', logdebug=self.SETTINGS['debug'] )
        self.LW.log( ['the settings are:', _logsafe_settings( self.SETTINGS )] )
        self.TVMCACHEFILE = os.path.join( self.SETTINGS['ADDONDATAPATH'], 'tvm_followed_cache.json' )
        self.KODIPLAYER = xbmc.Player()
        self.TVMAZE = tvmaze.API( user=self.SETTINGS['tvmaze_user'], apikey=self.SETTINGS['tvmaze_apikey'] )
        self._load_followed_cache()
        self._load_show_overrides()
        self._reset_playing()
        self._reset_scanned()
        self.LW.log( ['initialized variables'] )


    def _reset_playing( self ):
        self.PLAYINGVIDEO = False
        self.PLAYINGITEMS = []
        self.PLAYINGVIDEOTIME = 0
        self.PLAYINGVIDEOTOTALTIME = 0


    def _reset_scanned( self ):
        self.SCANSTARTED = False
        self.SCANNEDITEMS = []


    def _load_followed_cache( self ):
        loglines, results = readFile( self.TVMCACHEFILE )
        self.LW.log( loglines )
        try:
            self.TVMCACHE = json.loads( results )
        except ValueError:
            self.TVMCACHE = []


    def _update_followed_cache( self, showname ):
        self._load_show_overrides()
        self._add_followed( showname )
        success, loglines, results = self.TVMAZE.getFollowedShows( params={'embed':'show'} )
        self.LW.log( loglines )
        if success:
            self.TVMCACHE = results
        else:
            self.LW.log( ['no valid response returned from TV Maze'] )
            self.TVMCACHE = []
        if self.TVMCACHE:
            success, loglines = writeFile( json.dumps( self.TVMCACHE ), self.TVMCACHEFILE, wtype='w' )
            self.LW.log( loglines )


    def _add_followed( self, showname ):
        success, loglines, result = self.TVMAZE.findSingleShow( showname )
        self.LW.log( loglines )
        if success:
            showid = result.get( 'id', 0 )
            if showid:
                success, loglines, result = self.TVMAZE.followShow( showid )
                self.LW.log( loglines )
        return


    def _load_show_overrides( self ):
        loglines, results = readFile( os.path.join( self.SETTINGS['ADDONDATAPATH'], 'show_override.json' ) )
        self.LW.log( loglines )
        try:
            self.SHOWOVERRIDES = json.loads( results )
        except ValueError:
            self.SHOWOVERRIDES = {}


    def _get_show_ep_info( self, thetype, data ):
        showid = 0
        epid = 0
        showname = ''
        if data.get( 'item', {} ).get( 'type', '' ) == 'episode':
            epid = data['item'].get( 'id', 0 )
        if epid:
            method = 'VideoLibrary.GetEpisodeDetails'
            params = '{"episodeid":%s, "properties":["season", "episode", "tvshowid"]}' % str( epid )
            r_dict = self._get_json( method, params )
            season = r_dict.get( 'episodedetails', {} ).get( 'season', 0 )
            episode = r_dict.get( 'episodedetails', {} ).get( 'episode', 0 )
            showid = r_dict.get( 'episodedetails', {} ).get( 'tvshowid', 0 )
            self.LW.log( ['moving on with season of %s, episode of %s, and showid of %s' % (str(season), str(episode), str(showid))] )
            if showid:
                method = 'VideoLibrary.GetTVShowDetails'
                params = '{"tvshowid":%s}' % str( showid )
                r_dict = self._get_json( method, params )
                showname = r_dict.get( 'tvshowdetails', {} ).get( 'label', '' )
                self.LW.log( ['moving on with TV show name of %s' % showname] )
        if showname and season and episode:
            item = {'name':showname, 'season':season, 'episode':episode}
        else:
            item = {}
        if item:
            self.LW.log( ['storing item data of:', item] )
            if thetype == 'scanned':
                self.SCANNEDITEMS.append( item )
            elif thetype == 'playing':
                self.PLAYINGITEMS.append( item )


    def _get_json( self, method, params ):
        json_call = '{"jsonrpc":"2.0", "method":"%s", "params":%s, "id":1}' % (method, params)
        self.LW.log( ['sending: %s' % json_call ])
        response = xbmc.executeJSONRPC( json_call )
        self.LW.log( ['the response was:', response] )
        try:
            r_dict = json.loads( response )
        except ValueError:
            r_dict = {}
        return r_dict.get( 'result', {} )


    def _mark_episodes( self, thetype ):
        mark_type = 0
        items = self.PLAYINGITEMS
        if thetype == 'scanned':
            mark_type = 1
            items = self.SCANNEDITEMS
        for item in items:
            self._mark_one( item, mark_type )


    def _mark_one( self, show_info, mark_type ):
        self.LW.log( ['starting process to mark show as acquired'] )
        tvmazeid = ''
        if show_info:
            self.LW.log( ['show info found'] )
            if self.TVMCACHE:
                self.LW.log( ['trying with cached TV Maze information first'] )
                tvmazeid = self._match_from_followed_shows( show_info )
            if not tvmazeid:
                self.LW.log( ['no match, getting updated followed shows from TV Maze'] )
                self._update_followed_cache( show_info['name'] )
                if self.TVMCACHE:
                    self.LW.log( ['trying again with updated list of followed shows'] )
                    tvmazeid = self._match_from_followed_shows( show_info )
            if tvmazeid:
                self.LW.log( ['found tvmazeid of %s' % tvmazeid, 'attempting to get episode id'] )
                params = {'season':show_info['season'], 'number':show_info['episode']}
                success, loglines, results = self.TVMAZE.getEpisodeBySeasonEpNumber( tvmazeid, params )
                self.LW.log( loglines )
                if not success:
                    self.LW.log( ['no valid response returned from TV Maze, aborting'] )
                    return
                try:
                    episodeid = results['id']
                except KeyError:
                    episodeid = ''
                if episodeid:
                    self.LW.log( ['got back episode id of %s' % episodeid, 'marking episode as acquired on TV Maze'] )
                    success, loglines, results = self.TVMAZE.markEpisode( episodeid, marked_as=mark_type )
                    self.LW.log( loglines )
                    if not success:
                        self.LW.log( ['no valid response returned from TV Maze, show was not marked'] )
                else:
                    self.LW.log( ['no episode id found'] )
            else:
                self.LW.log( ['no tvmazeid found'] )
        else:
            self.LW.log( ['no show information from Kodi'] )


    def _match_from_followed_shows( self, show_info ):
        tvmazeid = ''
        self.LW.log( ['checking to see if there is an override for %s' % show_info['name']] )
        try:
            show_info['name'] = self.SHOWOVERRIDES[show_info['name']]
        except KeyError:
            self.LW.log( ['no show override found, using original'] )
        self.LW.log( ['using show name of %s' % show_info['name']] )
        for followed_show in self.TVMCACHE:
            followed_name = followed_show['_embedded']['show']['name']
            self.LW.log( ['checking for %s matching %s' % (show_info['name'], followed_name)] )
            if followed_name == show_info['name']:
                self.LW.log( ['found match for %s' % show_info['name'] ] )
                tvmazeid = followed_show['show_id']
                break
        return tvmazeid
