from django.db import migrations

DEFAULT_DEPARTMENTS = [
    ("Cardiology", "Heart and cardiovascular care."),
    ("Neurology", "Brain, spinal cord and nervous system disorders."),
    ("Orthopedics", "Bones, joints, ligaments and muscles."),
    ("Pediatrics", "Medical care for infants, children and adolescents."),
    ("General Medicine", "Diagnosis and non-surgical treatment of adult diseases."),
    ("Gynecology", "Women's reproductive health."),
    ("Emergency", "Round-the-clock urgent and emergency care."),
]


def create_departments(apps, schema_editor):
    Department = apps.get_model("doctors", "Department")
    for name, description in DEFAULT_DEPARTMENTS:
        Department.objects.get_or_create(name=name, defaults={"description": description})


class Migration(migrations.Migration):
    dependencies = [("doctors", "0001_initial")]

    operations = [migrations.RunPython(create_departments, migrations.RunPython.noop)]
