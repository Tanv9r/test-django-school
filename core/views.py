from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import loader
from django.views.decorators.csrf import requires_csrf_token


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


@requires_csrf_token
def server_error(request):
    # Rendered without a request context: the database may be the thing that failed.
    return HttpResponseServerError(loader.get_template("500.html").render())
