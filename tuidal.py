#!/usr/bin/env python3

import datetime
import json
from enum import Enum
from pathlib import Path
from typing import Any

import mpv
import tidalapi
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Footer, Header, Input, OptionList, Select, Static
from textual.widgets.option_list import Option
from tidalapi import Session

TUIDAL_THEME = Theme(
    name="tuidal-latte",
    primary="#1e66f5",
    secondary="#8839ef",
    accent="#40a02b",
    warning="#df8e1d",
    error="#d20f39",
    success="#40a02b",
    surface="#eff1f5",
    panel="#e6e9ef",
    dark=False,
)


class Session:
    def __init__(self):
        self.session = None

    def get_session_file_path(self) -> Path:
        """Get the path for storing the session file.

        Returns:
            Path: Path object for the session.json file
        """
        home_dir = Path.home()
        session_dir = home_dir / ".config" / "tuidal"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "session.json"

    def login_to_tidal(self, silent: bool = False) -> bool:
        """Login to Tidal using OAuth simple flow.

        Args:
            session (tidalapi.Session): The session to authenticate
            silent (bool): If True, suppress print statements

        Returns:
            bool: True if successful, False otherwise
        """
        if self.session.check_login():
            if not silent:
                print("Already logged in")
            return True

        try:
            session.login_oauth_simple()
            if not silent:
                print("Successfully logged in to Tidal")
            save_session(session, silent)
            return True
        except Exception as e:
            if not silent:
                print(f"Login failed: {e}")
            return False

    def create_session(self, silent=False) -> Session:
        """Create and return a new Tidal session, loading from file if
        available.

        Args:
            silent (bool): If True, suppress print statements

        Returns:
            tidalapi.Session: A Tidal session object
        """
        self.session = tidalapi.Session()
        session_file = self.get_session_file_path()

        if session_file.exists():
            try:
                self.session.load_session_from_file(session_file)
                if self.session.check_login():
                    if not silent:
                        print("Loaded existing session")
                if not silent:
                    print("Existing session expired, will need to login again")
            except Exception as e:
                if not silent:
                    print(f"Failed to load session: {e}")

    def save_session(self, silent: bool = False) -> bool:
        """Save the session to file.

        Args:
            session (tidalapi.Session): The session to save
            silent (bool): If True, suppress print statements

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            session_file = get_session_file_path()
            self.session.save_session_to_file(session_file)
            if not silent:
                print(f"Session saved to {session_file}")
            return True
        except Exception as e:
            if not silent:
                print(f"Failed to save session: {e}")
            return False


class TrackSelection(Screen):
    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("enter", "select", "Select", priority=True),
        Binding("p", "play_pause", "Play/Pause"),
    ]

    class PlayerState(Enum):
        PLAYING = 1
        PAUSED = 2
        STOPPED = 3

    def __init__(self, session: Session, album_id: int):
        super().__init__()
        self.track_list: OptionList = OptionList(id="track_list")
        self.session = session
        self.player = mpv.MPV()
        self.album = self.session.album(album_id)
        self.player_state: PlayerState = self.PlayerState.STOPPED

    def action_select(self):
        track_id = int(self.track_list.get_option_at_index(self.track_list.highlighted).id)
        track_obj = self.session.track(track_id)
        self.player.play(track_obj.get_url())

        self.player_state = self.PlayerState.PLAYING

    def pause(self, pause: bool = True):
        self.player.pause = pause
        self.player_state = self.PlayerState.PAUSED if pause else self.PlayerState.PLAYING

    def action_play_pause(self):
        if self.player_state == self.PlayerState.PLAYING:
            self.pause(True)
        elif self.player_state in [self.PlayerState.PAUSED, self.PlayerState.STOPPED]:
            self.pause(False)

    def search_tracks(self, limit=200, offset=0):
        try:
            if self.album:
                return self.album.tracks()
        except Exception as e:
            return []

    def on_mount(self):
        self.track_list.clear_options()
        tracks = self.search_tracks()
        for track in tracks:
            duration = datetime.timedelta(seconds=track.duration)
            self.track_list.add_option(Option(f"{track.name} : {duration}", id=track.id))

        self.track_list.focus()
        self.track_list.action_first()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(f"Album: {self.album.name} ({self.album.artist.name})"),
            Static("Tracks:"),
            self.track_list,
        )
        yield Footer()


class AlbumSelection(Screen):
    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("enter", "select", "Select", priority=True),
    ]

    def __init__(self, session: Session, artist_id: int):
        super().__init__()
        self.album_list: OptionList = OptionList(id="album_list")
        self.session = session
        self.artist = self.session.artist(artist_id)

    def action_select(self):
        selected_album_id = int(self.album_list.get_option_at_index(self.album_list.highlighted).id)
        self.dismiss(("album_selected", selected_album_id))

    def search_albums(self, limit=200, offset=0):
        try:
            if self.artist:
                return self.artist.get_albums(limit=limit + offset)
        except Exception as e:
            return []

    def on_mount(self):
        self.album_list.clear_options()
        albums = self.search_albums()
        for album in albums:
            self.album_list.add_option(
                Option(
                    f"{album.name}   {album.audio_modes}:{"|".join(album.media_metadata_tags)}",
                    id=album.id,
                )
            )

        self.album_list.focus()
        self.album_list.action_first()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static(f"Artist: {self.artist.name}"), Static("Albums:"), self.album_list)
        yield Footer()


class ArtistSearch(Screen):
    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("/", "new_search", "New search"),
        Binding("enter", "search_or_select", "Search/Select", priority=True),
    ]

    def __init__(self, session: Session):
        super().__init__()
        self.artist_list: OptionList = OptionList(id="artist_list")
        self.search_input: Input = Input(id="search")
        self.session: Session = session

    def action_new_search(self):
        self.search_input.focus()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Search:"), self.search_input, self.artist_list)
        yield Footer()

    def handle_search(self):
        query = self.search_input.value.strip()
        artists = self.search_artists(query)
        self.artist_list.clear_options()
        for artist in artists:
            self.artist_list.add_option(Option(artist.name, id=artist.id))

        self.artist_list.focus()
        self.artist_list.action_first()

    def action_search_or_select(self):
        if self.search_input.has_focus:
            self.handle_search()
        else:
            self.select_artist()

    def select_artist(self):
        """Select the highlighted artist."""
        if self.artist_list.highlighted is not None:
            selected_artist_id = int(
                self.artist_list.get_option_at_index(self.artist_list.highlighted).id
            )
            self.dismiss(("artist_selected", selected_artist_id))

    def search_artists(self, query: str, limit: int = 10, offset: int = 0) -> list[Any]:
        try:
            artist_model = tidalapi.Artist
            results = self.session.search(query, models=[artist_model], limit=limit + offset)
            if "artists" in results:
                return results["artists"][offset : offset + limit]
            return []
        except Exception as e:
            return []


class Tuidal(App):
    BINDINGS = [
        Binding("escape", "quit", "Esc Quit"),
    ]
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, session):
        super().__init__()
        self.theme = "textual-light"
        self.session = session.session

    def on_mount(self):
        self.push_screen(ArtistSearch(self.session), self.album_selection)

    def album_selection(self, result):
        _, artist_id = result
        self.push_screen(AlbumSelection(self.session, artist_id), self.track_selection)

    def track_selection(self, result):
        _, album_id = result
        self.push_screen(TrackSelection(self.session, album_id))


def main():
    session = Session()
    session.create_session(silent=True)
    if session.login_to_tidal():
        app = Tuidal(session)
        app.run()
    else:
        print("Login failed")


if __name__ == "__main__":
    main()
