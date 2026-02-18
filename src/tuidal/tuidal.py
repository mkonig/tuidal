#!/usr/bin/env python3
"""Tidal tui player."""

import datetime
import gettext
import tomllib
from enum import Enum
from typing import ClassVar

import mpv
import structlog
from . import stylix_theme
from .session import Session
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    Footer,
    Header,
    Input,
    OptionList,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
    Tabs,
)
from textual.widgets.option_list import Option
from tidalapi.album import Album as TidalAlbum
from tidalapi.artist import Artist as TidalArtist
from tidalapi.exceptions import ObjectNotFound
from tidalapi.media import Track as TidalTrack

cr = structlog.dev.ConsoleRenderer.get_active()
cr.colors = False
log = structlog.get_logger()


def setup_localization(language: str = "en"):
    """Load localization.

    Args:
        language: The language to load.

    Returns:
        Gettext function.
    """
    localedir = "locales"

    log.info("Loading translation.", localedir=localedir)
    translation = gettext.translation(
        "base", localedir, languages=[language], fallback=True
    )
    translation.install()

    return translation.gettext


config = {"ui": None}
with open("tuidal.toml", "rb") as config_file:
    config = tomllib.load(config_file)
    log.debug("Config", config=config)

_ = setup_localization(config["ui"].get("language", "us"))


def mpv_logger(_loglevel: str, component: str, message: str):
    """Set up custom log handler for mpv.

    Args:
        _loglevel: The log level.
        component: A component.
        message: The main message.
    """
    log.info(f"mpv: {component}: {message}")


class PlayerWidget(HorizontalGroup):
    """A widget representing the player.

    Attributes:
        DEFAULT_CSS: The default visual representation.
        playback_time: Time.
        track_duration: Duration.
        progress_bar: Visual progress.
        player: External player.
        playback_timer: Timer.
        repeat: How to repeat.
        player_state: Player state.
        tracks: List of tracks
        current_track_index: Track.
        currently_playing: Track.
        current_track: Track.
    """

    DEFAULT_CSS = """
    PlayerWidget {
        height: 3;
        width: 100%;
    }
    Static {
        width: auto;
        height: 1;
        margin: 0 1 0 1;
    }
    """

    class State(Enum):
        """Player states.

        Attributes:
            PLAYING:
            PAUSED:
            STOPPED:
        """

        PLAYING = 1
        PAUSED = 2
        STOPPED = 3

    class Repeat(Enum):
        """State of repeating.

        Attributes:
            NO:
            TRACK:
            TRACK_LIST:
        """

        NO = 1
        TRACK = 2
        TRACK_LIST = 3

    def __init__(self, widget_id: str):
        """Init the player widget.

        Args:
            widget_id: To identify it.
        """
        super().__init__(id=widget_id)
        self.currently_playing: Static | None = None
        self.progress_bar: ProgressBar | None = None
        self.player: mpv.MPV = mpv.MPV(log_handler=mpv_logger)
        self.player_state: PlayerWidget.State = self.State.STOPPED
        self.playback_timer: Timer = self.set_interval(
            1, self.make_progress, pause=True
        )
        self.playback_time: Static | None = None
        self.track_duration: Static | None = None
        self.tracks: list[TidalTrack] = []
        self.current_track_index: int = 0
        self.repeat: PlayerWidget.Repeat = self.Repeat.TRACK_LIST

    def compose(self) -> ComposeResult:
        """Compose the widget.

        Yields:
            The widget gui.
        """
        self.currently_playing = Static("", id="currently_playing")
        self.progress_bar = ProgressBar(show_percentage=False, show_eta=False)
        self.progress_bar.update(total=100, progress=30)
        self.playback_time = Static("", id="playback_time")
        self.track_duration = Static("", id="track_duration")
        yield self.currently_playing
        yield self.playback_time
        yield self.progress_bar
        yield self.track_duration

    def play(self):
        """Play the current track."""
        self.playback_timer.pause()
        self.player.play(self.current_track.get_url())
        self.player.wait_until_playing()
        self.player_state = self.State.PLAYING
        self.currently_playing.update(self.current_track.name or "")
        self.progress_bar.update(total=int(self.player.duration), progress=0)
        self.progress_bar.advance(0)
        self.start_timer()
        self.playback_time.update(f"{self.player.osd.time_pos}")
        self.track_duration.update(str(self.player.osd.duration))

    @property
    def current_track(self) -> TidalTrack | None:
        """The currently playing/paused track.

        Returns:
            The current track or None if none is playing/paused.
        """
        try:
            return self.tracks[self.current_track_index]
        except IndexError:
            return None

    def set_tracks(self, tracks: list[TidalTrack]):
        """Set a list of tracks to play.

        Args:
            tracks: The list of tracks.
        """
        self.tracks = tracks
        self.current_track_index = 0

    def _track_finished(self) -> bool:
        """Check if track finished."""
        return self.player.idle_active or int(self.player.percent_pos) >= 100

    def _is_playing(self) -> bool:
        """Check if player is playing."""
        return self.player_state == self.State.PLAYING

    def _continue_with_next_track(self) -> bool:
        """Check if player should continue with the next track."""
        if self._is_playing() and self._track_finished():
            return True
        return False

    def action_next_track(self):
        """Play next track."""
        match self.repeat:
            case self.Repeat.NO:
                self.current_track_index += 1
            case self.Repeat.TRACK:
                pass
            case self.Repeat.TRACK_LIST:
                self.current_track_index += 1
                self.current_track_index = self.current_track_index % len(
                    self.tracks
                )

        self.play()

    def action_prev_track(self):
        """Play previous track."""
        match self.repeat:
            case self.Repeat.NO:
                self.current_track_index -= 1
            case self.Repeat.TRACK:
                pass
            case self.Repeat.TRACK_LIST:
                self.current_track_index -= 1
                self.current_track_index = self.current_track_index % len(
                    self.tracks
                )
        self.play()

    def pause(self, pause: bool = True):
        """Pause playback.

        Args:
            pause: True to pause the playback. False to continue
                playback.
        """
        self.player.pause = pause

        if pause:
            self.playback_timer.pause()
            self.player_state = self.State.PAUSED
        else:
            self.playback_timer.resume()
            self.player_state = self.State.PLAYING

    def action_play_pause(self):
        """Start playing a track or pause it."""
        if self.player_state == self.State.PLAYING:
            self.pause(True)
        elif self.player_state in [
            self.State.PAUSED,
            self.State.STOPPED,
        ]:
            self.pause(False)

    def start_timer(self):
        """Start the timer again."""
        if self.player_state == self.State.PLAYING:
            self.playback_timer = self.set_interval(
                1, self.make_progress, pause=True
            )
            self.playback_timer.resume()

    def make_progress(self):
        """Progress the track.

        If track ends play next track if possible.
        """
        self.progress_bar.advance()
        self.playback_time.update(f"{self.player.osd.time_pos}")

        if self._continue_with_next_track():
            self.action_next_track()


