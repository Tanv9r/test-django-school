from django.db import migrations

DEFAULT_CATEGORIES = ["Analgesics", "Antibiotics", "Antihypertensives", "Antidiabetics", "Vitamins & Supplements", "Antiseptics", "Respiratory"]


def create_categories(apps, schema_editor):
    MedicineCategory = apps.get_model("pharmacy", "MedicineCategory")
    for name in DEFAULT_CATEGORIES:
        MedicineCategory.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0001_initial")]

    operations = [migrations.RunPython(create_categories, migrations.RunPython.noop)]
