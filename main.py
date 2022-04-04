import os
from dotenv import load_dotenv
from functools import wraps
from forms import AddProject, LoginUser, TaskDone, DeleteList, AddTask, UserSelectionField, AddUser, ChangePassword, \
    PasswordRecovery, EditUser
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, redirect, flash, url_for, request
from sqlalchemy.orm import relationship
from flask_bootstrap import Bootstrap
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from datetime import timedelta, datetime
from flask_gravatar import Gravatar
import re
import smtplib
import random


# ------ SET APP
# --- MAIN
app = Flask(__name__)
load_dotenv()
POSTGRES_DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres", "postgresql")
print(POSTGRES_DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("POSTGRES_DATABASE_URL", "DB_TABLE")
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
Bootstrap(app)
# --- SET DB
db = SQLAlchemy(app)
# --- LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
# --- EMAIL CREDENTIALS
FROM_EMAIL = os.environ.get("FROM_EMAIL")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

# user default avatar API
default_avatar_mini = Gravatar(app,
                               size=50,
                               rating='r',
                               default='robohash',
                               force_default=False,
                               force_lower=False,
                               use_ssl=False,
                               base_url=None)

# ------ CONFIGURE TABLES
# --- PROJECTS DB
# Association table for many-to-many relationship for users and tasks
# One user can have multiple tasks, one task can have multiple users assigned
user_task = db.Table("user_task",
                     db.Column("user_id", db.Integer, db.ForeignKey('users.id')),
                     db.Column("task_id", db.Integer, db.ForeignKey('tasks.id'))
                     )


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    tasks = relationship("Task", back_populates="project")
    users = relationship("User", back_populates="project")


# --- USERS DB
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    #
    password = db.Column(db.String(100))
    name = db.Column(db.String(100))
    # position column to separate admins (managers) from users
    position = db.Column(db.String(100))
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    project = relationship("Project", back_populates="users")
    tasks = relationship("Task", secondary=user_task, backref="involved_users")


# --- TASKS DB
class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(), unique=True)
    description = db.Column(db.String(1000))
    deadline = db.Column(db.String(10))
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    project = relationship("Project", back_populates="tasks")
    # columns needed to define task status
    in_progress = db.Column(db.Boolean)
    task_done = db.Column(db.Boolean)
    deadline_warning = db.Column(db.Boolean)
    deadline_passed = db.Column(db.Boolean)


# db.create_all()


# ------ REUSABLE FUNCTIONS
def select_project(full_path):
    """Used for project selection in project or task edit."""
    form = UserSelectionField()
    # blank choices for empty selection in selection field
    form.selection_id.choices = [("", "")]
    # every time number of project can be different, so each time check DB for current projects
    projects = db.session.query(Project).all()
    dynamic_choices = [(str(project.id), project.name) for project in projects]
    form.selection_id.choices += dynamic_choices
    # check attribute "full_path" with regex, to determine what step is next: edit project, add task etc. and choose
    # correct url to redirect
    regex = "\w+-\w+"
    outcome = re.search(regex, full_path)
    if form.validate_on_submit():
        if "edit-project" in outcome.string:
            return redirect(url_for("edit_project", project_id=form.selection_id.data))
        elif "task" in outcome.string:
            if "add" in outcome.string:
                return redirect(url_for("add_task", project_id=form.selection_id.data))
            elif "edit" in outcome.string:
                return redirect(url_for("choose_task_to_edit", project_id=form.selection_id.data))
            elif "delete" in outcome.string:
                return redirect(url_for("choose_tasks_to_delete", project_id=form.selection_id.data))
    return render_template("selection_form.html", form=form, selection_goal="project")


def users_selection(form, selection_type, project_id, task_id=None):
    """Depending on context, shows users without project, task or users currently on project or task"""
    empty_selection = [("", "")]
    users_without_a_project = User.query.filter_by(project_id=None)
    users_on_current_project = User.query.filter_by(project_id=project_id)
    form.occupied_users.choices = empty_selection
    form.free_users.choices = empty_selection
    # from every project and task exclude managers as available to assign
    # for new project, show only users not assigned to any project
    if selection_type == "add_project":
        form.free_users.choices = [(str(user.id), user.name) for user in users_without_a_project
                                   if user.position != "manager"]
        return form
    # for project editing show users currently on project (to delete them)
    # or users not assigned to any project (to add them)
    elif selection_type == "edit_project":
        form.occupied_users.choices = [(str(user.id), user.name) for user in users_on_current_project]
        form.free_users.choices = [(str(user.id), user.name) for user in users_without_a_project
                                   if user.position != "manager"]
        return form
    # for new task show users currently on project related to task
    elif selection_type == "add_task":
        task_to_edit = Task.query.get(task_id)
        form.free_users.choices = [(str(user.id), user.name) for user in users_on_current_project
                                   if task_to_edit not in user.tasks and user.position != "manager"]
        return form
    # for project editing show users currently on project related to task, either assigned to other tasks or not
    elif selection_type == "edit_task":
        task_to_edit = Task.query.get(task_id)
        form.occupied_users.choices = [(str(user.id), user.name) for user in task_to_edit.involved_users]
        form.free_users.choices = [(str(user.id), user.name) for user in users_on_current_project
                                   if task_to_edit not in user.tasks and user.position != "manager"]
        return form