class TrackSelection(VerticalGroup):
    """Select a track from a album.

    Attributes:
        track_list:
        session:
        album:
    """

    DEFAULT_CSS = """
    TrackSelection {
        height: 5fr;
    }
    .track-list {
        height: 8fr;
    }
    """

    def __init__(self, session: Session, player_widget: PlayerWidget | None):
        """Init the track selection with an album id.

        Args:
            session: The music provider session.
            player_widget: The player widget to show.
        """
        super().__init__()
        self.player_widget = player_widget
        self.tracks: list[TidalTrack] = []
        self.track_list: OptionList = OptionList(
            id="track_list", classes="track-list"
        )
        self.session: Session = session
        self.album: TidalAlbum | None = None

    def focus_list(self, focus_first: bool = False):
        """Focus the list and its first entry.

        Args:
            focus_first: Focus the first element in the list.
        """
        self.track_list.focus()
        highlighted = self.track_list.highlighted
        if highlighted is None or focus_first:
            self.track_list.action_first()

    def action_select(self):
        """Call when a track is selected from the track list."""
        tracks = self._get_tracks_from_highlighted_on()
        self.player_widget.set_tracks(tracks)
        self.player_widget.play()

    def _get_tracks_from_highlighted_on(self) -> list[TidalTrack]:
        """Get a list of tracks starting from the highlighted.

        Returns:
            A list of tracks.
        """
        highlighted = self.track_list.highlighted
        if highlighted is None:
            log.info("No track is highlighted")
            return []

        tracks: list[TidalTrack] = []
        for pos in range(highlighted, self.track_list.option_count):
            track_id = int(self.track_list.get_option_at_index(pos).id)
            tracks.append(self.tracks[track_id])

        return tracks

    def handle_search(self, query: str = "", album_id: str = ""):
        """Handle a search request.

        Args:
            query: Query string.
            album_id: Album id. If given has precedence over query.
        """
        tracks = self.search_tracks(query, album_id)
        self.set_tracks(tracks)

    def search_tracks(
        self, query: str = "", album_id: str = ""
    ) -> list[TidalTrack]:
        """Search tracks for an album or query.

        Args:
            query: Query string.
            album_id: Album id. If given has precedence over query.

        Returns:
            list[TidalTrack]: List of tracks.
        """
        try:
            if album_id:
                album = self.session.session.album(album_id)
                return album.tracks()

            result = self.session.session.search(query, models=[TidalTrack])
            return result["tracks"]
        except Exception as e:
            log.exception("No tracks could be found", exception=e)
            return []

    def set_tracks(self, tracks: list[TidalTrack]):
        """Display a list of tracks.

        Args:
            tracks: List of tracks to show.
        """
        self.tracks = tracks
        self.track_list.clear_options()
        for index, track in enumerate(self.tracks):
            duration = datetime.timedelta(seconds=track.duration)
            text = Content.from_markup(f"{track.name} [d]{duration}[/d]")
            self.track_list.add_option(Option(text, id=str(index)))

    def compose(self) -> ComposeResult:
        """Build the track selection screen.

        Yields:
            The ui.
        """
        yield self.track_list


