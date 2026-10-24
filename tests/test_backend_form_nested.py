"""A form nested with FormField, or listed in a FieldList, validates as part of the enclosing form."""

from __future__ import annotations

import unittest

from oldman.web.components.forms import FieldList, FormField, StringField, TailwindForm
from oldman.web.components.forms.validators import DataRequired


class AddressForm(TailwindForm):
    """The nested form."""

    city = StringField("City", validators=[DataRequired()])


class ProfileForm(TailwindForm):
    """One nested address."""

    name = StringField("Name", validators=[DataRequired()])
    address = FormField(AddressForm)


class TripForm(TailwindForm):
    """A list of nested addresses."""

    stops = FieldList(FormField(AddressForm), min_entries=1)


class NestedFormTest(unittest.IsolatedAsyncioTestCase):
    async def test_an_empty_required_field_in_a_nested_form_fails_the_enclosing_form(self) -> None:
        form = ProfileForm(data={"name": "Ann", "address-city": ""})

        self.assertFalse(await form.validate())
        self.assertEqual(["address-city"], list(form.errors))
        self.assertNotIn("address", form.cleaned_data)
        self.assertEqual({"address-city": form.errors["address-city"][0]}, form.to_api_response().errors)

    async def test_a_valid_nested_form_contributes_its_cleaned_data(self) -> None:
        form = ProfileForm(data={"name": "Ann", "address-city": "Paris"})

        self.assertTrue(await form.validate())
        self.assertEqual({"name": "Ann", "address": {"city": "Paris"}}, form.cleaned_data)

    async def test_every_nested_form_in_a_list_is_validated(self) -> None:
        form = TripForm(data={"stops-0-city": "Paris", "stops-1-city": ""})

        self.assertFalse(await form.validate())
        self.assertEqual(["stops-1-city"], list(form.errors))

        valid = TripForm(data={"stops-0-city": "Paris", "stops-1-city": "Rome"})
        self.assertTrue(await valid.validate())
        self.assertEqual([{"city": "Paris"}, {"city": "Rome"}], valid.cleaned_data["stops"])

    async def test_populate_obj_fills_the_nested_object_already_there(self) -> None:
        class Address:
            city = "Old"

        class Profile:
            name = "Old"

        address = Address()
        profile = Profile()
        profile.address = address  # type: ignore[attr-defined]
        form = ProfileForm(data={"name": "Ann", "address-city": "Paris"})

        self.assertTrue(await form.validate())
        form.populate_obj(profile)
        self.assertEqual("Ann", profile.name)
        self.assertIs(address, profile.address)  # type: ignore[attr-defined]
        self.assertEqual("Paris", address.city)
