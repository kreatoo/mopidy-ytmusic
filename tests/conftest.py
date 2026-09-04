"""Pytest fixtures and import shims.

Mopidy 3.x imports PyGObject (``gi``) at package import time, even when the
tests never touch the audio layer.  On machines without a GStreamer/GTK stack
we install minimal stand-in modules so the test suite can still run.
Real Mopidy installs bring their own PyGObject, which is used as-is.
"""

import sys
import types


class _Any:
    """Anything goes: callable and attribute-accessible dummy."""

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return _Any()

    def __getitem__(self, name):
        return _Any()

    def __bool__(self):
        return False

    def __add__(self, other):
        return _Any()

    def __radd__(self, other):
        return _Any()

    def __iter__(self):
        return iter(())

    def __eq__(self, other):
        return isinstance(other, _Any) or other is None

    def __lt__(self, other):
        return False

    def __le__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return True

    def __hash__(self):
        return 0

    def __mro_entries__(self, bases):
        # Mopidy's audio actor defines `class _Outputs(Gst.Bin)`; in a
        # stubbed environment just make it inherit from object.
        return (object,)

    def __repr__(self):
        return "<gi-stub>"


def _install_gi_stubs():
    try:
        import gi  # noqa: F401

        return  # real PyGObject available
    except ModuleNotFoundError:
        pass

    gi_module = types.ModuleType("gi")
    gi_module.require_version = lambda *args, **kwargs: None  # noqa: E731
    gi_module.get_required_version = lambda name: None  # noqa: E731
    sys.modules["gi"] = gi_module

    repository = types.ModuleType("gi.repository")
    sys.modules["gi.repository"] = repository

    for name in (
        "Gst",
        "GLib",
        "Gio",
        "GObject",
        "GstPbutils",
        "GstBase",
        "GstAudio",
    ):
        module = types.ModuleType(f"gi.repository.{name}")
        module.__getattr__ = lambda _name: _Any()  # type: ignore[attr-defined]
        sys.modules[f"gi.repository.{name}"] = module
        setattr(repository, name, module)


_install_gi_stubs()
