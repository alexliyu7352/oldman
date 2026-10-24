# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/meta.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from .utils import WebobInputWrapper
from .widgets.core import clean_key


class DefaultMeta:
    """
    This is the default Meta class which defines all the default values and
    therefore also the 'API' of the class Meta interface.
    """

    # -- Basic form primitives

    def bind_field(self, form, unbound_field, options):
        """
        bind_field allows potential customization of how fields are bound.

        The default implementation simply passes the options to
        :meth:`UnboundField.bind`.

        :param form: The form.
        :param unbound_field: The unbound field.
        :param options:
            A dictionary of options which are typically passed to the field.

        :return: A bound field
        """
        return unbound_field.bind(form=form, **options)

    def wrap_formdata(self, form, formdata):
        """
        wrap_formdata allows doing custom wrappers of WTForms formdata.

        The default implementation detects webob-style multidicts and wraps
        them, otherwise passes formdata back un-changed.

        :param form: The form.
        :param formdata: Form data.
        :return: A form-input wrapper compatible with WTForms.
        """
        if formdata is not None and not hasattr(formdata, "getlist"):
            if hasattr(formdata, "getall"):
                return WebobInputWrapper(formdata)
            else:
                raise TypeError("formdata should be a multidict-type wrapper that supports the 'getlist' method")
        return formdata

    def render_field(self, field, render_kw):
        """
        render_field allows customization of how widget rendering is done.

        The default implementation calls ``field.widget(field, **render_kw)``
        """

        render_kw = {clean_key(k): v for k, v in render_kw.items()}

        other_kw = getattr(field, "render_kw", None)
        if other_kw is not None:
            other_kw = {clean_key(k): v for k, v in other_kw.items()}
            render_kw = dict(other_kw, **render_kw)
        return field.widget(field, **render_kw)

    # -- CSRF

    # WTForms' CSRF implementation is not carried over: Oldman protects form views with
    # @csrf_protect() from oldman.web.security.csrf. The flag stays so that a form asking for it fails loudly in
    # BaseForm instead of silently running without protection.
    csrf = False

    # -- i18n

    # The locale a locale-aware number field (DecimalField(use_locale=True)) formats and parses with.
    locales = False

    def get_translations(self, form):
        """Return the object that translates this form's messages (its gettext and ngettext), or None.

        None leaves the messages untranslated. Oldman's Form.Meta returns the request's catalog; WTForms'
        own message catalogs are not carried over, so there is nothing else to look up.
        """
        return None

    # -- General

    def update_values(self, values):
        """
        Given a dictionary of values, update values on this `Meta` instance.
        """
        for key, value in values.items():
            setattr(self, key, value)