class AlbumSelection(VerticalGroup):
    """Screen to select an album from the artists album list.

    Attributes:
        session:
        player_widget:
    """

    DEFAULT_CSS = """
    AlbumSelection {
        height: 5fr;
    }
    .album-list {
        height: 8fr;
    }
    """

    def __init__(self, session: Session, player_widget: PlayerWidget | None):
        """Init album screen with artist id.

        Args:
            session: The current session.
            player_widget: The player widget to show.
        """
        super().__init__()
        self.album_list: OptionList = OptionList(
            id="album_list", classes="album-list"
        )
        self.session: Session = session
        self.player_widget = player_widget

    def on_mount(self):
        """On mount."""
        self.album_list.clear_options()

    def focus_list(self, focus_first: bool = False):
        """Focus the list and its first entry."""
        self.album_list.focus()
        highlighted = self.album_list.highlighted
        if highlighted is None or focus_first:
            self.album_list.action_first()

    def handle_search(self, query: str = "", artist_id: str = ""):
        """Handle a search request.

        Args:
            query: Query string.
            artist_id: Artist id. If given has precedence over query.
        """
        albums = self.search_albums(query, artist_id)
        self.set_albums(albums)

    def search_albums(
        self, query: str = "", artist_id: str = ""
    ) -> list[TidalAlbum]:
        """Search albums for the given artist.

        Args:
            query: Search query.
            artist_id: Id of artist to search for. Has precedence over query.

        Returns:
            list[TidalAlbum]: List of albums.
        """
        try:
            if artist_id:
                artist = self.session.session.artist(artist_id)
                return artist.get_albums()

            result = self.session.session.search(query, models=[TidalAlbum])
            return result["albums"]
        except ObjectNotFound as e:
            log.exception(
                "No album found for artist_id and query.",
                artist_id=artist_id,
                query_str=query,
                exception=e,
            )
            return []

    def set_albums(self, albums: list[TidalAlbum]):
        """Set the content of the album list.

        Args:
            albums: List of albums.
        """
        self.album_list.clear_options()
        for album in albums:
            duration = 0
            if album.duration is not None:
                duration = datetime.timedelta(seconds=float(album.duration))
            text = Content.from_markup(
                f"{album.name} [d]({album.year}) {duration}[/d]"
            )
            self.album_list.add_option(Option(text, id=str(album.id)))

    def get_selected_album_id(self) -> str:
        """Return the currently highlighted album's id.

        Returns:
            str: Id of the currently highlighted album.
        """
        album_id = None
        highlighted = self.album_list.highlighted
        if highlighted is not None:
            album_id = self.album_list.get_option_at_index(highlighted).id
        return album_id or ""

    def compose(self) -> ComposeResult:
        """Compose the album selection screen.

        Yields:
            The ui.
        """
        yield self.album_list


