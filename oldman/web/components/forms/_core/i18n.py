# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/i18n.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

# WTForms' message catalogs and the functions that loaded them are not carried over: Oldman forms
# translate through the framework's catalog (see DefaultMeta.get_translations).


class DummyTranslations:
    """
    A translations object which simply returns unmodified strings.

    This is typically used when translations are disabled or if no valid
    translations provider can be found.
    """

    def gettext(self, string):
        return string

    def ngettext(self, singular, plural, n):
        if n == 1:
            return singular

        return plural
