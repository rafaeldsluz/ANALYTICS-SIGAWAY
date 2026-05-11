from flask import Blueprint, render_template, redirect, url_for

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    return redirect(url_for("email.index"))
