from django.db import migrations, models


def update_company_name_in_db(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    # Update existing records to the new official company name
    for obj in SystemSetting.objects.all():
        if not obj.company_name or any(old in obj.company_name for old in ['مجتمع', 'معدنی', 'پریما']):
            obj.company_name = 'شرکت فولاد پریما'
            obj.save(update_fields=['company_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemsetting',
            name='company_name',
            field=models.CharField(default='شرکت فولاد پریما', max_length=200, verbose_name='نام شرکت'),
        ),
        migrations.RunPython(update_company_name_in_db, reverse_code=migrations.RunPython.noop),
    ]
