#!/usr/bin/env python3
"""Tidal tui player."""

import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import mpv
import structlog
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
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
from tidalapi.album import Album as TidalAlbum
from tidalapi.artist import Artist as TidalArtist
from tidalapi.exceptions import ObjectNotFound
from tidalapi.media import Track as TidalTrack
from tidalapi.session import Session as TidalSession

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

log = structlog.get_logger()


class Session:
    """Tidal session management."""

    def __init__(self):
        """Init."""
        self.session: TidalSession = TidalSession()

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
        """Check if already logged in.

        Returns:
            bool: True if already logged in. False otherwise.
        """
        logged_in = self.session.check_login()
        log.info("Checking if already logged in.", logged_in=logged_in)
        return logged_in

    def login_to_tidal(self) -> bool:
        """Login to Tidal using OAuth simple flow.

        Returns:
            bool: True if successful, False otherwise
        """
        if self.already_logged_in():
            return True

        try:
            self.session.login_oauth_simple()
            log.info("Successfully logged in to Tidal")
            self.save_session()
            return True
        except TimeoutError as e:
            log.info(f"Login failed: {e}")
            return False

    def create_session(self):
        """Create and return a new Tidal session.

        Loading from file if available.
        """
        log.info("Creating tuidal session.")
        session_file = self.get_session_file_path()

        if session_file.exists():
            self.load_from_file()
        else:
            self.login_to_tidal()

    def load_from_file(self):
        """Load a session from file."""
        try:
            session_file = self.get_session_file_path()
            self.session.load_session_from_file(session_file)
            if self.session.check_login():
                log.info("Loaded existing session")
                return
            log.info("Existing session expired, will need to login again")
        except TimeoutError as e:
            log.info(f"Failed to load session: {e}")

    def save_session(self) -> bool:
        """Save the session to file.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            session_file = self.get_session_file_path()
            self.session.save_session_to_file(session_file)
            log.info(f"Session saved to {session_file}")
            return True
        except Exception as e:
            log.info(f"Failed to save session: {e}")
            return False


class TrackSelection(Screen):
    """Select a track from a album.

    Attributes:
        BINDINGS:
        track_list:
        currently_playing:
        playback_time:
        track_duration:
        progress_bar:
        playback_timer:
        session:
        player:
        album:
        current_track:
        player_state:
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("enter", "select", "Select", priority=True),
        Binding("p", "play_pause", "Play/Pause"),
        Binding(">", "next_track", "Next"),
        Binding("<", "prev_track", "Previous"),
        Binding("b", "back", "Previous Screen"),
    ]

    class PlayerState(Enum):
        """Player states.

        Attributes:
            PLAYING:
            PAUSED:
            STOPPED:
        """

        PLAYING = 1
        PAUSED = 2
        STOPPED = 3

    def __init__(self, session: Session, album_id: str):
        """Init the track selection with an album id.

        Args:
            session (Session): The music provider session.
            album_id (str): The id of the selected album.
        """
        super().__init__()
        self.track_list: OptionList = OptionList(id="track_list")
        self.currently_playing: Static = Static(id="currently_playing")
        self.playback_time: Static = Static(id="playback_time")
        self.track_duration: Static = Static(id="track_duration")
        self.player_state: TrackSelection.PlayerState = self.PlayerState.STOPPED
        self.progress_bar: ProgressBar = ProgressBar(
            show_percentage=False, show_eta=False
        )
        self.playback_timer: Timer = self.set_interval(
            1, self.make_progress, pause=True
        )

        self.session = session
        self.player: mpv.MPV = mpv.MPV()
        self.album: TidalAlbum = self.session.session.album(album_id)
        self.current_track = None

    def action_back(self):
        """Go back to the previous screen."""
        id = -1
        if self.album.artist:
            id = self.album.artist.id
        self.dismiss(("back", id))

    def action_select(self):
        """Call when a track is selected from the track list."""
        highlighted = self.track_list.highlighted
        h = self.track_list.highlighted_option
        self.notify(f"in action selection: {h=}, index={highlighted}")
        if highlighted is None:
            self.notify("No track is highlighted")
            log.info("No track is highlighted")
            return
        track_id = self.track_list.get_option_at_index(highlighted).id
        self.current_track = self.session.session.track(track_id)
        self.player.play(self.current_track.get_url())
        self.player.wait_until_playing()
        self.player_state = self.PlayerState.PLAYING

        self.currently_playing.update(self.current_track.name or "")
        self.progress_bar.update(total=int(self.player.duration), progress=0)
        self.progress_bar.advance(0)
        self.playback_timer.resume()
        self.track_duration.update(str(self.player.osd.duration))

    def make_progress(self):
        """Progress the track.

        If track ends play next track if possible.
        """
        self.progress_bar.advance()
        self.playback_time.update(f"{self.player.osd.time_pos}")

        if self._continue_with_next_track(self):
            self.action_next_track()

    def _track_finished(self) -> bool:
        """Check if track finished."""
        return self.player.idle_active or int(self.player.percent_pos) >= 100

    def _is_playing(self) -> bool:
        """Check if player is playing."""
        return self.player_state == self.PlayerState.PLAYING

    def _continue_with_next_track(self) -> bool:
        """Check if player should continue with the next track."""
        if self._is_playing() and self._track_finished():
            return True
        return False

    def action_next_track(self):
        """Play next track."""
        self.playback_timer.pause()
        self.track_list.action_cursor_down()
        self.action_select()

    def action_prev_track(self):
        """Play previous track."""
        self.playback_timer.pause()
        self.track_list.action_cursor_up()
        self.action_select()

    def pause(self, pause: bool = True):
        """Pause playback.

        Args:
            pause (bool): True to pause the playback. False to continue
                playback.
        """
        self.player.pause = pause

        if pause:
            self.playback_timer.pause()
            self.player_state = self.PlayerState.PAUSED
        else:
            self.playback_timer.resume()
            self.player_state = self.PlayerState.PLAYING

    def action_play_pause(self):
        """Start playing a track or pause it."""
        if self.player_state == self.PlayerState.PLAYING:
            self.pause(True)
        elif self.player_state in [
            self.PlayerState.PAUSED,
            self.PlayerState.STOPPED,
        ]:
            self.pause(False)

    def search_tracks(self) -> list[TidalTrack]:
        """Search tracks for an album.

        Returns:
            list[TidalTrack]: List of tracks.
        """
        try:
            if self.album:
                return self.album.tracks()
            else:
                return []
        except Exception as e:
            log.info("No tracks could be found", exception=e)
            return []

    def on_mount(self):
        """Display track list."""
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
        """Build the track selection screen."""
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
    """Screen to select an album from the artists album list.

    Attributes:
        BINDINGS:
        album_list:
        session:
        artist:
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("enter", "select", "Select", priority=True),
        Binding("b", "back", "Prev Screen", priority=True),
    ]

    def __init__(self, session: Session, artist_id: str):
        """Init album screen with artist id.

        Args:
            session (Session): The current session.
            artist_id (str): Artist it.
        """
        super().__init__()
        self.album_list: OptionList = OptionList(id="album_list")
        self.session = session
        self.artist = self.session.session.artist(artist_id)

    def action_back(self):
        """Go back to the previous screen."""
        self.dismiss(("back", None))

    def action_select(self):
        """Dismiss this screen with the id of the selected album."""
        selected_album_id = self.album_list.get_option_at_index(
            self.album_list.highlighted
        ).id
        self.dismiss(("album_selected", selected_album_id))

    def search_albums(
        self, limit: int = 200, offset: int = 0
    ) -> list[TidalAlbum]:
        """Search albums for the given artist.

        Args:
            limit (int): Max results.
            offset (int): Offset in results for paging.

        Returns:
            list[TidalAlbum]: List of albums.
        """
        try:
            if self.artist:
                return self.artist.get_albums(limit=limit + offset)
            return []
        except ObjectNotFound as e:
            log.error(
                "No album found for artist.", artist=self.artist, exception=e
            )
            return []

    def on_mount(self):
        """On mount."""
        log.info("AlbumSelection init.", artist_id=self.artist.id)
        self.album_list.clear_options()
        albums = self.search_albums()
        for album in albums:
            self.album_list.add_option(
                Option(
                    f"{album.name}   {album.audio_modes}:{"|".join(album.media_metadata_tags)}",
                    id=str(album.id),
                )
            )

        self.album_list.focus()
        self.album_list.action_first()

    def compose(self) -> ComposeResult:
        """Compose the album selection screen.

        Yields:
            The ui.
        """
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
        """Init Artist search with provider session.

        Args:
            session (Session): The provider session.
        """
        super().__init__()
        self.artist_list: OptionList = OptionList(id="artist_list")
        self.search_input: Input = Input(id="search")
        self.session: Session = session

    def action_new_search(self):
        """Start a new search."""
        self.search_input.clear()
        self.search_input.focus()

    def compose(self) -> ComposeResult:
        """Compose the screen.

        Yields:
            ComposeResult: The screen elements.
        """
        yield Header()
        yield Vertical(Static("Search:"), self.search_input, self.artist_list)
        yield Footer()

    def handle_search(self):
        """Handle the search for an artist."""
        query = self.search_input.value.strip()
        artists = self.search_artists(query)
        self.artist_list.clear_options()
        for artist in artists:
            self.artist_list.add_option(Option(artist.name, id=artist.id))

        self.artist_list.focus()
        self.artist_list.action_first()

    def action_search_or_select(self):
        """Handle searching or selecting an artist."""
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
            self.dismiss(selected_artist_id)

    def search_artists(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[Any]:
        try:
            artist_model = TidalArtist
            results = self.session.session.search(
                query, models=[artist_model], limit=limit + offset
            )
            if "artists" in results:
                return results["artists"][offset : offset + limit]
            return []
        except Exception as e:
            log.info("Exception while artist search", exception=e)
            return []


class Tuidal(App):
    """The main app.

    Attributes:
        BINDINGS:
        ENABLE_COMMAND_PALETTE:
        theme:
        session:
    """

    BINDINGS = [
        Binding("escape", "quit", "Esc Quit"),
    ]
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, session: Session):
        """Init the app.

        Args:
            session (Session): A music provider session.
        """
        super().__init__()
        self.theme = "textual-light"
        self.session: Session = session

    def on_mount(self):
        """Display this on start."""
        self.push_screen(ArtistSearch(self.session), self.album_selection)

    def album_selection(self, artist_id: str):
        """Open the album selection screen.

        Args:
            artist_id (str): The artist id.
        """
        self.push_screen(
            AlbumSelection(self.session, artist_id),
            self.album_selection_dismissed,
        )

    def album_selection_dismissed(self, result: tuple[str, str]):
        """Handle album selection is dismissed.

        Args:
            result (tuple[str,str]): Next action and metadata.
        """
        next_action, album_id = result
        if next_action == "back":
            self.push_screen(ArtistSearch(self.session), self.album_selection)
        else:
            self.track_selection(album_id)

    def track_selection(self, album_id: str):
        """Open the track selection screen.

        Args:
            album_id (str): The id of the selected album.
        """
        self.push_screen(
            TrackSelection(self.session, album_id),
            self.track_selection_dismissed,
        )

    def track_selection_dismissed(self, result: tuple[str, str]):
        """Handle track selection is dismissed.

        Args:
            result (tuple[str,str]): Next action and metadata.
        """
        next_action, album_id = result
        if next_action == "back":
            self.push_screen(
                AlbumSelection(self.session, album_id),
                self.album_selection_dismissed,
            )
        else:
            log.error("Wrong next_action", next_action=next_action)


def main():
    """Run the player."""
    session = Session()
    session.create_session()
    if session.already_logged_in():
        app = Tuidal(session)
        app.run()
    else:
        session.login_to_tidal()


if __name__ == "__main__":
    main()
