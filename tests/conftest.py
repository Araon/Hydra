import os

# These must be present before importing either Flask application.
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
os.environ.setdefault("SKIP_BACKGROUND_TASKS", "1")
os.environ.setdefault("SKIP_NETWORK_CALLS", "1")
