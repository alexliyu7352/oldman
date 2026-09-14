"""Illustrative form routes; this is not a standalone Web project."""

from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Email

from oldman.web import Request, get_app, redirect_response, render_template
from oldman.web.components.forms import OldmanForm

app = get_app()


class ContactForm(OldmanForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    message = TextAreaField("Message", validators=[DataRequired()])


@app.get("/contact")
async def contact_form(request: Request):
    form = ContactForm(request=request)
    return await render_template(
        "contact.html",
        context={
            "contact_form_html": await form.render(
                action="/contact",
                method="post",
                form_mode="html",
                component_name=None,
            )
        },
    )


@app.post("/contact")
async def contact_submit(request: Request):
    form = ContactForm.from_request(request)
    if await form.validate():
        return redirect_response("/thanks")
    return await render_template(
        "contact.html",
        context={
            "contact_form_html": await form.render(
                action="/contact",
                method="post",
                form_mode="html",
                component_name=None,
            )
        },
        status=422,
    )
