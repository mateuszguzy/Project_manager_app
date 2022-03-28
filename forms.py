from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField, SelectMultipleField, widgets, DateField, HiddenField, \
    SelectField, EmailField
from wtforms.validators import DataRequired


# ------ MAIN FORMS
class TaskDone(FlaskForm):
    id = HiddenField("")
    done = SubmitField("DONE")
    undone = SubmitField("UNDONE")


class DeleteList(FlaskForm):
    list = SelectMultipleField(
        'List',
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=True))
    submit = SubmitField("Delete")


class UserSelectionField(FlaskForm):
    selection_id = SelectField("", choices=[], validators=[DataRequired()])
    submit = SubmitField("Next")


# ------ PROJECTS FORMS
class AddProject(FlaskForm):
    name = StringField("Project name", validators=[DataRequired()])
    occupied_users = SelectMultipleField(
        'users_id',
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False))
    free_users = SelectMultipleField(
        'free_users',
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False))
    submit = SubmitField("Submit")


# ------ TASKS FORMS
class AddTask(FlaskForm):
    title = StringField("Title", validators=[DataRequired()])
    description = StringField("Description", validators=[DataRequired()])
    deadline = DateField("Deadline", format="%Y-%m-%d", validators=[DataRequired()])
    occupied_users = SelectMultipleField(
        'users_id',
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False))
    free_users = SelectMultipleField(
        'free_users',
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False))
    submit = SubmitField("Submit")


# ------ USER FORMS
class AddUser(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    position = StringField("Position", validators=[DataRequired()])
    submit = SubmitField("Add")


# --- EDIT USER
class EditUser(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    position = StringField("Position", validators=[DataRequired()])
    submit = SubmitField("Apply Changes")


# --- USER LOGIN
class LoginUser(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


# --- CHANGE PASSWORD
class ChangePassword(FlaskForm):
    old_password = StringField("Old Password", validators=[DataRequired()])
    new_password = PasswordField("New Password", validators=[DataRequired()])
    new_password_repeat = PasswordField("Repeat new password", validators=[DataRequired()])
    submit = SubmitField("Change Password")


# --- PASSWORD REMINDER
class PasswordRecovery(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    submit = SubmitField("Reset Password")
