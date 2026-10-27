from django.urls import path

from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/password/", views.user_set_password, name="user_set_password"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("config/<slug:slug>/", views.config_list, name="config_list"),
    path("config/<slug:slug>/new/", views.config_form, name="config_create"),
    path("config/<slug:slug>/<int:pk>/edit/", views.config_form, name="config_edit"),
    path("config/<slug:slug>/<int:pk>/toggle/", views.config_toggle, name="config_toggle"),
    path("settings/", views.hospital_settings, name="settings"),
    path("audit-log/", views.audit_log, name="audit_log"),
]
