"""Switching Streamlit's own light/dark appearance from inside the app.

Streamlit remembers the active appearance in the browser and only exposes it
through its main menu (System / Light / Dark). There is no Python API for it,
so the helper below drives that menu on the user's behalf: the sidebar switch
calls :func:`theme_script` and the browser clicks the matching menu item.

Two details matter:

* The sanitizer Streamlit uses for ``st.html`` drops any script containing a
  ``<`` character, so comparisons are written with ``>`` instead.
* The menu items are looked up lazily: if they are not rendered yet, the menu
  button is clicked first and the lookup is retried for ~1.5 seconds.
"""

from __future__ import annotations

APPEARANCE_OPTIONS = ("System", "Light", "Dark")

_MENU_LABELS = {"System": "System", "Light": "Light", "Dark": "Dark"}


def theme_script(choice: str) -> str:
    """JavaScript that switches the browser to ``choice``.

    Returns an empty string for an unknown choice so callers can skip the
    ``st.html`` call entirely.
    """
    item = _MENU_LABELS.get(choice)
    if item is None:
        return ""

    return (
        "<script>(function(){try{"
        f"var item={item!r};"
        "var app=document.querySelector('[data-testid=\"stApp\"]');"
        "var scheme=app&&getComputedStyle(app).colorScheme==='dark'"
        "?'dark':'light';"
        "if(item!=='System'&&scheme===item.toLowerCase()){return;}"
        "var pick=function(){"
        "var node=document.querySelector("
        f"'[data-testid=\"stMainMenuItem-theme-{item}\"]');"
        "if(!node){return false;}"
        "node.click();"
        "return true;"
        "};"
        "var closeMenu=function(){"
        "document.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:'Escape',keyCode:27,bubbles:true}));"
        "};"
        "if(pick()){return;}"
        "var button=document.querySelector('[data-testid=\"stMainMenuButton\"]');"
        "if(!button){return;}"
        "button.click();"
        "var tries=0;"
        "var tick=function(){"
        "if(pick()){closeMenu();return;}"
        "tries+=1;"
        "if(tries>25){closeMenu();return;}"
        "setTimeout(tick,60);"
        "};"
        "setTimeout(tick,80);"
        "}catch(error){}})();</script>"
    )
