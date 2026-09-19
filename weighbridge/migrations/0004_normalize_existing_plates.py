import re
import unicodedata
from django.db import migrations


def normalize_existing_plates(apps, schema_editor):
    Ticket = apps.get_model("weighbridge", "WeighTicket")
    for ticket in Ticket.objects.using(schema_editor.connection.alias).all().iterator():
        plate = unicodedata.normalize("NFKC", ticket.license_plate_display or "")
        plate = plate.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک"))
        plate = plate.replace("ایران", "").replace("ايران", "")
        plate = re.sub(r"[\W_\u200c\u200d\u200e\u200f\u0640]+", "", plate).upper()
        Ticket.objects.using(schema_editor.connection.alias).filter(pk=ticket.pk).update(normalized_plate=plate)


class Migration(migrations.Migration):
    dependencies = [("weighbridge", "0003_weighticket_normalized_plate_platedaylock_and_more")]
    operations = [migrations.RunPython(normalize_existing_plates, migrations.RunPython.noop)]