class ArtistSearch(VerticalGroup):
    """The artist search screen.

    Attributes:
        DEFAULT_CSS:
        artist_list:
        session:
    """

    DEFAULT_CSS = """
    ArtistSearch {
        height: 5fr;
    }
    .artist-list {
        height: 8fr;
    }
    """

    def __init__(self, session: Session, player_widget: PlayerWidget | None):
        """Init Artist search with provider session.

        Args:
            session: The provider session.
            player_widget: The player widget to show.
        """
        super().__init__()
        self.artist_list: OptionList | None = None
        self.session: Session = session
        self.player_widget = player_widget

    def compose(self) -> ComposeResult:
        """Compose the screen.

        Yields:
            ComposeResult: The screen elements.
        """
        self.artist_list = OptionList(id="artist_list", classes="artist-list")
        yield self.artist_list

    def on_mount(self):
        """Display artist search."""
        #  self.player_widget.start_timer()

    def handle_search(self, query: str):
        """Handle the search for an artist.

        Args:
            query: The query.
        """
        artists = self.search_artists(query)
        self.set_artists(artists)

    def set_artists(self, artists: list[TidalArtist]):
        """Set the list of artists.

        Args:
            artists: List of artists.
        """
        if self.artist_list is not None:
            self.artist_list.clear_options()
            for artist in artists:
                if artist.name and artist.id:
                    _ = self.artist_list.add_option(
                        Option(artist.name, id=str(artist.id))
                    )

    def focus_list(self, focus_first: bool = False):
        """Focus the list and its first entry."""
        if self.artist_list is not None:
            self.artist_list.focus()
            highlighted = self.artist_list.highlighted
            if highlighted is None or focus_first:
                self.artist_list.action_first()

    def get_selected_artist_id(self) -> str:
        """Return the currently highlighted artist's id.

        Returns:
            str: Id of the currently highlighted artist.
        """
        if self.artist_list is None or self.artist_list.highlighted is None:
            return ""

        artist_id = self.artist_list.get_option_at_index(
            self.artist_list.highlighted
        ).id
        return artist_id or ""

    def search_artists(self, query: str) -> list[TidalArtist]:
        """Query music provider for artists.

        Args:
            query: The artist query.

        Returns:
            list[TidalArtist]: List of artists.
        """
        try:
            artist_model = TidalArtist
            results = self.session.session.search(query, models=[artist_model])
            return results["artists"]
        except ValueError as e:
            log.exception("Exception while artist search", exception=e)
            return []