# CHANGING USER ASSIGNMENT IN DB
def change_users(users_list, action, task=None, project=None):
    if action == "add":
        for user_id in users_list:
            user = User.query.get(user_id)
            if task is not None:
                user.tasks.append(Task.query.filter_by(title=task.title).first())
            if project is not None:
                user.project_id = project.id
    else:
        for user_to_remove in users_list:
            user = User.query.get(user_to_remove)
            if task is not None:
                user.tasks.remove(Task.query.filter_by(title=task.title).first())
            if project is not None:
                user.project = None
                for task_to_remove in user.tasks:
                    user.tasks.remove(task_to_remove)
    db.session.commit()


# ------ AUTHENTICATION
# custom decorator that only allows admin (manager) to access certain views
def admin_only(func):
    @wraps(func)
    def wrapped_view(*args, **kwargs):
        try:
            user_id = int(current_user.get_id())
            user = User.query.get(user_id)
            if user.position != "manager":
                return redirect("/401")
            return func(*args, **kwargs)
        except TypeError:
            return redirect("/login")

    return wrapped_view


# custom decorator to require user to log in before entering main page
# redirects to login page
def users_only(func):
    @wraps(func)
    def wrapped_view(*args, **kwargs):
        try:
            int(current_user.get_id())
        except TypeError:
            return redirect("/login")
        return func(*args, **kwargs)

    return wrapped_view


@app.route('/change-password', methods=["GET", "POST"])
@login_required
def change_password():
    """Allows to change temporary password with new hashed and added to DB."""
    form = ChangePassword()
    if form.validate_on_submit():
        user = User.query.get(current_user.get_id())
        if check_password_hash(pwhash=current_user.password, password=form.old_password.data):
            if form.new_password.data == form.new_password_repeat.data:
                user.password = generate_password_hash(
                    password=form.new_password.data,
                    method="pbkdf2:sha256",
                    salt_length=8
                )
                db.session.commit()
                return redirect("/")
            else:
                flash("Passwords doesn't match.")
        else:
            flash("Wrong password.")
    return render_template("change_password.html", form=form)


@app.route('/login', methods=["GET", "POST"])
def login():
    form = LoginUser()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(pwhash=user.password, password=form.password.data):
            login_user(user)
            return redirect("/")
        else:
            flash("Email or password incorrect!")
    return render_template("login.html", form=form)


@app.route("/password-recovery", methods=["GET", "POST"])
def password_recovery():
    """Password recovery function sending temporary password to user's mail, only if user is firstly registered in DB"""
    form = PasswordRecovery()
    temporary_password = str()
    # random password made out of numbers only
    temporary_password_list = random.choices(range(9), k=15)
    for number in temporary_password_list:
        temporary_password += str(number)
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        user.password = generate_password_hash(
            password=temporary_password,
            method="pbkdf2:sha256",
            salt_length=8
        )
        db.session.commit()
        with smtplib.SMTP("smtp.gmail.com") as connection:
            connection.starttls()
            connection.login(user=FROM_EMAIL, password=EMAIL_PASSWORD)
            connection.sendmail(
                from_addr=FROM_EMAIL,
                to_addrs=form.email.data,
                msg=f"Subject: 'Project Manager App' password reset \n\n"
                    f"Your temporary password to 'Project Manger App' is {temporary_password}")
            flash("Email with temporary password has been sent.")
        return redirect("/login")
    return render_template("password_recovery.html", form=form)


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)
    if user:
        return user
    else:
        return None


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")


