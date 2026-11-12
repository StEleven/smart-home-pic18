"""Configure the Windows Qt/Chromium presentation path before WebEngine starts."""
import os
import sys


def configure_webengine_graphics():
    if sys.platform != 'win32':
        return
    # Qt 6.12's native shared-image compositor intermittently loses HTML/WebGL
    # layers. Compose the page through the software output device instead.
    # ANGLE/WebGL itself remains hardware accelerated. The second flag avoids
    # the ~10 Hz submit/ack cadence observed with this software output path;
    # HouseScene caps its
    # actual render work at 60 Hz so back-to-back begin frames cannot run wild.
    flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
    for flag in ('--disable-gpu-compositing', '--disable-frame-rate-limit'):
        if flag not in flags.split():
            flags = (flags + ' ' + flag).strip()
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = flags