class MainScreen(Screen):
    """Main Screen.

    Attributes:
        BINDINGS:
        DEFAULT_CSS:
        session:
        player_widget:
        artist_search:
        album_selection:
        track_selection:
    """

    DEFAULT_CSS = """
    .main-tabs {
        height: 70%;
    }
    """

    BINDINGS = [
        Binding("/", "new_search", _("New search")),
        Binding("enter", "search_or_select", _("Search/Select"), priority=True),
        Binding("left", "previous_tab", _("Prev Tab"), priority=True),
        Binding("right", "next_tab", _("Next Tab"), priority=True),
        Binding("a", "focus_tab('artists')", priority=True),
        Binding("b", "focus_tab('albums')", priority=True),
        Binding("t", "focus_tab('tracks')", priority=True),
    ]

    def __init__(self, session: Session, player_widget: PlayerWidget):
        """Initialize the main screen.

        Args:
            session: The current music provider session.
            player_widget: The player widget.
        """
        super().__init__()
        self.session: Session = session
        self.player_widget: PlayerWidget = player_widget
        self.search_input: Input = Input(id="search")
        self.artist_search: ArtistSearch = ArtistSearch(
            self.session, self.player_widget
        )
        self.album_selection: AlbumSelection = AlbumSelection(
            self.session, self.player_widget
        )
        self.track_selection: TrackSelection = TrackSelection(
            self.session, self.player_widget
        )

    def action_next_tab(self):
        """Focus next tab."""
        self.query_one(Tabs).action_next_tab()
        self.call_after_refresh(self._focus_list)

    def action_previous_tab(self):
        """Focus previous tab."""
        self.query_one(Tabs).action_previous_tab()
        self.call_after_refresh(self._focus_list)

    def action_focus_tab(self, tab_name: str):
        """Focus the given tab.

        Args:
            tab_name: Name of the tab.
        """
        self.query_one(TabbedContent).active = tab_name
        self._focus_list()

    def handle_search(self):
        """Handle a search request."""
        query = self.search_input.value.strip()
        result = self.session.session.search(
            query, models=[TidalAlbum, TidalTrack, TidalArtist]
        )
        if self.artist_search:
            self.artist_search.set_artists(result["artists"])
        if self.album_selection:
            self.album_selection.set_albums(result["albums"])
        if self.track_selection:
            self.track_selection.set_tracks(result["tracks"])

        self._focus_list(focus_first=True)

    def _focus_list(self, focus_first: bool = False):
        match self.query_one("#tabs").active:
            case "tracks":
                self.track_selection.focus_list(focus_first)
            case "artists":
                self.artist_search.focus_list(focus_first)
            case "albums":
                self.album_selection.focus_list(focus_first)

    def display_albums_of_selected_artist(self):
        """Display the albums of the selected artist."""
        artist_id = self.artist_search.get_selected_artist_id()
        if self.album_selection:
            self.album_selection.handle_search(artist_id=artist_id)
            self.album_selection.focus_list()

    def display_tracks_of_selected_album(self):
        """Display the tracks of the selected album."""
        album_id = self.album_selection.get_selected_album_id()
        if self.track_selection:
            self.track_selection.handle_search(album_id=album_id)
            self.track_selection.focus_list()

    def select_track(self):
        """Play the selected track."""
        if self.track_selection:
            self.track_selection.action_select()

    def action_search_or_select(self):
        """Handle searching or selecting."""
        if self.search_input.has_focus:
            log.info("Searching for query.", query="test")
            self.handle_search()
        elif self.query_one("#track_list").has_focus:
            self.select_track()
        elif self.query_one("#artist_list").has_focus:
            self.display_albums_of_selected_artist()
        elif self.query_one("#album_list").has_focus:
            self.display_tracks_of_selected_album()

    def action_new_search(self):
        """Start a new search."""
        try:
            self.search_input.clear()
            self.search_input.focus()
        except AttributeError:
            self.notify("Something wrong in Ui.")

    def compose(self) -> ComposeResult:
        """Compose the screen.

        Yields:
            ComposeResult: The screen elements.
        """
        yield Header()
        yield Footer()
        yield Static(_("Search:"))
        yield self.search_input
        with TabbedContent(id="tabs", classes="main-tabs"):
            with TabPane(
                Content.from_markup(_("\\[[u]A[/u]]rtists")), id="artists"
            ):
                yield self.artist_search
            with TabPane(
                Content.from_markup(_("Al\\[[u]b[/u]]ums")), id="albums"
            ):
                yield self.album_selection
            with TabPane(
                Content.from_markup(_("\\[[u]T[/u]]racks")), id="tracks"
            ):
                yield self.track_selection
        yield self.player_widget


class Tuidal(App[None]):
    """The main app.

    Attributes:
        BINDINGS:
        ENABLE_COMMAND_PALETTE:
        theme:
        session:
    """

    BINDINGS = [
        Binding("escape", "quit", _("Quit")),
        Binding("p", "play_pause", _("Play/Pause")),
        Binding(">", "next_track", _("Next")),
        Binding("<", "prev_track", _("Previous")),
    ]

    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(self, session: Session):
        """Init the app.

        Args:
            session: A music provider session.
        """
        super().__init__()
        self.session: Session = session
        self.player_widget: PlayerWidget | None = None

    def action_prev_track(self):
        """Play the previous track."""
        if self.player_widget:
            self.player_widget.action_prev_track()

    def action_play_pause(self):
        """Play or pause the current track."""
        if self.player_widget:
            self.player_widget.action_play_pause()

    def action_next_track(self):
        """Play the next track."""
        if self.player_widget:
            self.player_widget.action_next_track()

    def on_mount(self):
        """Display this on start."""
        self.register_theme(stylix_theme.stylix)
        self.theme = "stylix"
        log.info("Theme", theme=self.theme)
        self.player_widget = PlayerWidget(widget_id="player_widget")
        self.push_screen(MainScreen(self.session, self.player_widget))


def main():
    """Run the player."""
    setup_localization(config.get("language", "us"))
    session = Session()
    session.create_session()
    if session.already_logged_in():
        app = Tuidal(session)
        app.run()
    else:
        log.info("Trying to log in")
        session.login_to_tidal()


if __name__ == "__main__":
    main()
