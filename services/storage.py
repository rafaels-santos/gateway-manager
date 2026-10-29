"""Persistent application state. Credentials and hook secrets stay outside source control."""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from . import notifications, network_management

@contextmanager
def open_database(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'labels.db')
    try:
        if os.name != 'nt': os.chmod(directory / 'labels.db', 0o600)
        db.execute('CREATE TABLE IF NOT EXISTS app_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS labels (gateway TEXT, mac TEXT, name TEXT, PRIMARY KEY (gateway, mac))')
        db.execute('CREATE TABLE IF NOT EXISTS webhook_config (gateway TEXT PRIMARY KEY, url TEXT NOT NULL, enabled INTEGER NOT NULL, baseline INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS seen_devices (gateway TEXT NOT NULL, mac TEXT NOT NULL, PRIMARY KEY (gateway, mac))')
        db.execute('CREATE TABLE IF NOT EXISTS app_origins (gateway TEXT PRIMARY KEY, origin TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS device_tags (gateway TEXT NOT NULL, mac TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (gateway, mac))')
        db.execute('CREATE TABLE IF NOT EXISTS webhook_options (gateway TEXT PRIMARY KEY, options TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS webhook_state (gateway TEXT, mac TEXT, state TEXT NOT NULL, PRIMARY KEY(gateway,mac))')
        notifications.schema(db)
        network_management.schema(db)
        with db:
            yield db
    finally:
        db.close()
