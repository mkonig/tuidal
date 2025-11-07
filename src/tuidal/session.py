"""Session management module."""

from pathlib import Path

import structlog
import tidalapi
from tidalapi.session import Session as TidalSession

cr = structlog.dev.ConsoleRenderer.get_active()
cr.colors = False
log = structlog.get_logger()


class Session:
    """Tidal session management."""

    def __init__(self):
        """Init."""
        config = tidalapi.session.Config(quality=tidalapi.media.Quality.default)
        self.session: TidalSession = TidalSession(config)

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
            log.info("Starting oauth.")
            self.session.login_oauth_simple()
            log.info("Successfully logged in to Tidal")
            self.save_session()
            return True
        except TimeoutError as e:
            log.exception(f"Login failed: {e}")
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
            log.exception(f"Failed to load session: {e}")

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
        except OSError as e:
            log.exception(f"Failed to save session: {e}")
            return False
