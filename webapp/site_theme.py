"""Browser-only theme choice for the shared private-page shell."""
from . import ui_icons
from .site_assets import THEME_STYLE as STYLE, THEME_BOOTSTRAP as BOOTSTRAP

BUTTON = ('<div class="site-theme-bar"><button id="site-theme-toggle" type="button" '
          'aria-label="어두운 화면으로 전환" title="어두운 화면으로 전환">'
          '<span data-theme-icon="light">' + ui_icons.icon('moon') + '</span>'
          '<span data-theme-icon="dark">' + ui_icons.icon('sun') + '</span>'
          '</button></div>')
