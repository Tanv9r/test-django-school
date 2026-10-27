from django.urls import path

from . import reports, views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("search/", views.search, name="search"),
    path("reports/", reports.report_index, name="reports"),
    path("reports/<slug:slug>/", reports.report_detail, name="report_detail"),
]
