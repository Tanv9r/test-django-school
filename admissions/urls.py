from django.urls import path

from . import views

app_name = "admissions"

urlpatterns = [
    path("", views.AdmissionListView.as_view(), name="list"),
    path("new/", views.admission_create, name="create"),
    path("<int:pk>/", views.admission_detail, name="detail"),
    path("<int:pk>/edit/", views.admission_update, name="edit"),
    path("<int:pk>/discharge/", views.admission_discharge, name="discharge"),
    path("<int:admission_pk>/tasks/new/", views.task_create, name="task_create"),
    path("beds/", views.bed_board, name="bed_board"),
    path("rooms/", views.room_list, name="room_list"),
    path("rooms/new/", views.room_form, name="room_create"),
    path("rooms/<int:pk>/", views.room_detail, name="room_detail"),
    path("rooms/<int:pk>/edit/", views.room_form, name="room_edit"),
    path("rooms/<int:room_pk>/beds/new/", views.bed_form, name="bed_create"),
    path("rooms/<int:room_pk>/beds/<int:pk>/edit/", views.bed_form, name="bed_edit"),
    path("tasks/", views.TaskListView.as_view(), name="tasks"),
    path("tasks/<int:pk>/status/", views.task_update_status, name="task_status"),
]
