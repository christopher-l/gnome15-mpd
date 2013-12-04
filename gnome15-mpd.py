#        +-----------------------------------------------------------------------------+
#        | GPL                                                                         |
#        +-----------------------------------------------------------------------------+
#        | Copyright (c) Christopher Luebbemeier                                       |
#        |                                                                             |
#        | This program is free software; you can redistribute it and/or               |
#        | modify it under the terms of the GNU General Public License                 |
#        | as published by the Free Software Foundation; either version 2              |
#        | of the License, or (at your option) any later version.                      |
#        |                                                                             |
#        | This program is distributed in the hope that it will be useful,             |
#        | but WITHOUT ANY WARRANTY; without even the implied warranty of              |
#        | MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the               |
#        | GNU General Public License for more details.                                |
#        |                                                                             |
#        | You should have received a copy of the GNU General Public License           |
#        | along with this program; if not, write to the Free Software                 |
#        | Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA. |
#        +-----------------------------------------------------------------------------+

import gnome15.g15screen as g15screen 
import gnome15.g15theme as g15theme 
#import gnome15.g15util as g15util
import gnome15.util.g15scheduler as g15scheduler
import gnome15.g15driver as g15driver
#import gnome15.g15globals as g15globals
import gnome15.g15text as g15text
import gtk
import os
#import sys
#import pango
from mpd import (MPDClient, MPDError, CommandError, ConnectionError)
from socket import error as SocketError

# Plugin details
id="gnome15-mpd"
name="MPD"
description="Allows to control the Music Player Daemon " \
         +  "and displays some status information."
author="Christopher Luebbemeier"
copyright="Copyright (C)2011 Christopher Luebbemeier"
site="http://www.gnome15.org/"
has_preferences=True
unsupported_models = [ g15driver.MODEL_G110, g15driver.MODEL_G11, g15driver.MODEL_G19 ]
actions={ 
         g15driver.PREVIOUS_SELECTION : "Previous Song / Vol -", 
         g15driver.NEXT_SELECTION : "Next Song / Vol +",
         g15driver.SELECT : "Play / Pause",
         g15driver.VIEW : "Volume",
         }

def create(gconf_key, gconf_client, screen):
    return G15mpd(gconf_key, gconf_client, screen)

def show_preferences(parent, driver, gconf_client, gconf_key):
    widget_tree = gtk.Builder()
    widget_tree.add_from_file(os.path.join(os.path.dirname(__file__), "gnome15-mpd.glade"))
    
    dialog = widget_tree.get_object("MPDdialog")
    dialog.set_transient_for(parent)
    
    host = widget_tree.get_object("hostname")
    host.set_text(gconf_client.get_string(gconf_key + "/host") or "localhost")
    host.connect("changed", _changed, gconf_key + "/host", gconf_client)
    
    port = widget_tree.get_object("port_adjustment")
    port.set_value(gconf_client.get_int(gconf_key + "/port") or 6600)
    port.connect("value-changed", _value_changed, gconf_key + "/port", gconf_client)

    password = widget_tree.get_object("password")
    password.set_text(gconf_client.get_string(gconf_key + "/password") or "")
    password.connect("changed", _changed, gconf_key + "/password", gconf_client)

    vol_steps = widget_tree.get_object("volume_adjustment")
    vol_steps.set_value(gconf_client.get_int(gconf_key + "/vol_steps") or 10)
    vol_steps.connect("value-changed", _value_changed, gconf_key + "/vol_steps", gconf_client)
    
    dialog.run()
    dialog.hide()

def _changed(widget, gconf_key, gconf_client):
    gconf_client.set_string(gconf_key, widget.get_text())

def _value_changed(widget, gconf_key, gconf_client):
    gconf_client.set_int(gconf_key, int(widget.get_value()))

