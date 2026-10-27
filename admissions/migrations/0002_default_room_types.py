from decimal import Decimal

from django.db import migrations

DEFAULT_ROOM_TYPES = [
    ("General Ward", "Shared ward with basic amenities.", Decimal("50.00")),
    ("Semi-Private", "Two-bed room.", Decimal("90.00")),
    ("Private", "Single room with attached bathroom.", Decimal("150.00")),
    ("ICU", "Intensive care unit with continuous monitoring.", Decimal("400.00")),
]


def create_room_types(apps, schema_editor):
    RoomType = apps.get_model("admissions", "RoomType")
    for name, description, rate in DEFAULT_ROOM_TYPES:
        RoomType.objects.get_or_create(name=name, defaults={"description": description, "daily_rate": rate})


class Migration(migrations.Migration):
    dependencies = [("admissions", "0001_initial")]

    operations = [migrations.RunPython(create_room_types, migrations.RunPython.noop)]