# ------ MAIN
@app.route("/", methods=["GET", "POST"])
@users_only
def index():
    # on every refresh check if any task was changed to "DONE"
    task_done_form = TaskDone()
    if task_done_form.validate_on_submit():
        # task can be set done by user, but undone only by manager
        # form works both ways, for user UNDONE button is not shown
        task = Task.query.get(task_done_form.id.data)
        if task.task_done is True:
            task.task_done = False
        else:
            task.task_done = True
            task.in_progress = False
            task.deadline_warning = False
            task.deadline_passed = False
    # determine which projects and tasks can be shown
    # for manager show all the projects with all the tasks
    # for users show only tasks on project they are assigned for
    if current_user.position == "manager":
        tasks_to_show = db.session.query(Task).all()
    else:
        project_that_user_is_on = current_user.project_id
        tasks_to_show = Project.query.get(project_that_user_is_on).tasks
    current_date_dt = datetime.now()
    current_date = str(current_date_dt)[:10]
    # set on how many days to deadline card should change color to warning
    warning_date_dt = current_date_dt + timedelta(days=3)
    warning_date = str(warning_date_dt)[:10]
    # set attributes for each task depending on it's state regarding deadline
    for task in tasks_to_show:
        if task.task_done is True:
            pass
        elif task.deadline < current_date:
            task.in_progress = False
            task.deadline_warning = False
            task.deadline_passed = True
        elif task.deadline <= warning_date:
            task.in_progress = False
            task.deadline_warning = True
            task.deadline_passed = False
        else:
            task.in_progress = True
            task.deadline_warning = False
            task.deadline_passed = False
    # save all changes
    db.session.commit()
    # take updated data from DB again depending on user position
    if current_user.position == "manager":
        all_projects = db.session.query(Project).all()
    else:
        project_that_user_is_on = current_user.project_id
        all_projects = list()
        all_projects.append(Project.query.get(project_that_user_is_on))
    return render_template("index.html", projects=all_projects, gravatar=default_avatar_mini, form=task_done_form)


# ------ MANAGE PROJECTS
@app.route("/add-project", methods=["GET", "POST"])
@admin_only
def add_project():
    form = AddProject()
    form = users_selection(form=form, selection_type="add_project", project_id=None)
    if form.validate_on_submit():
        # add new project to DB
        new_project = Project()
        new_project.name = form.name.data
        db.session.add(new_project)
        db.session.commit()
        # after committing new project withdraw it from DB to check its ID and
        # update users DB binding user with project id
        newly_added_project = Project.query.filter_by(name=form.name.data).first()
        change_users(users_list=form.free_users.data, action="add", project=newly_added_project)
        return redirect("/")
    return render_template("add_project.html", form=form, form_type="add")


@app.route("/edit-project", methods=["GET", "POST"])
@admin_only
def select_project_to_edit():
    """Middle function used to choose which project will be edited. Redirects to proper edit form."""
    return select_project(request.full_path)


@app.route("/edit-project/<int:project_id>", methods=["GET", "POST"])
@admin_only
def edit_project(project_id):
    project_to_edit = Project.query.get(project_id)
    form = AddProject(
        name=project_to_edit.name
    )
    form = users_selection(form=form, selection_type="edit_project", project_id=project_id)
    if form.validate_on_submit():
        project_to_edit.name = form.name.data
        change_users(users_list=form.occupied_users.data, action="delete", project=project_to_edit)
        change_users(users_list=form.free_users.data, action="add", project=project_to_edit)
        return redirect("/")
    return render_template("edit_project.html", form=form)


@app.route("/delete-project", methods=["GET", "POST"])
@admin_only
def delete_project():
    """Lists all projects. Multiple projects can be deleted at once."""
    form = DeleteList()
    projects = db.session.query(Project).all()
    form.list.choices = [(str(project.id), project.name) for project in projects]
    if form.validate_on_submit():
        for project_id in form.list.data:
            tasks_to_delete = Task.query.filter_by(project_id=project_id)
            for task in tasks_to_delete:
                db.session.delete(task)
            project_to_delete = Project.query.get(project_id)
            db.session.delete(project_to_delete)
        db.session.commit()
        return redirect("/")
    return render_template("delete_form.html", form=form, selection_goal="project")


# ------ MANAGE TASKS
@app.route("/add-task", methods=["GET", "POST"])
@admin_only
def select_project_to_add_task():
    """Middle function used to choose to which project task will be added. Redirects to proper add form."""
    return select_project(request.full_path)


@app.route("/add-task/<int:project_id>", methods=["GET", "POST"])
@admin_only
def add_task(project_id):
    form = AddTask()
    form = users_selection(form=form, selection_type="add_task", project_id=project_id)
    # if form is filled correctly add data to DB
    if form.validate_on_submit():
        new_task_creation = Task()
        new_task_creation.title = form.title.data
        new_task_creation.description = form.description.data
        new_task_creation.deadline = form.deadline.data
        new_task_creation.project_id = project_id
        # by default state that new task is "in progress"
        new_task_creation.in_progress = True
        new_task_creation.task_done = False
        new_task_creation.deadline_warning = False
        new_task_creation.deadline_passed = False
        db.session.add(new_task_creation)
        db.session.commit()
        change_users(users_list=form.occupied_users.data, action="add", task=new_task_creation)
        change_users(users_list=form.free_users.data, action="add", task=new_task_creation)
        return redirect("/")
    return render_template("add_task.html", form=form, form_type="add")


