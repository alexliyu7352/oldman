"""A form nested with FormField, or listed in a FieldList, validates as part of the enclosing form."""

from __future__ import annotations

import unittest

from oldman.web.components.forms import FieldList, FormField, StringField, TailwindForm, ValidationError
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


class CheckedAddressForm(AddressForm):
    """A nested form whose own clean() rejects the whole address."""

    async def clean(self):
        raise ValidationError("We do not deliver there.")


class CleanSpy(ProfileForm):
    """Records what clean_address() and clean() were given."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []

    async def clean_address(self):
        self.calls.append("clean_address")
        return self.cleaned_data["address"]

    async def clean(self):
        self.calls.append("clean sees address" if "address" in self.cleaned_data else "clean without address")


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

    async def test_clean_of_a_nested_form_field_can_reject_the_whole_nested_form(self) -> None:
        class Profile(CleanSpy):
            async def clean_address(self):
                await super().clean_address()
                raise ValidationError("Bad address.")

        form = Profile(data={"name": "Ann", "address-city": "Paris"})

        self.assertFalse(await form.validate())
        self.assertEqual({"address": ["Bad address."]}, form.errors)
        self.assertEqual(["clean_address", "clean without address"], form.calls)
        self.assertEqual({"name": "Ann"}, form.cleaned_data)
        self.assertEqual({"address": "Bad address."}, form.to_api_response().errors)

    async def test_add_error_on_a_nested_form_field_fails_the_form(self) -> None:
        class Profile(ProfileForm):
            async def clean(self):
                self.add_error("address", "Pick another address.")

        form = Profile(data={"name": "Ann", "address-city": "Paris"})

        self.assertFalse(await form.validate())
        self.assertEqual({"address": ["Pick another address."]}, form.errors)
        self.assertNotIn("address", form.cleaned_data)

    async def test_errors_added_to_a_nested_form_field_do_not_outlive_the_validation(self) -> None:
        class Profile(ProfileForm):
            rejections = 1

            async def clean_address(self):
                if self.rejections:
                    self.rejections -= 1
                    raise ValidationError("Bad address.")
                return self.cleaned_data["address"]

        form = Profile(data={"name": "Ann", "address-city": "Paris"})

        self.assertFalse(await form.validate())
        self.assertTrue(await form.validate())
        self.assertEqual({}, form.errors)

    async def test_clean_of_a_field_is_skipped_when_its_nested_form_rejected_itself(self) -> None:
        class Profile(CleanSpy):
            address = FormField(CheckedAddressForm)

        form = Profile(data={"name": "Ann", "address-city": "Paris"})

        self.assertFalse(await form.validate())
        self.assertEqual({"address": ["We do not deliver there."]}, form.errors)
        self.assertEqual(["clean without address"], form.calls)
