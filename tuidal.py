#!/usr/bin/env python3
"""Tidal tui player."""

import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import mpv
import tidalapi
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import (
    Footer,
    Header,
    Input,
    OptionList,
    ProgressBar,
    Static,
)
from textual.widgets.option_list import Option

TUIDAL_THEME: Theme = Theme(
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
    """Tidal session management."""

    def __init__(self, silent: bool = False):
        """Init.

        Args:
            silent (bool): Log output or not.
        """
        self.session: tidalapi.Session | None = None
        self.silent = silent

    def get_session_file_path(self) -> Path:
        """Get the path for storing the session file.

        Returns:
            Path: Path object for the session.json file
        """
        home_dir = Path.home()
        session_dir = home_dir / ".config" / "tuidal"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "session.json"

    def already_logged_in(self) -> bool:
        if self.session.check_login():
            return True

        return False

    def login_to_tidal(self) -> bool:
        """Login to Tidal using OAuth simple flow.

        Returns:
            bool: True if successful, False otherwise
        """
        if self.already_logged_in():
            return True

        try:
            self.session.login_oauth_simple()
            if not self.silent:
                print("Successfully logged in to Tidal")
            self.save_session()
            return True
        except TimeoutError as e:
            if not self.silent:
                print(f"Login failed: {e}")
            return False

    def create_session(self):
        """Create and return a new Tidal session, loading from file if
        available.

        Returns:
            tidalapi.Session: A Tidal session object
        """
        self.session = tidalapi.Session()
        session_file = self.get_session_file_path()

        if session_file.exists():
            try:
                self.session.load_session_from_file(session_file)
                if self.session.check_login():
                    if not self.silent:
                        print("Loaded existing session")
                    return
                if not self.silent:
                    print("Existing session expired, will need to login again")
            except TimeoutError as e:
                if not self.silent:
                    print(f"Failed to load session: {e}")

    def save_session(self) -> bool:
        """Save the session to file.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            session_file = self.get_session_file_path()
            self.session.save_session_to_file(session_file)
            if not self.silent:
                print(f"Session saved to {session_file}")
            return True
        except Exception as e:
            if not self.silent:
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
        self.currently_playing: Static = Static(id="currently_playing")
        self.playback_time: Static = Static(id="playback_time")
        self.track_duration: Static = Static(id="track_duration")
        self.player_state: PlayerState = self.PlayerState.STOPPED
        self.progress_bar: ProgressBar = ProgressBar(
            show_percentage=False, show_eta=False
        )
        self.playback_timer: Timer = self.set_interval(
            1, self.make_progress, pause=True
        )

        self.session = session
        self.player = mpv.MPV()
        self.album = self.session.album(album_id)
        self.current_track = None

    def action_select(self):
        track_id = int(
            self.track_list.get_option_at_index(self.track_list.highlighted).id
        )
        self.current_track = self.session.track(track_id)
        self.player.play(self.current_track.get_url())
        self.player.wait_until_playing()
        self.player_state = self.PlayerState.PLAYING

        self.currently_playing.update(self.current_track.name)
        self.progress_bar.update(total=self.player.duration, progress=0)
        self.progress_bar.advance(0)
        self.playback_timer.resume()
        self.track_duration.update(self.player.osd.duration)

    def make_progress(self):
        self.progress_bar.advance()
        self.playback_time.update(f"{self.player.osd.time_pos}")

        if not self.player.percent_pos or self.player.percent_pos >= 100:
            self.track_list.action_cursor_down()
            self.action_select()

    def pause(self, pause: bool = True):
        self.player.pause = pause
        self.player_state = (
            self.PlayerState.PAUSED if pause else self.PlayerState.PLAYING
        )

    def action_play_pause(self):
        if self.player_state == self.PlayerState.PLAYING:
            self.pause(True)
        elif self.player_state in [
            self.PlayerState.PAUSED,
            self.PlayerState.STOPPED,
        ]:
            self.pause(False)

    def search_tracks(self, limit=200, offset=0) -> list[object]:
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
            self.track_list.add_option(
                Option(f"{track.name} : {duration}", id=track.id)
            )

        self.track_list.focus()
        self.track_list.action_first()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(f"Album: {self.album.name} ({self.album.artist.name})")
            yield Static("Tracks:")
            yield self.track_list
            yield Static("Currently playing:")
            yield self.currently_playing
            yield self.playback_time
            yield self.progress_bar
            yield self.track_duration
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
        selected_album_id = int(
            self.album_list.get_option_at_index(self.album_list.highlighted).id
        )
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
        yield Vertical(
            Static(f"Artist: {self.artist.name}"),
            Static("Albums:"),
            self.album_list,
        )
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
                self.artist_list.get_option_at_index(
                    self.artist_list.highlighted
                ).id
            )
            self.dismiss(("artist_selected", selected_artist_id))

    def search_artists(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[Any]:
        try:
            artist_model = tidalapi.Artist
            results = self.session.search(
                query, models=[artist_model], limit=limit + offset
            )
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
        self.push_screen(
            AlbumSelection(self.session, artist_id), self.track_selection
        )

    def track_selection(self, result):
        _, album_id = result
        self.push_screen(TrackSelection(self.session, album_id))


def main():
    session = Session()
    session.create_session()
    if session.already_logged_in():
        app = Tuidal(session)
        app.run()
    else:
        session.login_to_tidal()


if __name__ == "__main__":
    main()