@app.route("/edit-task/", methods=["GET", "POST"])
@admin_only
def select_project_to_edit_task():
    """Middle function used to choose from which project task will be edited. Redirects to another select form."""
    return select_project(request.full_path)


@app.route("/edit-task/<int:project_id>", methods=["GET", "POST"])
@admin_only
def choose_task_to_edit(project_id):
    """Middle function used to choose which specific task will be edited. Redirects to proper edit form."""
    tasks_in_project = Task.query.filter_by(project_id=project_id)
    tasks = [(str(task.id), task.title) for task in tasks_in_project]
    form = UserSelectionField()
    form.selection_id.choices = [("", "")]
    form.selection_id.choices += tasks
    if form.validate_on_submit():
        return redirect(url_for("edit_task", project_id=project_id, task_id=form.selection_id.data))
    return render_template("selection_form.html", form=form, selection_goal="task")


@app.route("/edit-task/<int:project_id>/<int:task_id>", methods=["GET", "POST"])
@admin_only
def edit_task(project_id, task_id):
    task_to_edit = Task.query.get(task_id)
    form = AddTask(
        title=task_to_edit.title,
        description=task_to_edit.description,
        deadline=datetime.strptime(task_to_edit.deadline, "%Y-%m-%d"),
    )
    form = users_selection(form=form, selection_type="edit_task", project_id=project_id, task_id=task_id)
    if form.validate_on_submit():
        updated_task = Task.query.get(task_id)
        updated_task.title = form.title.data
        updated_task.description = form.description.data
        updated_task.deadline = form.deadline.data
        # check if any currently assigned user is to be removed from task
        change_users(users_list=form.occupied_users.data, action="delete", task=updated_task)
        change_users(users_list=form.free_users.data, action="add", task=updated_task)
        return redirect("/")
    return render_template("edit_tasks.html", project_id=project_id, task_id=task_id, form=form)


@app.route("/delete-tasks", methods=["GET", "POST"])
@admin_only
def select_project_to_delete_tasks():
    return select_project(request.full_path)


@app.route("/delete-tasks/<int:project_id>", methods=["GET", "POST"])
@admin_only
def choose_tasks_to_delete(project_id):
    """Middle function used to choose from which project task will be deleted. Redirects to proper delete form."""
    form = DeleteList()
    tasks = Task.query.filter_by(project_id=project_id)
    form.list.choices = [(str(task.id), task.title) for task in tasks]
    if form.validate_on_submit():
        for task_id in form.list.data:
            task_to_delete = Task.query.get(task_id)
            db.session.delete(task_to_delete)
        db.session.commit()
        return redirect("/")
    return render_template("delete_form.html", form=form, selection_goal="task")


# ------ MANAGE USERS
@app.route("/users")
@admin_only
def manage_users():
    """Allows to check all users list, no matter the project and edit them."""
    all_users = User.query.all()
    all_projects = Project.query.all()
    return render_template("users.html", all_users=all_users, all_projects=all_projects)


@app.route("/add-user", methods=["GET", "POST"])
@admin_only
def add_user():
    form = AddUser()
    if form.validate_on_submit():
        new_user = User()
        new_user.name = form.name.data
        new_user.email = form.email.data
        new_user.password = generate_password_hash(password=form.password.data, method="pbkdf2:sha256", salt_length=8)
        new_user.position = form.position.data
        db.session.add(new_user)
        db.session.commit()
        return redirect("/")
    return render_template("add_user.html", form=form)


@app.route("/edit-user/<int:user_id>", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    user = User.query.get(user_id)
    form = EditUser(
        email=user.email,
        position=user.position,
    )
    if form.validate_on_submit():
        user.email = form.email.data
        user.position = form.position.data
        db.session.commit()
        return redirect("/users")
    return render_template("edit_user.html", form=form, user=user)


@app.route("/delete-users", methods=["GET", "POST"])
@admin_only
def delete_users():
    """Lists all users which can be deleted, no matter the project."""
    form = DeleteList()
    all_users = User.query.all()
    form.list.choices = [(str(user.id), user.name) for user in all_users]
    if form.validate_on_submit():
        for user_id in form.list.data:
            user_to_delete = User.query.get(user_id)
            db.session.delete(user_to_delete)
        db.session.commit()
        return redirect("/")
    return render_template("delete_form.html", form=form, selection_goal="user")


# ------ MANAGE STATISTICS
# @app.route("/statistics")
# @admin_only
def charts():
    return render_template("charts.html")


# ------ MANAGE ERROR PAGES
@app.route("/401")
def error_401():
    return render_template("errors.html", error_type="401")


@app.route("/404")
def error_404():
    return render_template("errors.html", error_type="404")


@app.route("/500")
def error_500():
    return render_template("errors.html", error_type="500")


if __name__ == '__main__':
    app.run()