class G15mpd():

    _mpd_client = MPDClient()
    host = None
    port = None
    password = None
    vol_steps = None
    _connected = None
    _mode_vol = False
    _state = None

    def __init__(self, gconf_key, gconf_client, screen):
        self.screen = screen
        self.hidden = False
        self.gconf_client = gconf_client
        self.gconf_key = gconf_key
        self.page = None

    def activate(self):
        self._load_configuration()
        self._connect()
        self.timer = None 
        self.text = g15text.new_text(self.screen)
        self._reload_theme()
        self.page = g15theme.G15Page("MPD", self.screen,
                                     theme_properties_callback = self._get_properties,
#                                     thumbnail_painter = self.paint_thumbnail, panel_painter = self.paint_thumbnail,
                                     theme = self.theme)
        self.page.title = "MPD"
        self.screen.action_listeners.append(self)
        self.screen.add_page(self.page)
        self.screen.redraw(self.page)
        self._schedule_redraw()
        self.notify_handle = self.gconf_client.notify_add(self.gconf_key, self._config_changed)

    def deactivate(self):
        if self._connected:
            self._mpd_client.disconnect()
        self.gconf_client.notify_remove(self.notify_handle);
        if self.timer != None:
            self.timer.cancel()
            self.timer = None
        self.screen.del_page(self.page)

    def destroy(self):
        pass

    def _connect(self):
        try:
            self._mpd_client.connect(**{'host':self.host, 'port':self.port})
            self._connected = True
        except (SocketError, ConnectionError):
            self._connected = False
            return False
        if self.password:
            try:
                self._mpd_client.password(self.password)
            except CommandError:
                return False
        return True

    def _config_changed(self, client=None, connection_id=None, entry=None, args=None):
        self._load_configuration()
        try:
            self._mpd_client.disconnect()
        except (MPDError, IOError):
            pass
        self._connect()
        self._reload_theme()
#        self.page.set_theme(self.theme)
        self.screen.set_priority(self.page, g15screen.PRI_HIGH, revert_after = 3.0)

    def _load_configuration(self):
        host = self.gconf_client.get_string(self.gconf_key + "/host")
        self.host = host if host else 'localhost'
        port = self.gconf_client.get_int(self.gconf_key + "/port")
        self.port = port if port else 6600
        self.password = self.gconf_client.get_string(self.gconf_key + "/password")
        vol_steps = self.gconf_client.get_int(self.gconf_key + "/vol_steps")
        self.vol_steps = vol_steps if vol_steps else 10

    def _reload_theme(self):
        variant = None
        if self._connected:
            if self._mpd_client.status()['state'] == 'play':
                variant = 'playing'
            if self._mode_vol:
                variant = 'vol'
        else:
            variant = 'no_connection'
        self.theme = g15theme.G15Theme(os.path.join(os.path.dirname(__file__), "default"), variant)
        if self.page:
            self.page.set_theme(self.theme)

    def _get_properties(self):
        properties = { }
        if self._connected:
            try:
                properties = self._mpd_client.currentsong()
                # radio station, dirty yet
                if not 'title' in properties:
                    properties['title'] = '' if properties else 'Not playing'
                if not 'artist' in properties:
                    properties['artist'] = properties['name'] if name in properties else ''
                if not 'album' in properties:
                    properties['album'] = properties['file'] if 'file' in properties else ''
                if self._mode_vol:
                    properties['volume'] = self._mpd_client.status()['volume']
                if self._state != self._mpd_client.status()['state']:
                    self._state = self._mpd_client.status()['state']
                    self._reload_theme()
            except (MPDError, IOError):
                self._mpd_client.disconnect()
                self._connected = False
                self._reload_theme()
        else:
            if self._connect():
                self._reload_theme()
        properties['host'] = self.host
        properties['port'] = self.port
        return properties

    def action_performed(self, binding):
        if self._connected:
            if binding.action == g15driver.SELECT:
                self._mpd_client.pause()
                self._state = self._mpd_client.status()['state']
                if self._state == 'pause':
                    self._mode_vol = False
                self._reload_theme()
            elif binding.action == g15driver.PREVIOUS_SELECTION:
                if self._mode_vol:
                    self._mpd_client.setvol(int(self._mpd_client.status()['volume']) - self.vol_steps)
                else:
                    self._mpd_client.previous()
            elif binding.action == g15driver.NEXT_SELECTION:
                if self._mode_vol:
                    self._mpd_client.setvol(int(self._mpd_client.status()['volume']) + self.vol_steps)
                else:
                    self._mpd_client.next()
            elif binding.action == g15driver.VIEW:
                if (not self._mode_vol) and (self._mpd_client.status()['state'] == 'play'):
                    self._mode_vol = True
                else:
                    self._mode_vol = False
                self._config_changed()

    def _redraw(self):
        self.screen.redraw(self.page)
        self._schedule_redraw()

    def _schedule_redraw(self):
        self.timer = g15scheduler.schedule("MPDRedraw", 1, self._redraw)
